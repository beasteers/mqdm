from __future__ import annotations

import atexit
from contextlib import contextmanager
import logging
import threading
import weakref
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Callable, Literal, TypeAlias, TypedDict

import rich

from .backend import ProgressBackend, ProgressBackendFactory, ProxyConvertibleBackend
from . import utils

if TYPE_CHECKING:
    from logging import Formatter, Logger
    from weakref import ReferenceType

    from ._logging import MQDMHandler
    from .bar import mqdm as MQDMBar
    from .command_proxy import QueueCommandBridge
    from .executor import T_POOL_MODE


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
_RUNTIME_CONTEXTS_KEY = "runtime_contexts"
DEFAULT_REFRESH_PER_SECOND = 8


class RichProgressFactory:
    """Default backend factory that constructs Rich-backed mqdm progress.

    Rich owns the default column layout, so the runtime no longer hardcodes any
    renderer-specific presentation details.
    """

    def create(
        self,
        *,
        runtime: Runtime,
        columns: tuple[Any, ...] | None = None,
        **kw: Any,
    ) -> ProgressBackend:
        from . import progress

        columns = columns or progress.Progress.default_progress_columns()
        return progress.Progress(*columns, **kw)


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
        backend_factory: ProgressBackendFactory | None = None,
        progress_kw: dict[str, Any] | None = None,
        auto_refresh: bool = True,
        refresh_per_second: float = DEFAULT_REFRESH_PER_SECOND,
        speed_estimate_period: float = 60.0,
        redirect_stdout: bool = True,
        redirect_stderr: bool = True,
        expand: bool = False,
    ) -> None:
        self.pbar: ProgressBackend | None = None
        self.command_bridge: QueueCommandBridge | None = None
        self.backend_factory: ProgressBackendFactory = backend_factory or RichProgressFactory()
        self.paused: bool = False
        self._context_key = f"runtime:{id(self)}"
        # When set, emitted events are handed to this sink (a dict) instead of
        # being rendered to the console. Must be picklable to reach workers — a
        # multiprocessing queue's ``.put`` qualifies. ``None`` keeps the
        # default console behavior.
        self.on_event: Callable[[dict], Any] | None = on_event
        self.pause_event: threading.Event = threading.Event()
        self.pause_event.set()
        self.shutdown_event: threading.Event = threading.Event()
        self.shutdown_event.set()
        self.instances: OrderedDict[int, ReferenceType[MQDMBar]] = OrderedDict()
        self.logging_handlers: weakref.WeakSet[MQDMHandler] = weakref.WeakSet()
        self._sustain_depth: int = 0
        self.capture_warnings: bool = False
        self.logging_config: LoggingConfig | None = None
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
        backend_factory: ProgressBackendFactory | None = None,
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
            if backend_factory is None:
                return self
        if self.pbar is not None:
            raise RuntimeError("Cannot configure runtime progress options after the shared progress bar has been created.")
        if backend_factory is not None:
            self.backend_factory = backend_factory
        self._progress_kw.update(updates)
        return self

    def __getstate__(self) -> dict[str, Any]:
        state: dict[str, Any] = self.__dict__.copy()
        pbar = state.get('pbar')
        if pbar is not None and not getattr(pbar, 'multiprocess', False):
            state['pbar'] = None
        state['command_bridge'] = None
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

    def _get_context_store(self) -> dict[str, dict[str, Any]]:
        """Return the thread-local per-runtime context mapping."""
        from .executor import _get_local, _set_local

        contexts = _get_local(_RUNTIME_CONTEXTS_KEY)
        if contexts is None:
            contexts = {}
            _set_local(**{_RUNTIME_CONTEXTS_KEY: contexts})
        return contexts

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

    def new_pbar(self, columns: tuple[Any, ...] | None = None, **kw: Any) -> ProgressBackend:
        """Construct a backend instance using the configured factory."""
        return self.backend_factory.create(runtime=self, columns=columns, **kw)

    def _ensure_process_backend(self, pbar: ProgressBackend) -> ProgressBackend:
        """Promote a local backend when process mode requires IPC-safe access."""
        if pbar.multiprocess:
            return pbar
        if isinstance(pbar, ProxyConvertibleBackend):
            proxy = pbar.convert_proxy(runtime=self)
            self.install_command_bridge(proxy)
            return proxy
        raise RuntimeError(
            f"Progress backend {type(pbar).__name__!r} does not support process mode promotion."
        )

    def get_pbar(self, pool_mode: T_POOL_MODE = None, **kw: Any) -> ProgressBackend:
        pbar = self.pbar
        if pbar is None:
            pbar = self.pbar = self.new_pbar(**{**self._progress_kw, **kw})
        if pool_mode == 'process':
            pbar = self.pbar = self._ensure_process_backend(pbar)
        return pbar

    def clear_pbar(self, strict: bool = True, force: bool = False) -> None:
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
        elif self._sustain_depth > 0:
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

    def pause(self, paused: bool = True) -> _pause_exit:
        pbar = self.pbar
        prev_paused = self.paused
        self.paused = paused
        if pbar is not None:
            if paused:
                pbar.stop()
                self.pause_event.clear()
            else:
                pbar.start()
                self.pause_event.set()
        return _pause_exit(prev_paused)
    
    @contextmanager
    def sustain(self):
        """Keep the live progress display alive across this block.

        Normally mqdm tears the display down as soon as the last bar finishes,
        so a sequence of separate bars renders one at a time — each freezes into
        the scrollback as the next begins. Inside ``sustain()`` a single display
        spans the whole block: the bars stack and stay visible together as a
        growing panel while ``print``/logging flows above them. Nestable.
        """
        self._sustain_depth += 1
        try:
            yield
        finally:
            self._sustain_depth = max(self._sustain_depth - 1, 0)
            if self._sustain_depth == 0:
                self.clear_pbar(strict=False)

    def get_context(self) -> dict[str, Any]:
        """Get context for this runtime without leaking values across runtimes."""
        return dict(self._get_context_store().get(self._context_key, {}))

    @contextmanager
    def context(self, **context: Any):
        from .executor import _clear_local

        contexts = self._get_context_store()
        prev = self.get_context()
        contexts[self._context_key] = {**prev, **context}
        try:
            yield self
        finally:
            if prev:
                contexts[self._context_key] = prev
            else:
                contexts.pop(self._context_key, None)
                if not contexts:
                    _clear_local(_RUNTIME_CONTEXTS_KEY)

    def handle_event(self, event_type: str, **data: Any) -> Any:
        """Dispatch a runtime event. Override to centralize/customize output.

        Terminal output is delegated to :meth:`_write`, which routes through the
        active progress bar so it lands in whichever process owns the live
        display (the parent process in ``pool_mode='process'``).
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
        contexts = self._get_context_store()
        contexts[self._context_key] = {**self.get_context(), **context}

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

    def install_command_bridge(self, pbar: ProgressBackend) -> None:
        from .command_proxy import TransportCommandProxy

        if not isinstance(pbar, TransportCommandProxy):
            print("Provided pbar is not a TransportCommandProxy.")
            return
        if self.command_bridge is not None:
            self.command_bridge.stop()
        bridge = pbar.create_command_bridge()
        bridge.start()
        self.command_bridge = bridge

    def shutdown_command_bridge(self) -> None:
        bridge = self.command_bridge
        if bridge is None:
            return
        try:
            bridge.stop()
        finally:
            self.command_bridge = None

    def atexit(self) -> None:
        self.uninstall_logging()
        self.close_instances()
        self.shutdown_command_bridge()


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
