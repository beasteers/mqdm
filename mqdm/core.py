''''''
import sys
import queue
import threading
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from rich import progress, print
from . import utils



def get_pbar(pbar=None, bytes=False):
    return pbar or progress.Progress(
        "[progress.description]{task.description}",
        progress.BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        *([progress.DownloadColumn()] if bytes else [utils.MofNColumn()]),
        progress.TimeRemainingColumn(),
        progress.TimeElapsedColumn(),
        refresh_per_second=8,
    )


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
    

class Bars:
    def __init__(self, desc="", pbar=None, iter=None, total=None, pool_mode='process', **kw) -> None:
        if isinstance(desc, progress.Progress):
            desc, pbar = None, desc
        self.desc = desc
        self.pbar = get_pbar(pbar)
        self._overall_kw = kw
        self.total = utils.try_len(iter, total)
        self._pq = utils.POOL_QUEUES[pool_mode](self._on_message)
        self._tasks = {}

    def __enter__(self):
        self.pbar.__enter__()
        self._pq.__enter__()
        self._tasks = {}
        # ---------------------------------------------------------------------------- #
        #                               add overall task                               #
        # ---------------------------------------------------------------------------- #
        self.overall_task = self.pbar.add_task(self.desc, total=self.total, **self._overall_kw)
        return self
   
    def __exit__(self, c,v,t):
        self._pq.__exit__(c,v,t)
        self.pbar.__exit__(c,v,t)

    def add(self, title, visible=False, **kw):
        # ---------------------------------------------------------------------------- #
        #                                   add task                                   #
        # ---------------------------------------------------------------------------- #
        task_id = self.pbar.add_task(title, visible=visible, start=False, **kw)
        self._tasks[task_id] = {}
        return RemoteBar(self._pq.queue, task_id)
    
    def close(self):
        self.__exit__(None,None,None)

    def _on_message(self, task_id, method, data):
        if method == 'update':
            self._update(task_id, **data)
        else:
            getattr(self.pbar, method)(**data)

    def _update(self, task_id, **data):
        # update the task-specific progress bar
        if task_id is not None:
            self._tasks[task_id].update(**data)
            data.pop('complete', None)
            # ---------------------------------------------------------------------------- #
            #                                  update task                                 #
            # ---------------------------------------------------------------------------- #
            self.pbar.update(task_id, **data)

        # update the overall task progress bar
        n_finished = sum(bool(d and d.get('complete', False)) for d in self._tasks.values())
        # ---------------------------------------------------------------------------- #
        #                                update overall                                #
        # ---------------------------------------------------------------------------- #
        self.pbar.update(self.overall_task, completed=n_finished, total=len(self._tasks))

    @classmethod
    def ipool(cls, fn, xs, *a, n_workers=8, desc=None, mainbar_kw=None, subbar_kw=None, pool_mode='process', **kw):
        """Execute a function in a process pool with a progress bar for each task."""
        # get the arguments for each task
        items = [x if isinstance(x, args) else args(x) for x in xs]
    
        # no workers, just run the function
        if n_workers < 2:
            for i, arg in enumerate(items):
                desc_i = arg(desc or f'task {i}')
                yield arg(fn, *a, pbar=Bar, **kw)
            return

        # run the function in a process pool
        futures = []
        with utils.POOL_EXECUTORS[pool_mode](max_workers=n_workers) as executor, cls(pool_mode=pool_mode, **(mainbar_kw or {})) as pbars:
            for i, arg in enumerate(items):
                desc_i = arg(desc or f'task {i}')
                pbar = pbars.add(desc_i, **(subbar_kw or {}))
                futures.append(executor.submit(fn, *arg.a, *a, pbar=pbar, **dict(kw, **arg.kw)))
            for f in as_completed(futures):
                yield f.result()

    @classmethod
    def pool(cls, fn, xs, *a, n_workers=8, desc=None, **kw):
        return list(cls.imap(fn, xs, *a, n_workers=n_workers, desc=desc, **kw))

    # not sure which name is better
    imap = ipool
    map = pool


class args:
    def __init__(self, *a, **kw):
        self.a = a
        self.kw = kw

    def __call__(self, fn, *a, **kw):
        return fn(*self.a, *a, **dict(self.kw, **kw)) if callable(fn) else fn


class RemoteBar:
    def __init__(self, q, task_id):
        self._queue = q
        self.task_id = task_id
        self.current = 0
        self.total = 0
        self.complete = False
        self._started = False
        self.kw = {}
        self.update(0)
    
    def __enter__(self, **kw):
        # ---------------------------------------------------------------------------- #
        #                                  start task                                  #
        # ---------------------------------------------------------------------------- #
        # start the task if it hasn't been started yet
        if not self._started:
            self._call('start_task', task_id=self.task_id, **kw)
            self._started = True
        return self
            
    def __exit__(self, exc_type, exc_value, tb):
        self.close()

    def close(self):
        self.update(0, complete=True)
        # ---------------------------------------------------------------------------- #
        #                                   stop task                                  #
        # ---------------------------------------------------------------------------- #
        if self._started:
            self._call('stop_task', task_id=self.task_id)
            self._started = False
        return

    def __call__(self, iter=None, total=None, **kw):
        # if the first argument is a string, use it as the description
        if isinstance(iter, str):
            iter, kw['description'] = None, iter
        if iter is None:
            if total is not None:
                self.total = kw['total'] = total
            # if kw or total is not None:
            #     self.update(0, **kw)
            # ---------------------------------------------------------------------------- #
            #                                  start task                                  #
            # ---------------------------------------------------------------------------- #
            self.__enter__(**kw)
            return self
        
        # --------------------------------- iterable --------------------------------- #

        self.total = kw['total'] = utils.try_len(iter, total)
        def _iter():
            # ---------------------------------------------------------------------------- #
            #                                  start task                                  #
            # ---------------------------------------------------------------------------- #
            self.__enter__(**kw)
            try:
                for x in iter:
                    yield x
                    # ---------------------------------------------------------------------------- #
                    #                                    update                                    #
                    # ---------------------------------------------------------------------------- #
                    self.update()
            finally:
                # ---------------------------------------------------------------------------- #
                #                                   stop task                                  #
                # ---------------------------------------------------------------------------- #
                self.__exit__(*sys.exc_info())
        return _iter()
    
    def _call(self, method, **kw):
        self._queue.put((self.task_id, method, kw))

    def set(self, value):
        self.current = value
        self.update(0)
        return self

    def update(self, n=1, **kw):
        if not self._started:
            self.__enter__(**kw)

        if 'total' in kw:
            self.total = kw['total']

        # track all keyword arguments
        self.kw = dict(self.kw, **kw)
        kw = dict(self.kw)

        # calculate task progress
        self.current += n
        total = self.total if self.current or not self.total else (self.current+1)
        self.complete = total and self.current >= total
        visible = bool(total and not self.complete or not kw.get('transient', True))
        kw.setdefault('visible', visible)
        kw.setdefault('total', total)
        kw.setdefault('complete', self.complete)

        # ---------------------------------------------------------------------------- #
        #                                    update                                    #
        # ---------------------------------------------------------------------------- #
        self._call('update', completed=self.current, **kw)
        return self



class Bar:
    def __init__(self, desc=None, bytes=False, pbar=None, total=None, **kw):
        if isinstance(desc, progress.Progress):
            desc, pbar = None, desc
        self.pbar = get_pbar(pbar, bytes=bytes)
        # ---------------------------------------------------------------------------- #
        #                                   add task                                   #
        # ---------------------------------------------------------------------------- #
        self.task_id = self.pbar.add_task(desc, start=total is not None, total=total, **kw)
        self.pbar.__enter__()

    def __enter__(self):
        return self

    def __exit__(self, c,v,t):
        self.pbar.__exit__(c,v,t)

    def __call__(self, iter, total=None, **kw):
        with self.pbar:
            # ---------------------------------------------------------------------------- #
            #                                 update total                                 #
            # ---------------------------------------------------------------------------- #
            # set the initial total
            self.update(0, total=utils.try_len(iter, total), **kw)
            # loop through the elements
            for i, x in enumerate(iter):
                yield x
                # ---------------------------------------------------------------------------- #
                #                                    update                                    #
                # ---------------------------------------------------------------------------- #
                self.update()

    def update(self, n=1, total=None, **kw):
        # start the task if it hasn't been started yet
        if total is not None:
            # ---------------------------------------------------------------------------- #
            #                                  start task                                  #
            # ---------------------------------------------------------------------------- #
            task = self.pbar._tasks[self.task_id]
            if task.start_time is None:
                self.pbar.start_task(self.task_id)
                print('starting task', total, task, self.task_id)

        # ---------------------------------------------------------------------------- #
        #                                    update                                    #
        # ---------------------------------------------------------------------------- #
        self.pbar.update(self.task_id, advance=n, total=total, **kw)
        return self

    def close(self):
        pass



# ---------------------------------------------------------------------------- #
#                                   Examples                                   #
# ---------------------------------------------------------------------------- #


def example_fn(i, pbar):
    import random
    from time import sleep
    for i in pbar(range(i + 1)):
        sleep(random.random()*2)

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


def example_run():
    Bars.pool(
        example_fn, 
        range(10), 
        # desc=lambda i: f"wowow {i} :o", 
        mainbar_kw={'transient': False},
        subbar_kw={'transient': False},
        n_workers=5)

    

if __name__ == '__main__':
    import fire
    fire.Fire(example_run)