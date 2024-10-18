''''''
import sys
import time
# import rich
# from rich import progress
from . import get_pbar
from . import utils
import mqdm



class Bar:
    pbar = None
    _iter = None
    _entered = False
    _started = False
    total = None
    _get_desc = None
    _completed = 0

    def __init__(self, desc=None, *, bytes=False, transient=False, disable=False, task_id=None, parent_task_id=None, _update_manager=None, **kw):
        self.transient = transient
        self.disabled = disable
        self.pbar = get_pbar(bytes=bytes)
        self.total = kw.pop('total', None)
        self._update_manager = _update_manager
        kw = self._process_args(description=desc or '', start=False, **kw)
        kw.setdefault('description', '')
        self.task_id = task_id if task_id is not None else self.pbar.add_task(parent_task_id=parent_task_id, **kw) if not self.disabled else None

    def remove(self):
        if self.disabled: return
        self.pbar.remove_task(self.task_id)

    def __getitem__(self, key):
        return getattr(self.pbar.tasks[self.task_id], key)
    
    def __getstate__(self):
        state = self.__dict__.copy()
        # state['pbar'] = None
        # state['_pq'] = None
        state['_get_desc'] = None
        state['_iter'] = None
        return state
    
    def __setstate__(self, state):
        self.__dict__.update(state)
        # self.pbar = get_pbar()

    def __enter__(self):
        if not self._entered:
            self._entered = True
            self._completed = 0
            if not self.disabled:
                # self.pbar.start()
                self.pbar.start_task(self.task_id)
                mqdm._add_instance(self)
        return self

    def __exit__(self, c,v,t):
        if self._entered:
            self._entered = False
            if not self.disabled:
                self.pbar.refresh()
                self.pbar.stop_task(self.task_id)
                if self.transient:
                    self.pbar.remove_task(self.task_id)
                mqdm._remove_instance(self)

    def __del__(self):
        try:
            if sys.meta_path is None:
                return 
            self.__exit__(None, None, None)
            # if not mqdm._instances:
            #     if not self.disabled:
            #         self.pbar.stop()
            #     mqdm.pbar = None
        except ImportError as e:
            pass

    def _get_iter(self, iter, **kw):
        for i, x in enumerate(iter):
            self.update(i>0, arg_=x)
            yield x
        self.update()

    def __call__(self, iter, desc=None, total=None, **kw):
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

    def __len__(self):
        return self.total or 0

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._iter)

    @property
    def n(self):
        if self.disabled: return self._completed  # FIXME
        return self.pbar.tasks[self.task_id].completed

    def print(self, *a, **kw):
        mqdm.print(*a, **kw)
        return self

    def set_description(self, desc):
        return self.update(0, description=desc)
    
    def _process_args(self, *, arg_=..., **kw):
        kw = {k: v for k, v in kw.items() if v is not ...}
        if 'transient' in kw:
            self.transient = kw.pop('transient')
        if 'total' in kw:
            self.total = kw['total']

        # get description
        if 'desc' in kw:
            kw['description'] = kw.pop('desc')
        if 'description' in kw and callable(kw['description']):
            self._get_desc = kw.pop('description')
            kw['description'] = ''
        if kw.get('description') is None and self._get_desc is not None and arg_ is not ...:
            kw['description'] = self._get_desc(arg_)
        if 'description' in kw and kw.get('description') is None:
            kw['description'] = ''

        return kw

    def update(self, n=1, *, arg_=..., **kw):
        self._completed = kw['completed'] if 'completed' in kw else (self._completed + n)
        if self.disabled: return self

        # handle indeterminate progress
        if not self._started and self.total is not None:
            self._started = True
            self.pbar.start_task(self.task_id)

        # let a Bars object do the updates
        if self._update_manager:
            return self._update_manager(self.task_id, 'update', (), self._process_args(arg_=arg_, advance=n, **kw))

        # update progress bar
        kw = self._process_args(arg_=arg_, **kw)
        if n or kw:
            self.pbar.update(self.task_id, advance=int(n), **kw)
        return self

    @classmethod
    def mqdm(cls, iter=None, desc=None, bytes=False, transient=False, disable=False, **kw):
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
        if 'leave' in kw:
            transient = not kw.pop('leave')
        return cls(desc=desc, bytes=bytes, transient=transient, disable=disable)(iter, **kw)


# ---------------------------------------------------------------------------- #
#                                   Examples                                   #
# ---------------------------------------------------------------------------- #

@mqdm.iex
def example(n=10, transient=False):
    t0 = time.time()
    for i in mqdm.mqdm(range(n), desc='example', transient=transient):
        mqdm.set_description(f'example {i}')
        for j in mqdm.mqdm(range(10), desc=f'blah {i}', transient=transient):
            time.sleep(0.04)
            # 1/0
            # mqdm.embed()
            # time.sleep(1)
        # time.sleep(0.05)
    mqdm.print(f"done in {time.time() - t0:.2f} seconds")

# def example(n=10, transient=False):
#     import tqdm
#     t0 = time.time()
#     for i in tqdm.tqdm(range(n), desc='example', leave=not transient):
#         for j in tqdm.tqdm(range(10), desc=f'blah {i}', leave=not transient):
#             time.sleep(0.04)
#     tqdm.tqdm.write(f"done in {time.time() - t0:.2f} seconds")
