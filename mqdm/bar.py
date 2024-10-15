''''''
import time
import rich
from rich import progress
from . import utils
import mqdm


def new_pbar(bytes=False, **kw):
    kw.setdefault('refresh_per_second', 8)
    return progress.Progress(
        "[progress.description]{task.description}",
        progress.BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.0f}%",
        *([progress.DownloadColumn()] if bytes else [utils.MofNColumn()]),
        progress.TimeRemainingColumn(),
        progress.TimeElapsedColumn(),
        **kw,
    )


def get_pbar(pbar, **kw):
    if not pbar and not mqdm.pbar:
        pbar = new_pbar(**kw)
        pbar.__enter__()
    if pbar:
        if mqdm.pbar:
            mqdm.pbar.__exit__(None, None, None)
        mqdm.pbar = pbar
    return mqdm.pbar


class Bar:
    _iter = None
    _entered = False
    _started = False
    total = None
    _get_desc = None
    _completed = 0

    def __init__(self, desc=None, *, bytes=False, pbar=None, transient=False, disable=False, **kw):
        if isinstance(desc, progress.Progress):
            desc, pbar = None, desc

        self.transient = transient
        self.disabled = disable
        self.pbar = get_pbar(pbar, bytes=bytes)
        total = kw.pop('total', None)
        self._started = total is not None
        kw = self._process_args(description=desc or '', total=total, **kw)
        kw.setdefault('description', '')
        self.task_id = self.pbar.add_task(**kw) if not self.disabled else None

    def remove(self):
        if self.disabled: return
        self.pbar.remove_task(self.task_id)

    # @property
    # def visible(self):
    #     if self.disabled: return False
    #     return self.pbar.tasks[self.task_id].visible

    def __enter__(self):
        if not self._entered:
            self._entered = True
            self._completed = 0
            if not self.disabled:
                self.pbar.__enter__()
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
            self.__exit__(None, None, None)
            if not mqdm._instances:
                if not self.disabled:
                    self.pbar.__exit__(None, None, None)
                mqdm.pbar = None
        except ImportError as e:
            pass

    def _get_iter(self, iter, desc=None, **kw):        
        self.update(0, total=self.total, description=desc, **kw)
        for i, x in enumerate(iter):
            self.update(i>0, arg_=x)
            yield x
        self.update()

    def __call__(self, iter, desc=None, total=None, **kw):
        self.total = utils.try_len(iter) if total is None else total
        self.update(0, total=self.total, description=desc, **kw)
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
        rich.print(*a, **kw)
        return self

    def set_description(self, desc):
        return self.update(0, description=desc)
    
    def _process_args(self, *, arg_=..., **kw):
        if 'transient' in kw:
            self.transient = kw.pop('transient')
        if 'total' in kw:
            self.total = kw['total']

        # get description
        if 'desc' in kw:
            kw['description'] = kw.pop('desc')
        if 'description' in kw and callable(kw['description']):
            self._get_desc = kw.pop('description')
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

        # update progress bar
        self.pbar.update(self.task_id, advance=n, **self._process_args(arg_=arg_, **kw))
        return self

    @classmethod
    def mqdm(cls, iter=None, desc=None, bytes=False, pbar=None, transient=False, disable=False, **kw):
        return cls(desc=desc, bytes=bytes, pbar=pbar, transient=transient, disable=disable)(iter, **kw)


# ---------------------------------------------------------------------------- #
#                                   Examples                                   #
# ---------------------------------------------------------------------------- #

def example(n=10, transient=False):
    t0 = time.time()
    for i in mqdm.mqdm(range(n), desc='example', transient=transient):
        mqdm.set_description(f'example {i}')
        for j in mqdm.mqdm(range(10), desc=f'blah {i}', transient=transient):
            time.sleep(0.04)
        # time.sleep(0.05)
    mqdm.print("done in", time.time() - t0, "seconds")
