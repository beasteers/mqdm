from __future__ import annotations

import atexit
import logging
import threading
import weakref
from collections import OrderedDict
from time import monotonic
from typing import TYPE_CHECKING, Any, TypeAlias, TypedDict

import rich
from rich import progress

from . import progress_columns
from . import utils

if TYPE_CHECKING:
    from logging import Formatter, Logger
    from weakref import ReferenceType

    from ._logging import MQDMHandler
    from .bar import mqdm as MQDMBar
    from .executor import T_POOL_MODE
    from .proxy import MqdmManager, Progress, ProgressProxy


class LoggingConfig(TypedDict, total=False):
    level: int | None
    markup: bool
    capture_warnings: bool
    formatter_fmt: str | None
    formatter_datefmt: str | None


ProgressLike: TypeAlias = "Progress | ProgressProxy"


_all_runtimes: weakref.WeakSet[Runtime] = weakref.WeakSet()
_LOCAL_EVENT_TYPE = type(threading.Event())


class Runtime:
    """Owns progress, pause, and logging state for one mqdm session.

    A runtime coordinates the active progress display, worker-process plumbing,
    and optional logging integration. Most code can rely on the current runtime
    implicitly, but constructing a separate ``Runtime`` is useful when you want
    isolated progress or logging behavior.
    """

    def __init__(self) -> None:
        self.pbar: ProgressLike | None = None
        self.manager: MqdmManager | None = None
        self.pause_event: threading.Event = threading.Event()
        self.pause_event.set()
        self.shutdown_event: threading.Event = threading.Event()
        self.shutdown_event.set()
        self.instances: OrderedDict[int, ReferenceType[MQDMBar]] = OrderedDict()
        self.logging_handlers: weakref.WeakSet[MQDMHandler] = weakref.WeakSet()
        self.keep: bool = False
        self.keep_depth: int = 0
        self.capture_warnings: bool = False
        self.logging_config: LoggingConfig | None = None
        self.next_pause_check_time: float = 0
        self.pause_wait_ttl_seconds: float = 0.5
        _all_runtimes.add(self)

    def __getstate__(self) -> dict[str, Any]:
        state: dict[str, Any] = self.__dict__.copy()
        state['manager'] = None
        state['instances'] = OrderedDict()
        state['logging_handlers'] = None
        for key in ('pause_event', 'shutdown_event'):
            event = state.get(key)
            if isinstance(event, _LOCAL_EVENT_TYPE):
                state[f'{key}_is_set'] = event.is_set()
                state[key] = None
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        pause_event_is_set = state.pop('pause_event_is_set', True)
        shutdown_event_is_set = state.pop('shutdown_event_is_set', True)
        self.__dict__.update(state)
        if self.pause_event is None:
            self.pause_event = threading.Event()
            (self.pause_event.set if pause_event_is_set else self.pause_event.clear)()
        if self.shutdown_event is None:
            self.shutdown_event = threading.Event()
            (self.shutdown_event.set if shutdown_event_is_set else self.shutdown_event.clear)()
        self.instances = OrderedDict()
        self.logging_handlers = weakref.WeakSet()
        _all_runtimes.add(self)

    def prepare_pool_worker(self, pool_mode: T_POOL_MODE = None) -> None:
        self.get_pbar(pool_mode=pool_mode)
        self.pause_event.set()
        self.shutdown_event.set()

    def install_pool_worker(self) -> None:
        try:
            from ._logging import _install_from_config

            _install_from_config(self.logging_config)
        except Exception:
            pass

    def new_pbar(self, pool_mode: T_POOL_MODE = None, bytes: bool = False, **kw: Any) -> ProgressLike:
        from . import proxy

        kw.setdefault('refresh_per_second', 8)
        columns = (
            "[progress.description]{task.description}",
            progress.BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.0f}%",
            progress_columns.MofNColumn(bytes=bytes),
            progress_columns.SpeedColumn(bytes=bytes),
            progress_columns.TimeElapsedColumn(compact=True),
            progress.TimeRemainingColumn(compact=True),
            progress.SpinnerColumn(),
        )
        if pool_mode == 'process':
            return self.get_manager().mqdm_Progress(*columns, **kw)
        return proxy.Progress(*columns, **kw)

    def get_pbar(self, pool_mode: T_POOL_MODE = None, start: bool = True, **kw: Any) -> ProgressLike:
        pbar = self.pbar
        if pbar is None:
            pbar = self.pbar = self.new_pbar(pool_mode=pool_mode, **kw)
        elif pool_mode == 'process' and not pbar.multiprocess:
            pbar = self.pbar = pbar.convert_proxy(runtime=self)
        if start:
            pbar.start()
        return pbar

    def clear_pbar(self, strict: bool = True, force: bool = False, soft: bool = False) -> None:
        if force:
            for bar_ref in reversed(list(self.instances.values())):
                bar = bar_ref()
                if bar is not None:
                    bar.close(remove=False)
                    bar.disable = True
            if self.pbar is not None:
                self.pbar.stop()
            self.pbar = None
        if self.instances:
            if strict:
                raise RuntimeError("Cannot clear progress bar while instances are still active.")
        elif not utils.is_main_process():
            if strict:
                raise RuntimeError("Cannot clear progress bar in a subprocess.")
        elif soft or self.keep:
            if self.pbar is not None:
                self.pbar.refresh()
        else:
            pbar = self.pbar
            if pbar is not None:
                pbar.start()
                pbar.refresh()
                pbar.stop()
            self.pbar = None

    def add_instance(self, bar: MQDMBar) -> MQDMBar:
        self.instances.setdefault(hash(bar), weakref.ref(bar))
        return bar

    def remove_instance(self, bar: MQDMBar) -> None:
        self.instances.pop(hash(bar), None)

    def get_instance(self, i: int = -1) -> MQDMBar:
        try:
            return list(self.instances.values())[i]()
        except IndexError:
            raise IndexError(f'No progress bar found at index {i} in list of length {len(self.instances)}')

    def close_instances(self) -> None:
        for bar_ref in list(self.instances.values()):
            bar = bar_ref()
            if bar is not None:
                bar.close()
        self.instances.clear()

    def pause_wait(self) -> None:
        self.pause_event.wait()

    def ttl_pause_wait(self) -> None:
        now = monotonic()
        if now >= self.next_pause_check_time:
            self.next_pause_check_time = now + self.pause_wait_ttl_seconds
            self.pause_event.wait()

    def pause(self, paused: bool = True) -> _pause_exit:
        pbar = self.pbar
        prev_paused = getattr(pbar, 'paused', False)
        if pbar is not None:
            pbar.paused = paused
            if paused:
                pbar.stop()
                self.pause_event.clear()
            else:
                pbar.start()
                self.pause_event.set()
        return _pause_exit(prev_paused)

    def print(self, *args: Any, **kw: Any) -> Any:
        if self.pbar is not None:
            return self.pbar.print(*args, **kw)
        return rich.print(*args, **kw)

    def install_worker_context(
        self,
        *,
        pbar: ProgressLike,
        pause_event: threading.Event,
        shutdown_event: threading.Event,
        logging_config: LoggingConfig | None,
    ) -> None:
        self.pbar = pbar
        self.pause_event = pause_event
        self.shutdown_event = shutdown_event
        self.logging_config = logging_config

    def install_logging(
        self,
        logger: Logger | None = None,
        *,
        level: int | None = None,
        capture_warnings: bool = False,
        markup: bool = True,
        formatter: Formatter | None = None,
    ) -> MQDMHandler:
        """Attach an ``MQDMHandler`` to a logger for this runtime.

        Args:
            logger: Logger to attach to. Defaults to the root logger.
            level: Optional handler level to set on the attached handler.
            capture_warnings: Whether to route Python warnings through logging
                for this runtime.
            markup: Whether to allow Rich markup in emitted log messages.
            formatter: Optional formatter for the handler.

        Returns:
            The attached or reused ``MQDMHandler`` instance.
        """
        from ._logging import MQDMHandler, capture_warnings as _capture_warnings, release_warnings as _release_warnings

        logger = logger or logging.getLogger()
        handler = MQDMHandler.ensure_on_logger(logger, self, formatter=formatter, markup=markup)
        if level is not None:
            handler.setLevel(level)

        if capture_warnings:
            _capture_warnings(runtime=self)
        else:
            _release_warnings(runtime=self)

        self.logging_config = {
            "level": level,
            "markup": markup,
            "capture_warnings": capture_warnings,
            "formatter_fmt": (formatter._fmt if formatter else None),
            "formatter_datefmt": (formatter.datefmt if formatter else None),
        }
        return handler

    def uninstall_logging(self, logger: Logger | None = None) -> None:
        """Remove this runtime's logging handler from a logger.

        Args:
            logger: Logger to detach from. Defaults to the root logger.
        """
        from ._logging import MQDMHandler, release_warnings as _release_warnings

        logger = logger or logging.getLogger()
        MQDMHandler.remove_from_logger(logger, self)
        if self.capture_warnings:
            _release_warnings(runtime=self)
        self.logging_config = None

    def get_manager(self) -> MqdmManager:
        if self.manager is not None:
            return self.manager
        from .proxy import MqdmManager

        manager = MqdmManager()
        manager.start()
        self.manager = manager
        self.pause_event = manager.Event()
        self.pause_event.set()
        self.shutdown_event = manager.Event()
        self.shutdown_event.set()
        return manager

    def shutdown_manager(self) -> None:
        manager = self.manager
        if manager is None:
            return
        try:
            shutdown = getattr(manager, 'shutdown', None)
            if shutdown is not None:
                shutdown()
        finally:
            self.manager = None

    def atexit(self) -> None:
        self.close_instances()
        self.shutdown_manager()


_runtime = Runtime()


def _current_runtime() -> Runtime:
    try:
        from .executor import _get_local

        return _get_local('runtime', _runtime)
    except Exception:
        return _runtime


class _pause_exit:
    last: _pause_exit | None = None

    def __init__(self, prev_paused: bool) -> None:
        self.prev_paused = prev_paused
        _pause_exit.last = self

    def __enter__(self) -> None:
        pass

    def __exit__(self, c: object, exc: BaseException | None, t: object) -> None:
        if not exc and not self.prev_paused and self is _pause_exit.last:
            _current_runtime().pause(False)


def _atexit_runtimes() -> None:
    for runtime in list(_all_runtimes):
        try:
            runtime.atexit()
        except Exception:
            pass


atexit.register(_atexit_runtimes)
