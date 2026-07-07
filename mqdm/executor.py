import sys
from typing import Callable, Literal
from concurrent.futures._base import FINISHED, RUNNING
from concurrent.futures import Future, Executor, ThreadPoolExecutor, ProcessPoolExecutor as _StdlibProcessPoolExecutor
from concurrent.futures.process import _RemoteTraceback  # used in bar.py
import mqdm as M

# ----------- Process Pool Executor with KeyboardInterrupt Handling ---------- #

from ._process_pool_keyboard import process_worker_keyboard_interrupt
_ProcessPoolExecutorCompat = _StdlibProcessPoolExecutor
if sys.version_info < (3, 11):
    from ._process_pool_compat import ProcessPoolExecutorCompat as _ProcessPoolExecutorCompat, process_worker_keyboard_interrupt

class ProcessPoolExecutor(_ProcessPoolExecutorCompat):
    def _spawn_process(self):
        p = self._mp_context.Process(
            target=process_worker_keyboard_interrupt,
            args=(
                self._call_queue,
                self._result_queue,
                self._initializer,
                self._initargs,
                self._max_tasks_per_child,
            ),
        )
        p.start()
        self._processes[p.pid] = p


# ---------------------------- Sequential Executor --------------------------- #


class SequentialFuture(Future):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._evaluated = False
        self._processes = {}
        with self._condition:  # so as_completed will return it
            self._state = FINISHED

    def _evaluate(self):
        _rich_traceback_omit = True
        if not self._evaluated:
            with self._condition:
                self._state = RUNNING
            try:
                self.set_result(self._fn(*self._args, **self._kwargs))
            except Exception as exc:
                self.set_exception(exc)
            self._evaluated = True

    def result(self, timeout=None):
        _rich_traceback_omit = True
        self._evaluate()
        return super().result(timeout)

    def exception(self, timeout=None):
        _rich_traceback_omit = True
        self._evaluate()
        return super().exception(timeout)


class SequentialExecutor(Executor):
    def __init__(self, max_workers=None, initializer=None, initargs=()):
        super().__init__()
        self._initializer = initializer
        self._initargs = initargs

    def __enter__(self):
        if self._initializer is not None:
            self._initializer(*self._initargs)
        return super().__enter__()

    def submit(self, fn, *args, **kwargs):
        return SequentialFuture(fn, *args, **kwargs)


# --------------------------------- Executors -------------------------------- #


T_POOL_MODE = Literal['process', 'thread', 'sequential', None]
POOL_EXECUTORS = {
    'thread': ThreadPoolExecutor,
    'process': ProcessPoolExecutor,
    'sequential': SequentialExecutor,
    None: SequentialExecutor,
}


def executor(pool_mode: T_POOL_MODE='process', bar_kw: dict=None, runtime=None, **kw) -> Executor:
    """Return the appropriate executor for the pool mode of the progress bar."""
    return POOL_EXECUTORS[pool_mode](initializer=Initializer(pool_mode=pool_mode, defaults=bar_kw, runtime=runtime), **kw)


# -------------------------------- Initializer ------------------------------- #


import threading
_thread_local_data = threading.local()
def _get_local(key, default=None):
    """Get a thread-local variable."""
    return getattr(_thread_local_data, key, default)


def _set_local(**values):
    """Set one or more thread-local variables."""
    for key, value in values.items():
        setattr(_thread_local_data, key, value)


def _clear_local(*keys):
    """Remove thread-local variables if present."""
    for key in keys:
        if hasattr(_thread_local_data, key):
            delattr(_thread_local_data, key)


class Initializer:
    def __init__(self, fn: Callable=None, *a, pool_mode: T_POOL_MODE='process', defaults: dict=None, runtime=None, **kw):
        self.fn = M.fn(fn, *a, **kw) if fn is not None else None
        self.defaults = defaults if defaults is not None else {}
        self.runtime = runtime or M._current_runtime()
        self.runtime.prepare_pool_worker(pool_mode=pool_mode)

    def __call__(self):
        """Initialize the progress bar for the worker thread/process."""
        _set_local(runtime=self.runtime, defaults=self.defaults)
        self.runtime.install_pool_worker()
        if self.fn is not None:
            self.fn()
