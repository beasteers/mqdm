import os
import sys
from concurrent.futures._base import LOGGER
from concurrent.futures.process import _ExceptionWithTraceback, _ResultItem as _StdlibResultItem, ProcessPoolExecutor as _StdlibProcessPoolExecutor


if sys.version_info < (3, 11):
    # Pre-3.11 _ResultItem predates max_tasks_per_child and can't carry exit_pid,
    # so subclass it to accept (and ignore) the extra field.
    class _ResultItem(_StdlibResultItem):
        def __init__(self, work_id, exception=None, result=None, exit_pid=None):
            self.work_id = work_id
            self.exception = exception
            self.result = result
            self.exit_pid = exit_pid

    # _max_tasks_per_child is only set on the instance in 3.11+; default it here
    # so the shared _spawn_process works on older Pythons too.
    _StdlibProcessPoolExecutor._max_tasks_per_child = None  # pre-3.11 doesn't have this attribute
else:
    _ResultItem = _StdlibResultItem


def _sendback_result(result_queue, work_id, result=None, exception=None, exit_pid=None):
    try:
        result_queue.put(_ResultItem(work_id, result=result, exception=exception, exit_pid=exit_pid))
    except BaseException as e:
        exc = _ExceptionWithTraceback(e, e.__traceback__)
        result_queue.put(_ResultItem(work_id, exception=exc, exit_pid=exit_pid))


def process_worker_keyboard_interrupt(call_queue, result_queue, initializer, initargs, max_tasks=None):
    """Process-pool worker that reports a KeyboardInterrupt like any other
    exception and then exits, letting the parent shut the pool down cleanly."""
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
            result_queue.put(os.getpid())
            return

        if max_tasks is not None:
            num_tasks += 1
            if num_tasks >= max_tasks:
                exit_pid = os.getpid()

        try:
            result = call_item.fn(*call_item.args, **call_item.kwargs)
        except KeyboardInterrupt as e:
            exc = _ExceptionWithTraceback(e, e.__traceback__)
            _sendback_result(result_queue, call_item.work_id, exception=exc, exit_pid=os.getpid())
            return
        except BaseException as e:
            exc = _ExceptionWithTraceback(e, e.__traceback__)
            _sendback_result(result_queue, call_item.work_id, exception=exc, exit_pid=exit_pid)
        else:
            _sendback_result(result_queue, call_item.work_id, result=result, exit_pid=exit_pid)
            del result

        del call_item

        if exit_pid is not None:
            return



class ProcessPoolExecutor(_StdlibProcessPoolExecutor):
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
