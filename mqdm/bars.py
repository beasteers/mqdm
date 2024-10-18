''''''
import sys
from functools import wraps
from concurrent.futures import as_completed
from typing import Callable
import rich

from .proxy import RemoteProgressFunction
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

    def __init__(self, desc=None, *, pool_mode='process', transient=True, **kw):
        self._tasks = {}
        # self._pq = utils.POOL_QUEUES[pool_mode](self._on_message)
        # self._remote = Remote(self._pq)
        self.pool_mode = pool_mode

        super().__init__(desc, transient=transient, **kw)

    # def __enter__(self):
    #     if not self._entered:
    #         self._pq.__enter__()
    #         super().__enter__()
    #     return self

    # def __exit__(self, c,v,t):
    #     if self._entered:
    #         self._pq.__exit__(c,v,t)
    #         super().__exit__(c,v,t)
    #         # self._pq.raise_exception()

    def _get_iter(self, iter, **kw):
        for i, x in enumerate(iter):
            pbar = self.add(desc=utils.maybe_call(self._get_desc, x, i), **kw)
            yield x, pbar

    def __len__(self):
        return max(len(self._tasks), self.total or 0)
    
    def remote(self):
        return self._remote

    def add(self, desc="", visible=False, start=False, **kw):
        # if self.pool_mode != 'process':
        task_id = self._add_task(desc, visible=visible, start=start, **kw)
        return Bar(task_id=task_id, parent_task_id=self.task_id, **kw)
        # return RemoteBar(self._remote, self._add_task(desc, visible=visible, start=start, **kw))

    def _add_task(self, desc="", proxy=None, **kw):
        task_id = self.pbar.add_task(description=desc or "", parent_task_id=self.task_id, **kw)
        # print("added task", task_id)
        if task_id not in self._tasks:
            self._tasks[task_id] = {}
        if proxy is not None:
            self._task_id_proxy[proxy] = task_id
        return task_id

    def remove(self):
        if self.disabled: return
        for task_id in self._tasks:
            self.pbar.remove_task(task_id)
        self.pbar.remove_task(self.task_id)

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
            # task = self.pbar._tasks[task_id]
            # current = task.completed
            # total = task.total
            # transient = task.fields.get('transient', True)
            # complete = total is not None and current >= total
            # task.visible = bool(total is not None and not complete or not transient)
            task = self.pbar.get_task(task_id)
            current = task['completed']
            total = task['total']
            transient = task['fields'].get('transient', True)
            complete = total is not None and current >= total
            visible = bool(total is not None and not complete or not transient)
            self.pbar.set_task_attrs(task_id, {'visible': visible})
            self._tasks[task_id]['complete'] = complete

        # ------------------------------ update overall ------------------------------ #
        n_finished = sum(bool(d.get('complete', False)) for d in self._tasks.values())
        self.pbar.update(self.task_id, completed=n_finished, total=len(self))

    @classmethod
    def mqdms(cls, iter=None, desc=None, main_desc=None, bytes=False, transient=False, subbar_kw={}, **kw):
        return cls(desc=main_desc, bytes=bytes, transient=transient, **kw)(iter, desc, **(subbar_kw or {}))

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
            pool_mode='process', 
            ordered_=False, 
            squeeze_=False,
            results_=None,
            **kw):
        """Execute a function in a process pool with a progress bar for each task."""
        if n_workers < 1:
            pool_mode = 'sequential'
        try:
            if squeeze_ and len(iter) == 1:
                arg = utils.args.from_item(iter[0], *a, **kw)
                yield arg(fn, pbar=mqdm.mqdm)
                return
        except TypeError:
            pass

        # initialize progress bars
        # if pool_mode == 'process':
        mqdm.as_remote()
        pbars = cls.mqdms(
            iter, 
            pool_mode=pool_mode, 
            desc=desc or (lambda x, i: f'task {i}'), 
            main_desc=main_desc,
            subbar_kw=subbar_kw, 
            **(mainbar_kw or {})
        )

        try:
            # no workers, just run the function
            if n_workers < 2 or pool_mode == 'sequential':
                with pbars:
                    for arg, pbar in pbars:
                        arg = utils.args.from_item(arg, *a, **kw)
                        x = arg(fn, mqdm=pbar)
                        if results_ is not None:
                            results_.append(x)
                        yield x
                return

            # run the function in a process pool
            with pbars, pbars.executor(max_workers=n_workers, initializer=mqdm._pbar_initializer, initargs=[mqdm.pbar]) as executor:
                futures = []
                for arg, pbar in pbars:
                    arg = utils.args.from_item(arg, *a, **kw)
                    futures.append(executor.submit(fn, *arg.a, mqdm=pbar, **arg.kw))
                    # futures.append(executor.submit(RemoteProgressFunction(pbars.pbar, fn), *arg.a, mqdm=pbar, **arg.kw))

                for f in futures if ordered_ else as_completed(futures):
                    x = f.result()
                    if results_ is not None:
                        results_.append(x)
                    yield x
        except Exception as e:
            pbars.remove()
            raise
    

    @classmethod
    @wraps(ipool)
    def pool(cls, *a, **kw):
        return list(cls.ipool(*a, **kw))

    # not sure which name is better
    imap = ipool
    map = pool

    def executor(self, **kw):
        return utils.POOL_EXECUTORS[self.pool_mode](**kw)

# ---------------------------------------------------------------------------- #
#                                   Examples                                   #
# ---------------------------------------------------------------------------- #


import mqdm as mqdm_
def example_fn(i, mqdm):
    import time
    import random
    for i in mqdm(range(i + 1)):
        t = random.random()*2 / (i+1)
        time.sleep(t)
        # mqdm.print(i, "slept for", t)
        mqdm.set_description("sleeping for %.2f" % t)


def my_work(n, mqdm, sleep=0.2):
    import time
    for i in mqdm(range(n), description=f'counting to {n}'):
        time.sleep(sleep)


def my_other_work(n, mqdm, sleep=0.2):
    import time
    time.sleep(1)
    with mqdm(description=f'counting to {n}', total=n) as pbar:
        for i in range(n):
            mqdm.update(0.5, description=f'Im counting - {n}  ')
            time.sleep(sleep/2)
            mqdm.update(0.5, description=f'Im counting - {n+0.5}')
            time.sleep(sleep/2)
            mqdm.set_description(f'AAAAA - {n+1}')


def example(n=10, transient=False, n_workers=5, **kw):
    import time
    t0 = time.time()
    mqdm.pool(
        example_fn, 
        # my_other_work,
        range(n), 
        mainbar_kw={'transient': transient},
        subbar_kw={'transient': transient},
        n_workers=n_workers,
        **kw)
    mqdm.print("done in", time.time() - t0, "seconds")
