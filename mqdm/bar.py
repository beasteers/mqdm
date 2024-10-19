''''''
import sys
import time
from . import get_pbar
from . import utils
import mqdm



class Bar:
    """A progress bar for an iterable. Meant to approximate tqdm's interface."""
    task_id = None           # the task ID of the progress bar
    parent_task_id = None    # the task ID of the parent progress bar
    pbar = None              # the progress bar instance
    total = None             # the total number of items to iterate over
    _completed = 0           # the number of items completed
    _iter = None             # the item iterator
    _entered = False         # whether the progress bar has called __enter__()
    _started = False         # whether the progress bar has beed started (for lazy start)
    _get_desc = None         # a function to get the description

    def __init__(self, desc=None, *, bytes=False, disable=False, task_id=None, parent_task_id=None, pool_mode=None, **kw):
        self.disabled = disable
        self.pool_mode = pool_mode
        self.pbar = get_pbar(bytes=bytes, pool_mode=pool_mode)
        self.total = kw.pop('total', None)
        kw.setdefault('start', False)
        kw = self._process_args(description=desc or '', **kw)
        kw.setdefault('description', '')
        self.parent_task_id = parent_task_id if parent_task_id is not None else getattr(mqdm.proxy._thread_local_data, 'parent_task_id', None)
        self.task_id = task_id if task_id is not None else self.pbar.add_task(parent_task_id=self.parent_task_id, **kw) if not self.disabled else None

    def remove_task(self):
        """Remove the progress bar."""
        if self.disabled: return
        self.pbar.remove_task(self.task_id)

    def __getitem__(self, key):
        return getattr(self.pbar.tasks[self.task_id], key)
    
    def __getstate__(self):
        state = self.__dict__.copy()
        state['_unpickled'] = True
        state['_get_desc'] = None  # cannot pickle lambda functions
        state['_iter'] = None  # cannot pickle iterators
        return state

    def __enter__(self):
        if not self._entered:
            self._entered = True
            self._completed = 0
            if not self.disabled:
                # self.pbar.start()
                self.pbar.start_task(self.task_id)
                self._started = True
                mqdm._add_instance(self)
        return self

    def __exit__(self, c,v,t):
        if self._entered:
            self._entered = False
            if not self.disabled:
                self.pbar.refresh()
                self.pbar.stop_task(self.task_id)
                self._started = False
                mqdm._remove_instance(self)

    def __del__(self):
        try:
            if sys.meta_path is None:
                return 
            self.__exit__(None, None, None)
            if not mqdm._instances and self.parent_task_id is None and utils.is_main_process():
                if not self.disabled:
                    self.pbar.stop()
                mqdm.pbar = None
        except ImportError as e:
            pass

    def _get_iter(self, iter, **kw):
        for i, x in enumerate(iter):
            self.update(i>0, arg_=x, i_=i)
            yield x
        self.update()

    def __call__(self, iter, desc=None, total=None, **kw) -> 'Bar':
        """Iterate over an iterable with a progress bar."""
        if isinstance(iter, str) and desc is None:  # infer string as description
            iter, kw['description'] = None, iter
        if iter is None:
            return self.update(total=total, **kw)
        if isinstance(iter, int):
            iter = range(iter)

        total = utils.try_len(iter, self.total) if total is None else total
        self.update(0, total=total, description=... if desc is None else desc, **kw)
        def _with_iter():
            if self._entered:  # already called __enter__, don't call __exit__() when leaving
                yield from self._get_iter(iter, **kw)
                return
            with self:  # call __enter__() and __exit__()
                yield from self._get_iter(iter, **kw)
        self._iter = _with_iter()
        return self

    def __len__(self):
        return self.total or 0

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._iter)

    @property
    def n(self) -> int:
        """The number of items completed."""
        if self.disabled: return self._completed
        return self.pbar.tasks[self.task_id].completed

    def print(self, *a, **kw):
        """Print above the progress bar."""
        mqdm.print(*a, **kw)
        return self

    def set_description(self, desc):
        """Set the description of the progress bar."""
        return self.update(0, description=desc)
    
    def _process_args(self, *, arg_=..., i_: int=None, **kw) -> dict:
        kw = {k: v for k, v in kw.items() if v is not ...}
        if 'leave' in kw:  # tqdm compatibility
            kw['transient'] = not kw.pop('leave')
        if 'total' in kw:  # keep local copy of total
            self.total = kw['total']

        # get description
        if 'desc' in kw:  # tqdm compatibility
            kw['description'] = kw.pop('desc')
        if 'description' in kw and callable(kw['description']):  # handle dynamic descriptions
            self._get_desc = kw.pop('description')
            kw['description'] = None
        if kw.get('description') is None and self._get_desc is not None and arg_ is not ...:
            kw['description'] = self._get_desc(arg_, i_)
        if 'description' in kw and kw.get('description') is None:
            kw['description'] = ''

        return kw

    def update(self, n: int=1, **kw) -> 'Bar':
        """Update the progress bar."""
        self._completed = kw['completed'] if 'completed' in kw else (self._completed + int(n))
        if self.disabled: return self

        # handle indeterminate progress
        if not self._started and self.total is not None:
            self.pbar.start_task(self.task_id)
            self._started = True

        # update progress bar
        kw = self._process_args(**kw)
        if n or kw:
            self.pbar.update(self.task_id, advance=int(n), **kw)
        return self

    @classmethod
    def mqdm(cls, iter=None, desc=None, bytes=False, transient=False, disable=False, **kw) -> 'Bar':
        """Create a progress bar for an iterable.
        
        Args:
            iter (Iterable): The iterable to iterate over.
            desc (str): The description of the progress bar.
            bytes (bool): Whether to show bytes transferred.
            pbar (rich.progress.Progress): An existing progress bar to use.
            transient (bool): Whether to remove the progress bar after completion.
            disable (bool): Whether to disable the progress bar.
            **kw: Additional keyword arguments to pass to the progress bar.
        """
        return cls(desc=desc, bytes=bytes, transient=transient, disable=disable)(iter, **kw)


# ---------------------------------------------------------------------------- #
#                                   Examples                                   #
# ---------------------------------------------------------------------------- #


def example(n=10, transient=False, error=False, embed=False, bp=False):
    t0 = time.time()
    for i in mqdm.mqdm(range(n), desc='example', transient=transient):
        mqdm.set_description(f'example {i}')
        for j in mqdm.mqdm(range(10), desc=f'blah {i}', transient=transient):
            time.sleep(0.04)
            if j == 5 and not i % 2:
                print("blah", i, j)
                if error: 1/0
                if embed: mqdm.embed()
                if bp: mqdm.bp()
    mqdm.print(f"done in {time.time() - t0:.2f} seconds")

# def example(n=10, transient=False):
#     import tqdm
#     t0 = time.time()
#     for i in tqdm.tqdm(range(n), desc='example', leave=not transient):
#         for j in tqdm.tqdm(range(10), desc=f'blah {i}', leave=not transient):
#             time.sleep(0.04)
#     tqdm.tqdm.write(f"done in {time.time() - t0:.2f} seconds")
