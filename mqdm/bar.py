''''''
import time
import rich
from rich import progress
from . import utils
import mqdm


def new_pbar(bytes=False):
    return progress.Progress(
        "[progress.description]{task.description}",
        progress.BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        *([progress.DownloadColumn()] if bytes else [utils.MofNColumn()]),
        progress.TimeRemainingColumn(),
        progress.TimeElapsedColumn(),
        refresh_per_second=8,
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
    total = None

    def __init__(self, desc=None, *, bytes=False, pbar=None, transient=False, **kw):
        if isinstance(desc, progress.Progress):
            desc, pbar = None, desc

        self.transient = transient
        self.pbar = get_pbar(pbar, bytes=bytes)
        self.task_id = self.pbar.add_task(description=desc, start=kw.get('total') is not None, **kw)

    def __enter__(self):
        if not self._entered:
            self._entered = True
            self.pbar.__enter__()
            self.pbar.start_task(self.task_id)
            mqdm._add_instance(self)
        return self

    def __exit__(self, c,v,t):
        if self._entered:
            self._entered = False
            self.pbar.refresh()
            self.pbar.stop_task(self.task_id)
            if self.transient:
                self.pbar.remove_task(self.task_id)
            mqdm._remove_instance(self)

    def __del__(self):
        try:
            self.__exit__(None, None, None)
            if not mqdm._instances:
                self.pbar.__exit__(None, None, None)
                mqdm.pbar = None
        except ImportError as e:
            pass

    def __call__(self, iter, total=None, **kw):
        self.total = utils.try_len(iter) if total is None else total
        def _iter():
            self.update(0, total=self.total, **kw)
            for i, x in enumerate(iter):
                yield x
                self.update()
        def _with_iter():
            if self._entered:
                yield from _iter()
                return
            with self:
                yield from _iter()
        self._iter = _with_iter()
        return self

    def __len__(self):
        return self.total or 0

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._iter)

    def print(self, *a, **kw):
        rich.print(*a, **kw)
        return self

    def set_description(self, desc):
        return self.update(0, description=desc)

    def update(self, n=1, **kw):
        if 'transient' in kw:
            self.transient = kw.pop('transient')
        self.pbar.update(self.task_id, advance=n, **kw)
        return self

    @classmethod
    def mqdm(cls, iter=None, desc=None, bytes=False, pbar=None, transient=False, **kw):
        return cls(desc=desc, bytes=bytes, pbar=pbar, transient=transient)(iter, **kw)


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
