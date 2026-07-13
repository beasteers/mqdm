from __future__ import annotations

import atexit
from contextlib import contextmanager
import logging
import threading
import time
import weakref
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Callable, Literal, TypeAlias, TypedDict


import rich

from .backend import ProgressBackend, ProxyConvertibleBackend, create_backend as _default_create_backend
from . import utils

if TYPE_CHECKING:
    from logging import Formatter, Logger
    from weakref import ReferenceType

    from .utils._logging import MQDMHandler
    from .bar import mqdm as MQDMBar
    from .utils.proxy import QueueCommandDispatch
    from .events.events import EventEnvelope
    from .parallel.executor import T_POOL_MODE


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


class Runtime:
    """Owns progress, pause, and logging state for one mqdm session.

    A runtime coordinates the active progress display, worker-process plumbing,
    and optional logging integration. Most code can rely on the current runtime
    implicitly, but constructing a separate ``Runtime`` is useful when you want
    isolated progress or logging behavior.
    """

    def __init__(
        self,
        on_event: Callable[[EventEnvelope], Any] | None = None,
        *,
        create_backend: Callable[..., ProgressBackend] | None = None,
        backend_options: dict[str, Any] | None = None,
    ) -> None:
        self.pbar: ProgressBackend | None = None
        self.command_dispatch: QueueCommandDispatch | None = None
        self.paused: bool = False
        self._context_key = f"runtime:{id(self)}"
        # Event sink.  In process pools this callable is pickled and runs
        # inside each worker, so it typically must be a transport that
        # serialises events back to the parent process (e.g.
        # ``multiprocessing.Queue.put`` or a picklable adapter).  For thread /
        # sequential pools any callable works, including an in-process
        # accumulator.  ``None`` (the default) disables the event stream so
        # the zero-cost check in :meth:`emit` returns immediately.
        self.on_event: Callable[[EventEnvelope], Any] | None = on_event
        self.pause_event: threading.Event = threading.Event()
        self.pause_event.set()
        self.shutdown_event: threading.Event = threading.Event()
        self.shutdown_event.set()
        self.instances: OrderedDict[int, ReferenceType[MQDMBar]] = OrderedDict()
        self.logging_handlers: weakref.WeakSet[MQDMHandler] = weakref.WeakSet()
        self._sustain_depth: int = 0
        self._last_pause_exit: _pause_exit | None = None
        self.capture_warnings: bool = False
        self.logging_config: LoggingConfig | None = None
        self.pause_wait_ttl_seconds: float = 0.5
        self._create_backend = create_backend or _default_create_backend
        self._backend_options: dict[str, Any] = dict(backend_options or {})
        _all_runtimes.add(self)

    @property
    def backend_options(self) -> dict[str, Any]:
        """Runtime-scoped options used when creating the shared Progress."""
        return dict(self._backend_options)

    def configure(
        self,
        *,
        create_backend: Callable[..., ProgressBackend] | None = None,
        backend_options: dict[str, Any] | None = None,
    ) -> Runtime:
        """Set display options for this runtime, before its first bar.

        ``backend_options`` are forwarded to the progress backend (Rich by default,
        e.g. ``refresh_per_second``, ``expand``, ``redirect_stdout``); ``create_backend``
        swaps the backend factory entirely. Raises if the shared display already exists.
        """
        if backend_options is None and create_backend is None:
            return self
        if self.pbar is not None:
            raise RuntimeError("Cannot configure runtime options after the shared progress bar has been created.")
        if create_backend is not None:
            self._create_backend = create_backend
        if backend_options is not None:
            self._backend_options.update(backend_options)
        return self

    def __getstate__(self) -> dict[str, Any]:
        state: dict[str, Any] = self.__dict__.copy()
        pbar = state.get('pbar')
        if pbar is not None and not getattr(pbar, 'multiprocess', False):
            state['pbar'] = None
        state['command_dispatch'] = None
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
        from .parallel.executor import _get_local, _set_local

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

    def new_pbar(self, **kw: Any) -> ProgressBackend:
        return self._create_backend(runtime=self, **kw)

    def _ensure_command_dispatch(self) -> QueueCommandDispatch:
        from .utils.proxy import QueueCommandDispatch

        dispatch = self.command_dispatch
        if dispatch is not None:
            return dispatch
        dispatch = self.command_dispatch = QueueCommandDispatch()
        dispatch.start()
        return dispatch

    def _ensure_process_backend(self, pbar: ProgressBackend) -> ProgressBackend:
        """Promote a local backend when process mode requires IPC-safe access."""
        if pbar.multiprocess:
            return pbar
        if isinstance(pbar, ProxyConvertibleBackend):
            return pbar.convert_proxy(command_dispatch=self._ensure_command_dispatch())
        raise RuntimeError(
            f"Progress backend {type(pbar).__name__!r} does not support process mode promotion."
        )

    def get_pbar(self, pool_mode: T_POOL_MODE = None, **kw: Any) -> ProgressBackend:
        pbar = self.pbar
        if pbar is None:
            pbar = self.pbar = self.new_pbar(**{**self._backend_options, **kw})
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
            self.shutdown_command_dispatch()
        elif self.instances:
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
            # The command dispatch is only needed while a process-mode pbar is
            # live. Tearing it down with the pbar keeps its per-worker reply ends
            # and per-pool handler registrations from accumulating across pools.
            self.shutdown_command_dispatch()

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
        return _pause_exit(prev_paused, self)
    
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
        """Attach key/values to every event emitted inside this block.

        Emitted events (``print``, ``log``, task lifecycle) carry a ``context`` dict;
        this pushes extra fields onto it for the duration of the ``with`` block and
        pops them on exit. Useful for tagging output with a phase, request id, or
        similar so an ``on_event`` sink can group it. Nestable; see
        :meth:`set_base_context` for long-lived values like worker identity.

        Example:
            ```python
            with runtime.context(phase="index"):
                mqdm.print("scanning")   # event context includes phase="index"
            ```
        """
        from .parallel.executor import _clear_local

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
        """Default fallback for events with no sink attached.

        **Output events** (``print``, ``log``) are forwarded to the active
        progress-bar console so they interleave with the live display.
        If no progress bar is active, they fall back to the default Rich
        console.

        **Telemetry events** (``task_started``, ``task_finished``,
        ``task_failed``) are no-ops here — they exist purely for
        programmatic consumers attached via ``on_event``.
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
        """Emit an event. Routes to ``on_event`` if set, else :meth:`handle_event`.

        Every event dict receives a ``time`` timestamp (``time.time()``,
        float) pegged to this call site and the current runtime context.
        """
        data.setdefault("context", self.get_context())
        data.setdefault("time", time.time())
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
        from .utils._logging import MQDMHandler, capture_warnings as _capture_warnings, release_warnings as _release_warnings

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
        from .utils._logging import MQDMHandler, release_warnings as _release_warnings

        if logger is None:
            MQDMHandler.remove_from_all_loggers(self)
        else:
            MQDMHandler.remove_from_logger(logger, self)
        if self.capture_warnings:
            _release_warnings(runtime=self)
        self.logging_config = None

    def shutdown_command_dispatch(self) -> None:
        dispatch = self.command_dispatch
        if dispatch is None:
            return
        dispatch.closed.set()
        try:
            dispatch.stop()
        finally:
            self.command_dispatch = None

    def atexit(self) -> None:
        self.uninstall_logging()
        dispatch = self.command_dispatch
        if dispatch is not None:
            dispatch.closed.set()
        self.close_instances()
        self.shutdown_command_dispatch()


_runtime = Runtime()


def _current_runtime() -> Runtime:
    try:
        from .parallel.executor import _get_local

        return _get_local('runtime', _runtime)
    except Exception:
        return _runtime


@contextmanager
def using(runtime: Runtime):
    """Make ``runtime`` the current runtime for the duration of this block.

    Bars, pools, prints, and logging created inside pick it up automatically, so
    you can run a differently-configured display for a section without threading
    ``runtime=`` through every call. Thread-local and restored on exit — safe to
    nest, and it never leaks to other threads.

    For a single, program-wide look, prefer :func:`configure` at startup; reach
    for this only when a specific block needs its own runtime.

    Example:
        ```python
        compact = mqdm.Runtime(backend_options={"columns": (
            "[progress.description]{task.description}",
            mqdm.columns.TwoToneColumn(bar_width=None),
        )})
        with mqdm.using(compact):
            for x in mqdm.mqdm(items):   # uses `compact`, no runtime= needed
                ...
        ```
    """
    from .parallel.executor import _get_local, _set_local, _clear_local

    prev = _get_local('runtime', None)
    _set_local(runtime=runtime)
    try:
        yield runtime
    finally:
        if prev is None:
            _clear_local('runtime')
        else:
            _set_local(runtime=prev)


def configure(**kw: Any) -> Runtime:
    """Set display options on the implicit global runtime, before its first bar.

    Keywords are forwarded to the progress backend (Rich by default), e.g.
    ``refresh_per_second``, ``expand``, ``redirect_stdout`` / ``redirect_stderr``,
    ``speed_estimate_period``. Must run before any bar is created — it raises once the
    shared display exists.

    Example:
        ```python
        import mqdm as M
        M.configure(refresh_per_second=12, expand=True)
        for x in M.mqdm(range(10)):
            ...
        ```
    """
    return _runtime.configure(backend_options=kw or None)


class _pause_exit:

    def __init__(self, prev_paused: bool, runtime: Runtime) -> None:
        self._prev_paused = prev_paused
        self._runtime = runtime
        runtime._last_pause_exit = self

    def __enter__(self) -> None:
        pass

    def __exit__(self, c: object, exc: BaseException | None, t: object) -> None:
        if not exc and not self._prev_paused and self is self._runtime._last_pause_exit:
            self._runtime.pause(False)


def _atexit_runtimes() -> None:
    for runtime in list(_all_runtimes):
        try:
            runtime.atexit()
        except Exception:
            pass


atexit.register(_atexit_runtimes)
