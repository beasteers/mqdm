''''''
from functools import wraps
from concurrent.futures import as_completed
from typing import Callable
import rich
from . import utils
from .bar import Bar
import mqdm

'''
-- Multi Process:

Bars(**kw) -> add_task(overall, **kw)
Bars.add(**kw) -> add_task(item, **kw)

RemoteBar__init__() -> --
RemoteBar.__call__(**kw) -> RemoteBar.__enter__(**kw)
RemoteBar.__enter__(**kw) -> start_task(item, **kw)
iter(RemoteBar(**kw)) -> start_task(item, **kw)
RemoteBar.update(**kw) -> update(item, **kw)

-- Single Process:

Bar(**kw) -> add_task(item, **kw)
Bar.__call__(**kw) -> iter(Bar(**kw))
Bar.update(**kw) -> update(item, **kw)

'''


class Bars(Bar):
    _iter = None

    def __init__(self, desc=None, *, bytes=False, pbar=None, pool_mode='process', transient=False, **kw):
        self._tasks = {}
        self._pq = utils.POOL_QUEUES[pool_mode](self._on_message)
        self.pool_mode = pool_mode

        super().__init__(desc, pbar=pbar, bytes=bytes, transient=transient, **kw)

    def __enter__(self):
        if not self._entered:
            self._pq.__enter__()
            super().__enter__()
        return self

    def __exit__(self, c,v,t):
        if self._entered:
            self._pq.__exit__(c,v,t)
            super().__exit__(c,v,t)

    def _get_iter(self, iter, desc=None, **kw):
        for i, x in enumerate(iter):
            pbar = self.add(desc=utils.maybe_call(desc, x, i), **kw)
            yield x, pbar

    def __len__(self):
        return max(len(self._tasks), self.total or 0)

    def add(self, desc, visible=False, start=False, **kw):
        task_id = self.pbar.add_task(description=desc or "", visible=visible, start=start, **kw)
        self._tasks[task_id] = {}
        return RemoteBar(self._pq.queue, task_id)

    def _on_message(self, task_id, method, args, data):
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
        n_finished = sum(bool(d and d.get('complete', False)) for d in self._tasks.values())
        self.pbar.update(self.task_id, completed=n_finished, total=len(self))

    @classmethod
    def mqdms(cls, iter=None, desc=None, main_desc=None, bytes=False, pbar=None, transient=False, subbar_kw={}, **kw):
        return cls(desc=main_desc, bytes=bytes, pbar=pbar, transient=transient, **kw)(iter, desc, **(subbar_kw or {}))

    @classmethod
    def ipool(
            cls, 
            fn: Callable, iter, 
            *a, 
            desc: str|Callable="", 
            main_desc="", 
            mainbar_kw: dict={}, 
            subbar_kw: dict={}, 
            n_workers=8, 
            ordered=False, 
            pool_mode='process', 
            **kw):
        """Execute a function in a process pool with a progress bar for each task."""
        # initialize progress bars
        pbars = cls.mqdms(
            iter, 
            pool_mode=pool_mode, 
            desc=desc or (lambda x, i: f'task {i}'), 
            main_desc=main_desc,
            subbar_kw=subbar_kw, 
            **(mainbar_kw or {})
        )

        # no workers, just run the function
        if n_workers < 2 or pool_mode == 'sequential':
            for arg, pbar in pbars:
                arg = utils.args.from_item(arg, *a, **kw)
                yield arg(fn, pbar=pbar)
            return

        # run the function in a process pool
        with pbars, pbars.executor(max_workers=n_workers) as executor:
            futures = []
            for arg, pbar in pbars:
                arg = utils.args.from_item(arg, *a, **kw)
                futures.append(executor.submit(fn, *arg.a, pbar=pbar, **arg.kw))

            for f in futures if ordered else as_completed(futures):
                yield f.result()

    @classmethod
    @wraps(ipool)
    def pool(cls, *a, **kw):
        return list(cls.ipool(*a, **kw))

    # not sure which name is better
    imap = ipool
    map = pool

    def executor(self, **kw):
        return utils.POOL_EXECUTORS[self.pool_mode](**kw)


class RemoteBar:
    _entered = False
    _console = None
    total = None
    def __init__(self, q, task_id):
        self._queue = q
        self.task_id = task_id
        self.__enter__()

    @property
    def console(self):
        if self._console is None:
            self._console = rich.console.Console(file=QueueFile(self._queue, self.task_id))
        return self._console

    def __getstate__(self):
        state = self.__dict__.copy()
        state['_console'] = None
        return state

    def _call(self, method, *args, **kw):
        self._queue.put((self.task_id, method, args, kw))

    def __enter__(self, **kw):
        if not self._entered:
            self._call('start_task', **kw)
            self._entered = True
        return self

    def __exit__(self, exc_type, exc_value, tb):
        if self._entered:
            self._call('stop_task')
            self._entered = False

    def __del__(self):
        try:
            self.__exit__(None, None, None)
        except (BrokenPipeError, FileNotFoundError) as e:
            pass

    def __len__(self):
        return self.total or 0

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._iter)
    
    def _get_iter(self, iter, **kw):
        self.update(0, total=self.total, **kw)
        for i, x in enumerate(iter):
            yield x
            self.update()

    def __call__(self, iter=None, total=None, **kw):
        if isinstance(iter, str):  # infer string as description
            iter, kw['description'] = None, iter
        if iter is None:
            return self.update(total=total, **kw)

        self.total = utils.try_len(iter) if total is None else total
        def _with_iter():
            if self._entered:
                yield from self._get_iter(iter, **kw)
                return
            with self:
                yield from self._get_iter(iter, **kw)
        self._iter = _with_iter()
        return self

    def print(self, *a, **kw):
        self.console.print(*a, **kw)
        return self

    def set_description(self, desc):
        return self.update(None, description=desc or "")

    def update(self, n=1, **kw):
        if n or kw:
            self._call('update', advance=n, **kw)
        return self


class QueueFile:
    isatty=rich.get_console().file.isatty
    def __init__(self, q, task_id):
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




# ---------------------------------------------------------------------------- #
#                                   Examples                                   #
# ---------------------------------------------------------------------------- #


def example_fn(i, pbar):
    import time
    import random
    for i in pbar(range(i + 1)):
        t = random.random()*2 / (i+1)
        time.sleep(t)
        pbar.print(i, "slept for", t)
        pbar.set_description("sleeping for %.2f" % t)


def my_work(n, pbar, sleep=0.2):
    import time
    for i in pbar(range(n), description=f'counting to {n}'):
        time.sleep(sleep)


def my_other_work(n, pbar, sleep=0.2):
    import time
    time.sleep(1)
    with pbar(description=f'counting to {n}', total=n):
        for i in range(n):
            pbar.update(0.5, description=f'Im counting - {n}  ')
            time.sleep(sleep/2)
            pbar.update(0.5, description=f'Im counting - {n+0.5}')
            time.sleep(sleep/2)


def example(n=10, transient=False, n_workers=5, **kw):
    import time
    t0 = time.time()
    mqdm.pool(
        example_fn, 
        range(n), 
        mainbar_kw={'transient': transient},
        subbar_kw={'transient': transient},
        n_workers=n_workers,
        **kw)
    mqdm.print("done in", time.time() - t0, "seconds")
