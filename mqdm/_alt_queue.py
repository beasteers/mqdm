''''''
import sys
import rich
from . import utils
import mqdm

import time
import random
import queue
import threading
import multiprocessing as mp

import rich
from rich import progress
from .bars import Bars



class Bars(Bars):
    def __init__(self, desc=None, *, pool_mode='process', transient=True, **kw):
        self._tasks = {}
        self._pq = POOL_QUEUES[pool_mode](self._on_message)
        self._remote = Remote(self._pq)
        self.pool_mode = pool_mode

        super().__init__(desc, transient=transient, **kw)

    def remote(self):
        return self._remote

    def __enter__(self):
        if not self._entered:
            self._pq.__enter__()
            super().__enter__()
        return self

    def __exit__(self, c,v,t):
        if self._entered:
            self._pq.__exit__(c,v,t)
            super().__exit__(c,v,t)

    def add(self, desc="", visible=False, start=False, **kw):
        return RemoteBar(self._remote, self._add_task(desc, visible=visible, start=start, **kw))

    def _add_task(self, desc="", proxy=None, **kw):
        task_id = self.pbar.add_task(description=desc or "", parent_task_id=self.task_id, **kw)
        if task_id not in self._tasks:
            self._tasks[task_id] = {}
        if proxy is not None:
            self._task_id_proxy[proxy] = task_id
        return task_id

    _task_id_proxy = {}
    def _on_message(self, task_id, method, args, data):
        if method == '__remote_add':
            if task_id in self._tasks:
                raise ValueError(f"Task with id {task_id} already exists")
            self._add_task(*args, proxy=task_id, **data)

        if isinstance(task_id, tuple):
            task_id = self._task_id_proxy[task_id]
        if method == 'raw_print':
            print(*args, end='')
        elif method == 'rich_print':
            rich.print(*args, end='', sep=" ", **data)
        elif method == 'update':
            self._update(task_id, *args, **data)
        elif method == 'start_task':
            self._tasks[task_id]['complete'] = False
            self.pbar.start_task(*args, task_id=task_id, **data)
        elif method == 'stop_task':
            self._tasks[task_id]['complete'] = True
            self.pbar.stop_task(*args, task_id=task_id, **data)
            self._update(None)
        elif method == '__pause':
            mqdm.pause(*args, **data)
        else:
            getattr(self.pbar, method)(*args, **data)

    def _update(self, task_id, **data):
        if task_id is not None:
            # -------------------------------- update task ------------------------------- #
            # update the task-specific progress bar
            self.pbar.update(task_id, **data, refresh=False)

            # update progress bar visibility
            task = self.pbar._tasks[task_id]
            current = task.completed
            total = task.total
            transient = task.fields.get('transient', True)
            complete = total is not None and current >= total
            task.visible = bool(total is not None and not complete or not transient)
            self._tasks[task_id]['complete'] = complete

        # ------------------------------ update overall ------------------------------ #
        n_finished = sum(bool(d.get('complete', False)) for d in self._tasks.values())
        self.pbar.update(self.task_id, completed=n_finished, total=len(self))



class Remote:
    _console = None
    def __init__(self, queue):
        self.queue = queue

    def _new(self):
        return RemoteBar(self.queue, self.queue.random_id())
    
    def _call(self, task_id, method, *args, **kw):
        self.queue.put((task_id, method, args, kw))

    def __call__(self, **kw):
        bar = self._new()
        self._call(bar.task_id, '__remote_add', (), bar._process_args(**kw))
        return bar

    @property
    def console(self):
        if self._console is None:
            self._console = rich.console.Console(file=utils.QueueFile(self.queue))
        return self._console

    def __getstate__(self):
        state = self.__dict__.copy()
        state['_console'] = None
        return state
    
    def __setstate__(self, state):
        self.__dict__.update(state)
        mqdm._remote = self
    
    # -------------------------- Top Level mqdm Aliases -------------------------- #
    
    def pause(self, paused=True):
        self._call(None, '__pause', paused)

    def print(self, *a, **kw):
        self.console.print(*a, **kw)
        return self
    
    def get(self, i=-1):
        return mqdm.get(i)

    def set_description(self, desc, i=-1):
        return mqdm.set_description(desc)


class RemoteBar:
    _entered = False
    _get_desc = None
    total = None
    def __init__(self, remote, task_id):
        self._remote = remote
        self.task_id = task_id

    def _call(self, method, *args, **kw):
        self._remote._call(self.task_id, method, *args, **kw)

    def __setstate__(self, state):
        self.__dict__.update(state)
        mqdm._add_instance(self)

    def __enter__(self, **kw):
        if not self._entered:
            self._call('start_task', **kw)
            mqdm._add_instance(self)
            self._entered = True
        return self

    def __exit__(self, exc_type, exc_value, tb):
        if self._entered:
            self._call('stop_task')
            mqdm._remove_instance(self)
            self._entered = False

    def __del__(self):
        try:
            if sys.meta_path is None:
                return 
            self.__exit__(None, None, None)
        except (AttributeError, ImportError, BrokenPipeError, FileNotFoundError) as e:
            pass

    def __len__(self):
        return self.total or 0

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._iter)
    
    def _get_iter(self, iter, **kw):
        for i, x in enumerate(iter):
            self.update(i>0, arg_=x)
            yield x
        self.update()

    def __call__(self, iter=None, total=None, desc=None, **kw):
        if isinstance(iter, str) and desc is None:  # infer string as description
            iter, kw['description'] = None, iter
        if iter is None:
            return self.update(total=total, **kw)

        total = utils.try_len(iter, self.total) if total is None else total
        self.update(0, total=total, description=desc or ..., **kw)
        def _with_iter():
            if self._entered:
                yield from self._get_iter(iter, **kw)
                return
            with self:
                yield from self._get_iter(iter, **kw)
        self._iter = _with_iter()
        return self

    def print(self, *a, **kw):
        self._remote.print(*a, **kw)
        return self

    def set_description(self, desc):
        return self.update(0, description=desc or "")

    def _process_args(self, *, arg_=..., **kw):
        kw = {k: v for k, v in kw.items() if v is not ...}
        if 'total' in kw:
            self.total = kw['total']

        # get description
        if 'desc' in kw:
            kw['description'] = kw.pop('desc')
        if 'description' in kw and callable(kw['description']):
            self._get_desc = kw.pop('description')
        if 'description' not in kw and self._get_desc is not None and arg_ is not ...:
            kw['description'] = self._get_desc(arg_)
        if 'description' in kw and kw.get('description') is None:
            kw['description'] = ''

        return kw

    def update(self, n=1, *, arg_=..., **kw):
        kw = self._process_args(arg_=arg_, **kw)
        if n or kw:
            self._call('update', advance=n, **kw)
        return self






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
    None: SequentialQueue,
}
