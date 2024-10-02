import queue
import threading
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from matplotlib.dates import TH
import rich
from rich import progress


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


class MsgQueue:
    _max_cleanup_attempts = 100
    def __init__(self, fn):
        self._fn = fn
        self._closed = False
        self._thread = threading.Thread(target=self._monitor, daemon=True)

    def __enter__(self):
        self._closed = False
        try:
            self._thread.start()
        except RuntimeError:
            pass
        return self
    
    def __exit__(self, c,v,t):
        self._closed = True
        self._thread.join()
        for i in range(self._max_cleanup_attempts):
            if not self._read(timeout=0.005):
                break

    def _read(self, timeout=0.1):
        try:
            xs = self.queue.get(timeout=timeout)
            self._fn(*xs)
            return True
        except queue.Empty:
            return False

    def _monitor(self):
        while not self._closed:
            self._read()

    def put(self, xs, **kw):
        self.queue.put(xs, **kw)

    def get(self, xs, **kw):
        return self.queue.get(xs, **kw)

class SequentialQueue:
    '''An event queue to respond to events in the main thread.'''
    def __init__(self, fn):
        self._fn = fn
        self.queue = self

    def __enter__(self):
        return self

    def __exit__(self, c,v,t):
        pass

    def put(self, xs):
        self._fn(*xs)


class ThreadQueue(MsgQueue):
    '''An event queue to respond to events in a separate thread.'''
    def __init__(self, fn):
        super().__init__(fn)
        self.queue = queue.Queue()

class ProcessQueue(MsgQueue):
    '''An event queue to respond to events in a separate process.'''
    def __init__(self, fn, manager=None):
        self._self_managed = manager is not None
        self._manager = manager or mp.Manager()
        self.queue = self._manager.Queue()
        super().__init__(fn)

    def __getstate__(self):
        state = self.__dict__.copy()
        state['_manager'] = None
        state['_thread'] = None
        return state

    def __enter__(self):
        if self._self_managed:
            self._manager.__enter__()
        super().__enter__()
        return self
    
    def __exit__(self, c,v,t):
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



class MofNColumn(progress.MofNCompleteColumn):
    '''A progress column that shows the current vs. total count of items.'''
    def render(self, task):
        total = f'{int(task.total):,}' if task.total is not None else "?"
        return progress.Text(
            f"{int(task.completed):,d}{self.separator}{total}",
            style="progress.download",
        )
