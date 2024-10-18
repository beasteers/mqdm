import sys
import time
import random
import queue
import threading
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import rich
from rich import progress
from .proxy import get_manager


class args:
    '''Storing Function Arguments for later.
    
    Example:
    ```
    def fn(a, b=2, c=3):
        print(a, b, c)

    fn_args = [args(i, c=i*2) for i in range(3)]
    for arg in fn_args:
        arg(fn, b=2)
    ```
    '''
    def __init__(self, *a, **kw):
        self.a = a
        self.kw = kw

    def __getitem__(self, i):
        return self.a[i] if isinstance(i, int) else self.kw[i]

    def __call__(self, fn, *a, **kw):
        return fn(*self.a, *a, **dict(self.kw, **kw)) if callable(fn) else fn
    
    @classmethod
    def call(cls, fn, x, *a, **kw):
        return cls.from_item(x)(fn, *a, **kw)
    
    @classmethod
    def from_item(cls, x, *a, **kw):
        return x.merge_general(*a, **kw) if isinstance(x, cls) else cls(x, *a, **kw)

    @classmethod
    def from_items(cls, items, *a, **kw):
        return [cls.from_item(x, *a, **kw) for x in items]

    def merge_general(self, *a, **kw):
        return args(*self.a, *a, **dict(kw, **self.kw))


def maybe_call(fn, *a, **kw):
    return fn(*a, **kw) if callable(fn) else fn


# def try_len(it, default=None):
#     try:
#         return len(it)
#     except TypeError:
#         return default

def try_len(it, default=None):
    if it is None:
        return default
    if isinstance(it, int):
        return it
    try:
        return len(it)
    except TypeError:
        pass

    try:
        x = type(it).__length_hint__(it)
        return x if isinstance(x, int) else default
    except (AttributeError, TypeError):
        return default


class BaseQueue:
    def __init__(self, fn):
        self._fn = fn

    def __enter__(self):
        return self

    def __exit__(self, c,v,t):
        pass

    def random_id(self):
        return (0, id(self), time.time(), random.random())


class SequentialQueue(BaseQueue):
    '''An event queue to respond to events in the main thread.'''
    def __init__(self, fn):
        self._fn = fn
        self.queue = self

    def put(self, xs):
        self._fn(*xs)


class MsgQueue(BaseQueue):
    _max_cleanup_attempts = 100
    def __init__(self, fn):
        self._fn = fn
        self._closed = False
        self._thread = threading.Thread(target=self._monitor, daemon=True)

    def __getstate__(self):
        state = self.__dict__.copy()
        state['_thread'] = None
        state['_fn'] = None
        return state

    def __enter__(self):
        if self._thread is None: return self
        self._closed = False
        try:
            self._thread.start()
        except RuntimeError:
            pass
        return self
    
    def __exit__(self, c,v,t):
        self._closed = True
        if self._thread is None: return
        self._thread.join()
        for i in range(self._max_cleanup_attempts):
            if not self._read(timeout=0.005):
                break

    def _read(self, timeout=0.1):
        try:
            xs = self.queue.get(timeout=timeout)
        except queue.Empty:
            return False
        self._fn(*xs)
        return True

    def _monitor(self):
        while not self._closed:
            self._read()

    def put(self, xs, **kw):
        self.queue.put(xs, **kw)

    def get(self, xs, **kw):
        return self.queue.get(xs, **kw)

    def raise_exception(self, e):
        pass


class ThreadQueue(MsgQueue):
    '''An event queue to respond to events in a separate thread.'''
    def __init__(self, fn):
        super().__init__(fn)
        self.queue = queue.Queue()
    #     self._exc_info = None

    def random_id(self):
        return (threading.get_ident(), random.random(), id(self), time.time(), random.random())

    # def __enter__(self):
    #     self._exc_info = None
    #     return super().__enter__()

    # def raise_exception(self):
    #     if self._exc_info:
    #         raise self._exc_info[1].with_traceback(self._exc_info[2])

    # def _read(self, timeout=0.1):
    #     try:
    #         xs = self.queue.get(timeout=timeout)
    #     except queue.Empty:
    #         return False
    #     try:
    #         self._fn(*xs)
    #     except Exception as e:
    #         self._exc_info = sys.exc_info()
    #     return True


class ProcessQueue(MsgQueue):
    '''An event queue to respond to events in a separate process.'''
    def __init__(self, fn, manager=None):
        self._self_managed = manager is not None
        self._manager = manager or mp.Manager()
        # self._manager = manager or get_manager() #mp.Manager()
        self.queue = self._manager.Queue()
        super().__init__(fn)

    def random_id(self):
        return (mp.current_process().pid, id(self), time.time(), random.random())

    def __getstate__(self):
        state = self.__dict__.copy()
        state['_manager'] = None
        state['_thread'] = None
        state['_fn'] = None
        return state

    def __enter__(self):
        if self._thread is None: return self
        if self._self_managed:
            self._manager.__enter__()
        super().__enter__()
        return self
    
    def __exit__(self, c,v,t):
        if self._thread is None: return
        super().__exit__(c,v,t)
        if self._self_managed:
            self._manager.__exit__(c,v,t)


POOL_QUEUES = {
    'thread': ThreadQueue,
    'process': ProcessQueue,
    'sequential': SequentialQueue,
}

POOL_EXECUTORS = {
    'thread': ThreadPoolExecutor,
    'process': ProcessPoolExecutor,
}


class QueueFile:
    isatty=rich.get_console().file.isatty
    def __init__(self, q, task_id=None):
        self._queue = q
        self.task_id = task_id
        self._buffer = []
        self.kw = {}

    def write(self, *args, **kw):
        self._buffer.extend(args)
        self.kw = kw

    def flush(self):
        if self._buffer:
            self._buffer, buffer = [], self._buffer
            self._queue.put((self.task_id, 'raw_print', buffer, self.kw))
            self.kw = {}


class MofNColumn(progress.MofNCompleteColumn):
    '''A progress column that shows the current vs. total count of items.'''
    def render(self, task):
        total = f'{int(task.total):,}' if task.total is not None else "?"
        return progress.Text(
            f"{int(task.completed):,d}{self.separator}{total}",
            style="progress.download",
        )


class SpeedColumn(progress.TaskProgressColumn):
    """Renders human readable transfer speed."""
    def render(self, task):
        """Show data transfer speed."""
        speed = task.finished_speed or task.speed
        if speed is None:
            return progress.Text("", style="progress.data.speed")
        end = 'x/s'
        if speed < 1:
            speed = 1 / speed
            end = 's/x'
        unit, suffix = progress.filesize.pick_unit_and_suffix(
            int(speed), ["", "×10³", "×10⁶", "×10⁹", "×10¹²"], 1000)
        
        return progress.Text(f"{speed/unit:.1f}{suffix}{end}", justify='right', style="progress.data.speed")


class TimeElapsedColumn(progress.TimeRemainingColumn):
    """Renders time elapsed."""
    def __init__(self, compact: bool = False, **kw):
        self._compact = compact
        super().__init__(**kw)

    def render(self, task):
        """Show time elapsed."""
        elapsed = task.finished_time if task.finished else task.elapsed
        if elapsed is None:
            return progress.Text("--:--" if self._compact else "-:--:--", style="progress.elapsed")
        minutes, seconds = divmod(int(elapsed), 60)
        hours, minutes = divmod(minutes, 60)
        return progress.Text(
            (f"{hours:d}:" if hours or not self._compact else "") + 
            f"{minutes:02d}:{seconds:02d}", style="progress.elapsed")
