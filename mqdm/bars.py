''''''
from functools import wraps
from concurrent.futures import as_completed, Executor
from typing import Callable, Iterable, Literal
from . import utils
from .bar import Bar
import mqdm

T_POOL_MODE = Literal['process', 'thread', 'sequential', None]

class Bars(Bar):
    """A progress bar that contains multiple sub progress bars.

    The main progress bar is used to track the completion of the sub progress bars.

    TODO: The main progress bar's estimated time should incorporate the estimated times of the sub progress bars.
    """
    _get_sub_desc = None
    def __init__(self, desc: str|Callable=None, *, pool_mode: T_POOL_MODE='process', transient=True, **kw):
        super().__init__(desc, transient=transient, pool_mode=pool_mode, **kw)
        # default child progress bar keyword arguments
        self._subbar_kw = {
            'transient': transient, 
            'disabled': self.disabled, 
            'visible': False, 
            'start': False,
        }

    def _get_iter(self, iter, **kw):
        for i, x in enumerate(iter):
            # for each item, create a child progress bar
            pbar = self.add(desc=utils.maybe_call(self._get_sub_desc, x, i) or '', **kw)
            yield x, pbar

    def __call__(self, iter, desc=None, DESC=None, **kw):
        """Iterate over an iterable with a progress bar."""
        if desc is None:
            self._get_sub_desc = lambda x, i: f'task {i}'
        elif isinstance(desc, str):
            self._get_sub_desc = lambda x, i: desc.format(x=x, i=i)
        else:
            self._get_sub_desc = desc
        return super().__call__(iter, DESC, **kw)

    def add(self, desc="", **kw):
        """Add a sub progress bar to the main progress bar."""
        return Bar(desc, parent_task_id=self.task_id, **{**self._subbar_kw, **kw, 'pool_mode': self.pool_mode})

    @classmethod
    def mqdms(cls, iter=None, desc=None, DESC=None, bytes=False, transient=False, subbar_kw={}, **kw):
        """Create a progress bar group for each item in an iterable.
        
        Args:
            iter (Iterable): The iterable to create subtasks for.
            desc (str, Callable, optional): The description of the sub progress bars. Can be a function that takes the item and index as arguments. Defaults to (lambda x, i: f'task {i}').
            main_desc (str, optional): The description of the main progress bar. 
            bytes (bool, optional): Whether to display the bytes processed. Defaults to False.
            transient (bool, optional): Whether to remove the progress bar after completion. Defaults to False.
            subbar_kw (dict, optional): Additional keyword arguments for the sub progress bars.
            **kw: Additional keyword arguments for the main progress bar.
        """
        return cls(desc=DESC, bytes=bytes, transient=transient, **kw)(iter, desc, **(subbar_kw or {}))

    @classmethod
    def ipool(
            cls, 
            fn: Callable, 
            iter: Iterable, 
            *a, 
            desc: str|Callable=..., 
            DESC: str="", 
            mainbar_kw: dict={}, 
            subbar_kw: dict={}, 
            n_workers: int=8, 
            pool_mode: T_POOL_MODE='process', 
            ordered_: bool=False, 
            squeeze_: bool=False,
            results_: list|None=None,
            **kw) -> Iterable:
        """Execute a function in a process pool with a progress bar for each task.
        
        Args:
            fn (Callable): The function to execute.
            iter (Iterable): The iterable to iterate over.
            desc (str, Callable, optional): The description of the sub progress bars. Can be a function that takes the item and index as arguments. Defaults to (lambda x, i: f'task {i}').
            DESC (str, optional): The description of the main progress bar. 
            mainbar_kw (dict, optional): Additional keyword arguments for the main progress bar.
            subbar_kw (dict, optional): Additional keyword arguments for the sub progress bars.
            n_workers (int, optional): The number of workers in the pool. Defaults to 8.
            pool_mode (str, optional): The mode of the pool. Can be 'process', 'thread', 'sequential'. Defaults to 'process'.
            ordered_ (bool, optional): Whether to yield the results in order. Defaults to False.
            squeeze_ (bool, optional): Whether to skip the pool and main progress bar if there is only one item in the iterable. Defaults to False.
            results_ (list, optional): The list to append the results to. Useful to collect partial results in case of exception.
        """
        # no workers, just run sequentially
        if n_workers in {0, 1}:
            pool_mode = None

        # if the iterable is a single item, just run the function
        if squeeze_ and utils.try_len(iter, -1) == 1:
            arg = utils.args.from_item(iter[0], *a, **kw)
            yield arg(fn, pbar=mqdm.mqdm)
            if results_ is not None:
                results_.append(x)
            return

        # initialize progress bars
        pbars = cls.mqdms(
            iter, 
            pool_mode=pool_mode, 
            desc=(lambda x, i: f'task {i}') if desc is ... else (desc or ""), 
            DESC=DESC,
            subbar_kw=subbar_kw, 
            **(mainbar_kw or {})
        )

        try:
            with pbars:
                # no multiple workers, just run the function sequentially
                if pool_mode in {'sequential', None}:
                    for arg, pbar in pbars:
                        arg = utils.args.from_item(arg, *a, **kw)
                        x = arg(fn, mqdm=pbar)
                        if results_ is not None:
                            results_.append(x)
                        yield x
                    return

                # run the function in a process/thread pool
                with pbars.executor(max_workers=n_workers) as executor:
                    futures = []
                    for arg, pbar in pbars:
                        arg = utils.args.from_item(arg, *a, **kw)
                        futures.append(executor.submit(fn, *arg.a, mqdm=pbar, **arg.kw))

                    # get function results
                    for f in futures if ordered_ else as_completed(futures):
                        x = f.result()
                        if results_ is not None:
                            results_.append(x)
                        yield x
        except Exception as e:
            # pause the progress bar so it doesn't interfere with the traceback
            pbars.remove_task()
            mqdm.pause()
            raise

    @classmethod
    @wraps(ipool, ['__annotations__', '__doc__', '__type_params__'])
    def pool(cls, *a, **kw):
        return list(cls.ipool(*a, **kw))

    def executor(self, **kw) -> Executor:
        """Return the appropriate executor for the pool mode of the progress bar."""
        return utils.POOL_EXECUTORS[self.pool_mode](initializer=mqdm.proxy._pbar_initializer, initargs=[mqdm.pbar, self.task_id], **kw)

# ---------------------------------------------------------------------------- #
#                                   Examples                                   #
# ---------------------------------------------------------------------------- #


def example_fn(i, mqdm, error=False, sleep=1):
    import time
    import random
    for i in mqdm(range(i + 1)):
        t = sleep * random.random()*2 / (i+1)
        time.sleep(t)
        mqdm.print(i, "slept for", t)
        mqdm.set_description("sleeping for %.2f" % t)
        if error: 1/0


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
        # my_work, 
        # my_other_work,
        range(n), 
        DESC='[bold blue]Very important work',
        mainbar_kw={'transient': transient},
        subbar_kw={'transient': transient},
        n_workers=n_workers,
        **kw)
    mqdm.print("done in", time.time() - t0, "seconds", 123)
