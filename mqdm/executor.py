import os
from typing import Literal
from concurrent.futures._base import FINISHED, RUNNING
from concurrent.futures import Future, Executor, ThreadPoolExecutor, ProcessPoolExecutor
from concurrent.futures._base import LOGGER
# from concurrent.futures.process import _sendback_result
from concurrent.futures.process import _ResultItem, _ExceptionWithTraceback
from concurrent.futures.process import _RemoteTraceback  # used in bar.py
import mqdm as M


# ---------------------------------------------------------------------------- #
#                                 Monkey Patch                                 #
# At some point, _max_tasks_per_child and exit_pid were added to ProcessPoolExecutor.
# At some point we can remove this monkey patch if we drop support for older Python versions.
# ---------------------------------------------------------------------------- #

class _ResultItem(_ResultItem):
    def __init__(self, work_id, exception=None, result=None, exit_pid=None):
        self.work_id = work_id
        self.exception = exception
        self.result = result
        self.exit_pid = exit_pid


def _sendback_result(result_queue, work_id, result=None, exception=None, exit_pid=None):
    try:
        result_queue.put(_ResultItem(work_id, result=result, exception=exception, exit_pid=exit_pid))
    except BaseException as e:
        exc = _ExceptionWithTraceback(e, e.__traceback__)
        result_queue.put(_ResultItem(work_id, exception=exc, exit_pid=exit_pid))


def _process_worker(call_queue, result_queue, initializer, initargs, max_tasks=None):
    if initializer is not None:
        try:
            initializer(*initargs)
        except BaseException:
            LOGGER.critical('Exception in initializer:', exc_info=True)
            return
    num_tasks = 0
    exit_pid = None
    while True:
        call_item = call_queue.get(block=True)
        if call_item is None:
            # Wake up queue management thread
            result_queue.put(os.getpid())
            return

        if max_tasks is not None:
            num_tasks += 1
            if num_tasks >= max_tasks:
                exit_pid = os.getpid()

        try:
            r = call_item.fn(*call_item.args, **call_item.kwargs)
        except KeyboardInterrupt as e:  # +++++ Added: ensure KeyboardInterrupt stops the worker
            exc = _ExceptionWithTraceback(e, e.__traceback__)
            _sendback_result(result_queue, call_item.work_id, exception=exc, exit_pid=os.getpid())
            return
        except BaseException as e:
            exc = _ExceptionWithTraceback(e, e.__traceback__)
            _sendback_result(result_queue, call_item.work_id, exception=exc, exit_pid=exit_pid)
        else:
            _sendback_result(result_queue, call_item.work_id, result=r, exit_pid=exit_pid)
            del r

        del call_item

        if exit_pid is not None:
            return


class ProcessPoolExecutor(ProcessPoolExecutor):
    _max_tasks_per_child = None  # specific python version compatibility (?)

    def _spawn_process(self):
        p = self._mp_context.Process(
            target=_process_worker,
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

# ---------------------------------------------------------------------------- #
#                                  Sequential                                  #
# ---------------------------------------------------------------------------- #


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



# ---------------------------------------------------------------------------- #
#                         Concurrent Futures Executors                         #
# ---------------------------------------------------------------------------- #


T_POOL_MODE = Literal['process', 'thread', 'sequential', None]
POOL_EXECUTORS = {
    'thread': ThreadPoolExecutor,
    'process': ProcessPoolExecutor,
    'sequential': SequentialExecutor,
    None: SequentialExecutor,
}


def executor(pool_mode: T_POOL_MODE='process', bar_kw: dict=None, **kw) -> Executor:
    """Return the appropriate executor for the pool mode of the progress bar."""
    pbar = M._get_pbar(pool_mode=pool_mode)
    M._pause_event.set()
    M._shutdown_event.set()
    return POOL_EXECUTORS[pool_mode](initializer=_pbar_initializer, initargs=[
        pool_mode, pbar, M._pause_event, M._shutdown_event, bar_kw or {}], **kw)

import threading
_thread_local_data = threading.local()
def _pbar_initializer(pool_mode, pbar, event, shutdown_event, defaults=None):
    """Initialize the progress bar for the worker thread/process."""
    M.pbar = pbar
    M._pause_event = event
    M._shutdown_event = shutdown_event
    _thread_local_data.defaults = defaults or {}

def _get_local(key, default=None):
    """Get a thread-local variable."""
    return getattr(_thread_local_data, key, default)
