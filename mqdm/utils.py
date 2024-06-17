import queue
import threading
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from rich import progress


def try_len(it, default):
    try:
        return len(it)
    except TypeError:
        return default


class ThreadQueue:
    '''An event queue to respond to events in a separate thread.'''
    def __init__(self, fn):
        self._fn = fn
        self._closed = False
        self.queue = queue.Queue()
        self._thread = threading.Thread(target=self._monitor, daemon=True)

    def __enter__(self):
        self._closed = False
        self._thread.start()
        return self
    
    def __exit__(self, c,v,t):
        self._closed = True
        self._thread.join()

    def _monitor(self):
        while not self._closed:
            try:
                xs = self.queue.get(timeout=0.1)
                self._fn(*xs)
            except queue.Empty:
                continue

class ProcessQueue:
    '''An event queue to respond to events in a separate process.'''
    def __init__(self, fn):
        self._fn = fn
        self._closed = False
        self._manager = mp.Manager()
        self.queue = self._manager.Queue()
        self._thread = threading.Thread(target=self._monitor, daemon=True)

    def put(self, *args, **kw):
        self._queue.put(*args, **kw)
    
    def get(self, *args, **kw):
        return self._queue.get(*args, **kw)
    
    def __enter__(self):
        self._closed = False
        self._manager.__enter__()
        self._thread.start()
        return self
    
    def __exit__(self, c,v,t):
        self._closed = True
        self._thread.join()
        self._manager.__exit__(c,v,t)

    def _monitor(self):
        while not self._closed:
            try:
                xs = self.queue.get(timeout=0.1)
                self._fn(*xs)
            except queue.Empty:
                continue

POOL_QUEUES = {
    'thread': ThreadQueue,
    'process': ProcessQueue,
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
