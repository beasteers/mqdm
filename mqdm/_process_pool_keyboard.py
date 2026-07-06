import os
from concurrent.futures._base import LOGGER
from concurrent.futures.process import _ExceptionWithTraceback, _ResultItem


def _sendback_result(result_queue, work_id, result=None, exception=None, exit_pid=None):
    try:
        result_queue.put(_ResultItem(work_id, result=result, exception=exception, exit_pid=exit_pid))
    except BaseException as e:
        exc = _ExceptionWithTraceback(e, e.__traceback__)
        result_queue.put(_ResultItem(work_id, exception=exc, exit_pid=exit_pid))


def _run_process_worker(call_queue, result_queue, initializer, initargs, max_tasks, sendback_result, stop_on_keyboard_interrupt):
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
            sendback_result(result_queue, call_item.work_id, exception=exc, exit_pid=os.getpid() if stop_on_keyboard_interrupt else exit_pid)
            if stop_on_keyboard_interrupt:
                return
        except BaseException as e:
            exc = _ExceptionWithTraceback(e, e.__traceback__)
            sendback_result(result_queue, call_item.work_id, exception=exc, exit_pid=exit_pid)
        else:
            sendback_result(result_queue, call_item.work_id, result=result, exit_pid=exit_pid)
            del result

        del call_item

        if exit_pid is not None:
            return


def process_worker_keyboard_interrupt(call_queue, result_queue, initializer, initargs, max_tasks=None):
    return _run_process_worker(
        call_queue=call_queue,
        result_queue=result_queue,
        initializer=initializer,
        initargs=initargs,
        max_tasks=max_tasks,
        sendback_result=_sendback_result,
        stop_on_keyboard_interrupt=True,
    )
