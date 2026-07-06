from concurrent.futures import ProcessPoolExecutor as _StdlibProcessPoolExecutor
from concurrent.futures.process import _ExceptionWithTraceback, _ResultItem as _StdlibResultItem

from ._process_pool_keyboard import _run_process_worker


class ResultItem(_StdlibResultItem):
    def __init__(self, work_id, exception=None, result=None, exit_pid=None):
        self.work_id = work_id
        self.exception = exception
        self.result = result
        self.exit_pid = exit_pid


def sendback_result(result_queue, work_id, result=None, exception=None, exit_pid=None):
    try:
        result_queue.put(ResultItem(work_id, result=result, exception=exception, exit_pid=exit_pid))
    except BaseException as e:
        exc = _ExceptionWithTraceback(e, e.__traceback__)
        result_queue.put(ResultItem(work_id, exception=exc, exit_pid=exit_pid))


def process_worker(call_queue, result_queue, initializer, initargs, max_tasks=None):
    return _run_process_worker(
        call_queue=call_queue,
        result_queue=result_queue,
        initializer=initializer,
        initargs=initargs,
        max_tasks=max_tasks,
        sendback_result=sendback_result,
        stop_on_keyboard_interrupt=False,
    )


def process_worker_keyboard_interrupt(call_queue, result_queue, initializer, initargs, max_tasks=None):
    return _run_process_worker(
        call_queue=call_queue,
        result_queue=result_queue,
        initializer=initializer,
        initargs=initargs,
        max_tasks=max_tasks,
        sendback_result=sendback_result,
        stop_on_keyboard_interrupt=True,
    )


class ProcessPoolExecutorCompat(_StdlibProcessPoolExecutor):
    _max_tasks_per_child = None

    def _spawn_process(self):
        p = self._mp_context.Process(
            target=process_worker,
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
