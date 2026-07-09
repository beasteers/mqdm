from __future__ import annotations

import atexit
from contextlib import contextmanager
import logging
import threading
import weakref
from collections import OrderedDict
from time import monotonic
from typing import TYPE_CHECKING, Any, Callable, Literal, TypeAlias, TypedDict

import rich

from .backend import ProgressBackend
from . import utils

if TYPE_CHECKING:
    from logging import Formatter, Logger
    from weakref import ReferenceType

    from ._logging import MQDMHandler
    from .bar import mqdm as MQDMBar
    from .executor import T_POOL_MODE
    from .proxy import MqdmManager


class LoggingConfig(TypedDict, total=False):
    logger_name: str
    level: int | None
    markup: bool
    capture_warnings: WarningCapturePolicy
    formatter_fmt: str | None
    formatter_datefmt: str | None

WarningCapturePolicy: TypeAlias = "bool | Literal['process']"


_all_runtimes: weakref.WeakSet[Runtime] = weakref.WeakSet()
_LOCAL_EVENT_TYPE = type(threading.Event())
_RUNTIME_CONTEXT_KEY = "runtime_context"


class Runtime:
    """Owns progress, pause, and logging state for one mqdm session.

    A runtime coordinates the active progress display, worker-process plumbing,
    and optional logging integration. Most code can rely on the current runtime
    implicitly, but constructing a separate ``Runtime`` is useful when you want
    isolated progress or logging behavior.
    """

    def __init__(
        self,
        on_event: Callable[[dict], Any] | None = None,
        *,
        progress_kw: dict[str, Any] | None = None,
        auto_refresh: bool = True,
        refresh_per_second: float = 8,
        speed_estimate_period: float = 60.0,
        redirect_stdout: bool = True,
        redirect_stderr: bool = True,
        expand: bool = False,
    ) -> None:
        self.pbar: ProgressBackend | None = None
        self.manager: MqdmManager | None = None
        # When set, emitted events are handed to this sink (a dict) instead of
        # being rendered to the console. Must be picklable to reach workers — a
        # multiprocessing manager Queue's ``.put`` qualifies. ``None`` keeps the
        # default console behavior.
        self.on_event: Callable[[dict], Any] | None = on_event
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
        self._progress_kw: dict[str, Any] = {
            **(progress_kw or {}),
            "auto_refresh": auto_refresh,
            "refresh_per_second": refresh_per_second,
            "speed_estimate_period": speed_estimate_period,
            "redirect_stdout": redirect_stdout,
            "redirect_stderr": redirect_stderr,
            "expand": expand,
        }
        _all_runtimes.add(self)

    @property
    def progress_options(self) -> dict[str, Any]:
        """Runtime-scoped options used when creating the shared Progress."""
        return dict(self._progress_kw)

    def configure(
        self,
        *,
        progress_kw: dict[str, Any] | None = None,
        auto_refresh: bool | None = None,
        refresh_per_second: float | None = None,
        speed_estimate_period: float | None = None,
        redirect_stdout: bool | None = None,
        redirect_stderr: bool | None = None,
        expand: bool | None = None,
    ) -> Runtime:
        """Configure runtime-scoped Progress options before the first bar."""
        updates = {
            key: value for key, value in {
                "auto_refresh": auto_refresh,
                "refresh_per_second": refresh_per_second,
                "speed_estimate_period": speed_estimate_period,
                "redirect_stdout": redirect_stdout,
                "redirect_stderr": redirect_stderr,
                "expand": expand,
            }.items()
            if value is not None
        }
        if progress_kw:
            updates = {**progress_kw, **updates}
        if not updates:
            return self
        if self.pbar is not None:
            raise RuntimeError("Cannot configure runtime progress options after the shared progress bar has been created.")
        self._progress_kw.update(updates)
        return self

    def __getstate__(self) -> dict[str, Any]:
        state: dict[str, Any] = self.__dict__.copy()
        pbar = state.get('pbar')
        if pbar is not None and not getattr(pbar, 'multiprocess', False):
            state['pbar'] = None
        state['manager'] = None
        state['instances'] = OrderedDict()
        state['logging_handlers'] = None
        # Warning capture is process-local state and must be reinstalled in workers.
        state['capture_warnings'] = False
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
        pbar = self.get_pbar(pool_mode=pool_mode)
        pbar.start()
        self.pause_event.set()
        self.shutdown_event.set()

    def install_pool_worker(self, pool_mode: T_POOL_MODE = None) -> None:
        self.pbar = self.get_pbar(pool_mode=pool_mode)
        self.pbar.start()

        cfg = self.logging_config
        if cfg:
            logger_name = cfg.get("logger_name", "root")
            self.install_logging(
                logger=logging.getLogger(logger_name),
                level=cfg.get("level"),
                capture_warnings=cfg.get("capture_warnings", "process"),
                markup=cfg.get("markup", True),
                formatter=(
                    logging.Formatter(cfg["formatter_fmt"], cfg.get("formatter_datefmt"))
                    if cfg.get("formatter_fmt")
                    else None
                ),
            )

    def default_progress_columns(self, bytes: bool = False) -> tuple[Any, ...]:
        """Return the default column layout for a progress bar."""
        from rich import progress
        from . import progress_columns

        return (
            "[progress.description]{task.description}",
            progress.BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.0f}%",
            progress_columns.MofNColumn(bytes=bytes),
            progress_columns.SpeedColumn(bytes=bytes),
            progress_columns.TimeElapsedColumn(compact=True),
            progress.TimeRemainingColumn(compact=True),
            progress.SpinnerColumn(),
        )

    def new_pbar(self, pool_mode: T_POOL_MODE = None, bytes: bool = False, columns: tuple[Any, ...] | None = None, **kw: Any) -> ProgressBackend:
        from . import proxy

        kw.setdefault('refresh_per_second', 8)
        columns = columns or self.default_progress_columns(bytes=bytes)
        if pool_mode == 'process':
            return self.get_manager().mqdm_Progress(*columns, **kw)
        return proxy.Progress(*columns, **kw)

    def get_pbar(self, pool_mode: T_POOL_MODE = None, start: bool = False, **kw: Any) -> ProgressBackend:
        pbar = self.pbar
        if pbar is None:
            pbar = self.pbar = self.new_pbar(pool_mode=pool_mode, **{**self._progress_kw, **kw})
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
    
    @contextmanager
    def group(self):
        """Group progress bars."""
        self.keep_depth += 1
        self.keep = True
        try:
            yield
        finally:
            self.keep_depth = max(self.keep_depth - 1, 0)
            self.keep = self.keep_depth > 0
            if not self.keep:
                self.clear_pbar()

    def get_context(self) -> dict[str, Any]:
        from .executor import _get_local
        return dict(_get_local(_RUNTIME_CONTEXT_KEY, {}) or {})

    @contextmanager
    def context(self, **context: Any):
        from .executor import _clear_local, _set_local

        prev = self.get_context()
        _set_local(**{_RUNTIME_CONTEXT_KEY: {**prev, **context}})
        try:
            yield self
        finally:
            if prev:
                _set_local(**{_RUNTIME_CONTEXT_KEY: prev})
            else:
                _clear_local(_RUNTIME_CONTEXT_KEY)

    def handle_event(self, event_type: str, **data: Any) -> Any:
        """Dispatch a runtime event. Override to centralize/customize output.

        Terminal output is delegated to :meth:`_write`, which routes through the
        active progress bar so it lands in whichever process owns the live
        display (the manager process in ``pool_mode='process'``).
        """
        data.setdefault("context", self.get_context())
        if event_type == "print":
            return self._write(*data.get("args", ()), **data.get("kw", {}))
        if event_type == "log":
            return self._write(data.get("message", ""), markup=data.get("markup", True))
        return None

    def _write(self, *args: Any, **kw: Any) -> Any:
        pbar = self.pbar
        if pbar is not None:
            return pbar.write(*args, **kw)
        return rich.get_console().print(*args, **kw)

    def emit(self, event_type: str, **data: Any) -> Any:
        """Emit an event. Routes to ``on_event`` if set, else the console."""
        data.setdefault("context", self.get_context())
        if self.on_event is not None:
            return self.on_event({"type": event_type, **data})
        return self.handle_event(event_type, **data)

    def set_base_context(self, **context: Any) -> None:
        """Set a persistent base context for this thread/worker.

        Unlike :meth:`context` (a scoped push/pop), this seeds long-lived values
        such as worker identity that every subsequent event should carry.
        """
        from .executor import _set_local
        _set_local(**{_RUNTIME_CONTEXT_KEY: {**self.get_context(), **context}})

    def print(self, *args: Any, **kw: Any) -> Any:
        return self.emit("print", args=args, kw=kw)

    def install_worker_context(
        self,
        *,
        pbar: ProgressBackend,
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
        capture_warnings: WarningCapturePolicy = 'process',
        markup: bool = True,
        formatter: Formatter | None = None,
    ) -> MQDMHandler:
        """Attach an ``MQDMHandler`` to a logger for this runtime.

        Args:
            logger: Logger to attach to. Defaults to the root logger.
            level: Optional handler level to set on the attached handler.
            capture_warnings: Warning routing policy. ``False`` leaves warnings
                alone, ``True`` captures warnings immediately, and
                ``"process"`` captures warnings automatically only in process
                pool workers installed by mqdm.
            markup: Whether to allow Rich markup in emitted log messages.
            formatter: Optional formatter for the handler.

        Returns:
            The attached or reused ``MQDMHandler`` instance.
        """
        from ._logging import MQDMHandler, capture_warnings as _capture_warnings, release_warnings as _release_warnings

        logger = logger or logging.getLogger()
        handler = MQDMHandler.ensure_on_logger(logger, self, formatter=formatter, markup=markup)
        if level is not None:
            logger.setLevel(level)
            handler.setLevel(level)

        if capture_warnings is True:
            _capture_warnings(runtime=self)
        elif capture_warnings == 'process' and not utils.is_main_process():
            _capture_warnings(runtime=self)
        else:
            _release_warnings(runtime=self)

        self.logging_config = {
            "logger_name": logger.name,
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

        if logger is None:
            MQDMHandler.remove_from_all_loggers(self)
        else:
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
        self.uninstall_logging()
        self.close_instances()
        self.shutdown_manager()


_runtime = Runtime()


def _current_runtime() -> Runtime:
    try:
        from .executor import _get_local

        return _get_local('runtime', _runtime)
    except Exception:
        return _runtime


def configure(**kw: Any) -> Runtime:
    """Configure the implicit global runtime before its first progress bar."""
    return _runtime.configure(**kw)


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
