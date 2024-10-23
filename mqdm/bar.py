''''''
import time
import sys
from functools import wraps
from typing import Callable, Iterable
from concurrent.futures import as_completed

from . import print, T_POOL_MODE
from . import utils
from .executor import _get_local
import mqdm as M



class mqdm:
    """Create a progress bar for an iterable. (tqdm-like interface)
        
        Args:
            iter (Iterable): The iterable to iterate over.
            desc (str): The description of the progress bar.
            bytes (bool): Whether to show bytes transferred.
            pbar (rich.progress.Progress): An existing progress bar to use.
            transient (bool): Whether to remove the progress bar after completion.
            disable (bool): Whether to disable the progress bar.
            **kw: Additional keyword arguments to pass to the progress bar.
        """
    task_id = None           # the task ID of the progress bar
    pbar = None              # the progress bar instance
    _desc = None             # the description of the progress bar
    _total = None            # the total number of items to iterate over
    _n = 0                   # the number of items completed
    _iter = None             # the item iterator
    # _items = None            # the items of the iterator (for indexing)
    _entered = False         # whether the progress bar has called __enter__()
    _started = False         # whether the progress bar has beed started (for lazy start)
    _task_dict = None        # the dumped task
    get_desc = None          # a function to get the description

    def __init__(self, iter=None, desc=None, *, disable=False, task_id=None, pool_mode=None, progress_kw=None, init_kw=None, **kw):
        self._speed_increment = _speed_increment()
        if isinstance(iter, str) and desc is None:  # infer string as description
            iter, desc = None, iter

        self.disable = disable

        # initialize progress bar task
        init_kw = {**_get_local('defaults', {}), **kw, **(init_kw or {})}
        init_kw = self._process_args(description=desc, **init_kw)
        if not self.disable:
            pbar = M._get_pbar(pool_mode=pool_mode, **(progress_kw or {}))
            M._add_instance(self)
            if task_id is None:
                init_kw.setdefault('start', True) # self._total is not None
                init_kw.setdefault('total', self._total)
                init_kw.setdefault('description', '')
                task_id = M.pbar.add_task(**init_kw)
            else:
                kw = {**init_kw, **kw}
                try:
                    task_dict = M.pbar.dump_task(task_id) or {}
                except KeyError:
                    task_dict = {}
                self._n = task_dict.get('completed', 0)
                self._total = task_dict.get('total')
                self._desc = task_dict.get('description')

        self.task_id = task_id
        self._speed_increment.task_id = task_id
        self._started = True

        # if we have an iterable, start the progress bar
        self(iter, desc=..., **kw)

    # ------------------------------ Dunder methods ------------------------------ #

    def __repr__(self) -> str:
        return f'<mqdm[{self.task_id}]({self._n}/{self._total}, {self._desc or ""!r})>'

    def __getstate__(self):
        state = self.__dict__.copy()
        state['get_desc'] = None  # cannot pickle lambda functions
        # state['_items'] = None  # cannot pickle iterators
        state['_iter'] = None  # cannot pickle iterators
        return state

    # def __getitem__(self, i: int):
    #     """Get an item at index."""
    #     return self._items[i]
    
    # def __bool__(self) -> bool:
    #     return self._total is None or self._total

    def __len__(self) -> int:
        """Get the total number of items."""
        return self._total or 0

    def __iter__(self) -> 'mqdm':
        return self

    def __next__(self):
        return next(self._iter)
    
    # ----------------------------- Lifecycle methods ---------------------------- #
    
    def __enter__(self) -> 'mqdm':
        self._entered = True
        return self.open()

    def __exit__(self, c,v,t):
        self._entered = False
        self.close()
        pbar = M.pbar
        if isinstance(v, KeyboardInterrupt) and pbar is not None:
            pbar.stop()

    def __del__(self):
        try:
            if sys.meta_path is None:
                return 
            self.close()
        except (ImportError, BrokenPipeError, FileNotFoundError) as e:
            pass

    # ----------------------------- Iteration methods ---------------------------- #

    # def _speed_inc(self, n: int=1, arg_=..., i_: int=None, flush=False):
    #     try:
    #         self._speed_increment(n, arg_=arg_, i_=i_, flush=flush)
    #     except KeyError as e:
    #         pass

    def _get_iter(self, iter, **kw):
        i = x = ...
        try:
            for i, x in enumerate(iter):
                M._ttl_pause_wait()
                self._speed_increment(i>0, arg_=x, i_=i)
                yield x
            self._speed_increment(1, flush=True)
        finally:
            self._speed_increment(0, arg_=x, i_=i, flush=True)

    def __call__(self, iter, desc=None, total=None, **kw) -> 'mqdm':
        """Iterate over an iterable with a progress bar."""
        if isinstance(iter, str) and desc is None:  # infer string as description
            iter, desc = None, iter
        if iter is None:  # no iterable yet
            return self.update(0, total=total, **kw)
        if isinstance(iter, int):  # implicit range
            iter = range(iter)

        total = utils.try_len(iter, self._total) if total is None else total
        self.update(0, total=total, description=desc, **kw)
        def _with_iter():
            if self._entered:  # already called __enter__, don't call __exit__() when leaving
                yield from self._get_iter(iter, **kw)
                return
            with self:  # call __enter__() and __exit__()
                yield from self._get_iter(iter, **kw)
        # self._items = iter
        self._iter = _with_iter()
        return self
    
    # ------------------------------ Internal methods ----------------------------- #

    def _attach(self):
        """Attach the task to the progress bar."""
        if self.disable: return

        pbar = M._get_pbar(start=False)
        M._add_instance(self)
        if self._task_dict is not None:
            pbar.load_task(self._task_dict)
            pbar.start_task(self.task_id)
            self._task_dict = None
        self.set(total=self._total)

    def _detach(self, remove=None, soft=False):
        """Detach the task from the progress bar."""
        pbar = M.pbar
        if self.disable or pbar is None: return

        # stop and remove task
        if self._task_dict is None:
            self._task_dict = pbar.pop_task(self.task_id, remove=remove)
        M._remove_instance(self)
        M._clear_pbar(strict=False, soft=soft)

    def _process_args(self, *, append_total=None, arg_=..., i_: int=None, **kw) -> dict:
        """Process keyword arguments for updates."""
        kw = {k: v for k, v in kw.items() if v is not ...}
        if 'leave' in kw:  # tqdm compatibility
            kw['transient'] = not kw.pop('leave')

        # get progress and total
        if 'total' in kw:  # keep local copy of total
            self._total = kw['total']
        if append_total:
            kw['total'] = self._total = (self._total or 0) + append_total
        if kw.get('advance'):
            kw['advance'] = int(kw['advance'])
            self._n += kw['advance']
        if kw.get('advance') == 0:
            kw.pop('advance')
        if kw.get('completed') is not None:
            self._n = kw['completed'] = int(kw['completed'])

        # get description
        if 'desc' in kw:  # tqdm compatibility
            kw['description'] = kw.pop('desc')
        if 'description' in kw and callable(kw['description']):  # handle dynamic descriptions
            self.get_desc = kw.pop('description')
            self._speed_increment.get_desc = self.get_desc
        if kw.get('description') is None and self.get_desc is not None and arg_ is not ...:
            kw['description'] = self.get_desc(arg_, i_)
        if kw.get('description') is not None:
            self._desc = kw['description']
        if 'description' in kw and kw['description'] is None:  # ignore None descriptions
            kw.pop('description')

        return kw

    # --------------------------- tqdm-like attributes --------------------------- #

    @property
    def n(self) -> int:
        """The number of items completed."""
        return self._n
    
    @n.setter
    def n(self, n: int):
        """Set the number of items completed."""
        self.set(completed=n)

    @property
    def total(self) -> int:
        """The total number of items to iterate over."""
        return self._total
    
    @total.setter
    def total(self, total: int):
        """Set the total number of items to iterate over."""
        self.set(total=total)

    # ------------------------------ public methods ------------------------------ #

    def open(self):
        """Add the task to the progress bar."""
        self._attach()
        return self

    def close(self, remove=None):
        """Remove the task from the progress bar."""
        self._detach(remove=remove)
        return self

    def print(self, *a, **kw) -> 'mqdm':
        """Print above the progress bar."""
        M.print(*a, **kw)
        return self

    def set_description(self, desc) -> 'mqdm':
        """Set the description of the progress bar."""
        return self.update(0, description=desc)

    def update(self, advance: int=1, **kw) -> 'mqdm':
        """Increment the progress bar."""
        return self.set(advance=advance, **kw)

    def set(self, **kw) -> 'mqdm':
        """Update progress bar fields."""
        kw = self._process_args(**kw)
        if self.disable: return self

        # update progress bar
        if kw:
            M.pbar.update(self.task_id, **kw)
        return self


class _speed_increment:
    """Increment the progress bar in a very fast loop.
    Saves time by reducing inter-process IO.
    """
    __slots__ = ('n', 't', 'delta', 'n0', 'flush', 'get_desc', 'task_id')
    def __init__(self, delta=0.005):
        self.delta = delta
        self.n = self.t = 0
        self.get_desc = None
        self.task_id = None

    def __call__(self, n: int=1, arg_=..., i_=..., flush=False):
        delta = self.delta
        if delta:
            # If the time since the last increment is less than some delta, increment a local counter
            # The only time this fails is if the iterations are highly irregular 
            # (e.g. a bunch of 1000fps followed by a 100 second iteration
            #       - could happen with overwrite=False type scenarios)
            t = time.time()
            last_t = self.t
            n0 = self.n
            if t - last_t < delta and not flush:
                self.n = n + n0
                return
            n += n0

        pbar = M.pbar
        if pbar is None:
            return

        if i_ is not ...:
            get_desc = self.get_desc
            if get_desc is not None:
                desc = get_desc(arg_, i_)
                if desc is not None:
                    pbar.update(self.task_id, advance=n, description=desc)
                    return
        if n:
            pbar.update(self.task_id, advance=n)

        if delta:
            if n0:
                self.n = 0
            self.t = t


def ipool(
        fn: Callable, 
        iter: Iterable, 
        desc: str='', 
        bar_kw: dict={}, 
        n_workers: int=8, 
        pool_mode: T_POOL_MODE='process', 
        ordered_: bool=False, 
        squeeze_: bool=True,
        **kw) -> Iterable:
    """Execute a function in a process pool with a progress bar for each task.

    Args:
        fn (Callable): The function to execute.
        iter (Iterable): The iterable to iterate over.
        desc (str, optional): The description of the main progress bar. 
        bar_kw (dict, optional): Additional keyword arguments for the sub progress bars.
        n_workers (int, optional): The number of workers in the pool. Defaults to 8.
        pool_mode (str, optional): The mode of the pool. Can be 'process', 'thread', 'sequential'. Defaults to 'process'.
        ordered_ (bool, optional): Whether to yield the results in order. Defaults to False for ipool, True for pool.
        squeeze_ (bool, optional): Whether to skip the pool and main progress bar if there is only one item in the iterable. Defaults to True.
    """
    # no workers, just run sequentially
    if n_workers in {0, 1} and squeeze_:
        pool_mode = 'sequential'
    if pool_mode == 'sequential':
        ordered_ = True

    # if the iterable is a single item, just run the function
    if squeeze_ and utils.try_len(iter, -1) == 1:
        arg = utils.args.from_item(iter[0], **kw)
        yield arg(fn)
        return

    bar_kw = {'transient': True, **(bar_kw or {})}
    try:
        # initialize progress bars and run the tasks in a process/thread pool
        with mqdm(desc=desc, **bar_kw) as pbars:
            with M.executor(pool_mode, bar_kw=bar_kw, max_workers=n_workers) as executor:
                try:
                    futures = []
                    for arg in iter:
                        arg = utils.args.from_item(arg, **kw)
                        futures.append(executor.submit(fn, *arg.a, **arg.kw))
                        pbars.set(append_total=1)

                    # get function results
                    for f in futures if ordered_ else as_completed(futures):
                        x = f.result()
                        pbars.update()
                        yield x
                except KeyboardInterrupt:
                    M.pause()
                    executor.shutdown(cancel_futures=True)
                    raise
    except:
        # pause the progress bar so it doesn't interfere with the traceback
        M.pause()
        raise


@wraps(ipool, ['__doc__'])
def pool(
        fn: Callable, 
        iter: Iterable, 
        desc: str='', 
        bar_kw: dict={}, 
        n_workers: int=8, 
        pool_mode: T_POOL_MODE='process', 
        results_: list=None,
        ordered_: bool=True, 
        squeeze_: bool=True,
        **kw) -> Iterable:
    results_ = [] if results_ is None else results_
    results_.extend(ipool(fn, iter, desc=desc, bar_kw=bar_kw, n_workers=n_workers, pool_mode=pool_mode, ordered_=ordered_, squeeze_=squeeze_, **kw))
    return results_
