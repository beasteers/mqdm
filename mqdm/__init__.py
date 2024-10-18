# from rich import print
import rich
from rich import progress

_manager = None
_remote = None
_instances = []
pbar = None

import mqdm as mqdm_  # self



def new_pbar(bytes=False, **kw):
    kw.setdefault('refresh_per_second', 8)
    cls = progress.Progress
    if mqdm_._manager:
        cls = mqdm_._manager.mqdm_Progress
    # print(cls)
    return cls(
        "[progress.description]{task.description}",
        progress.BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.0f}%",
        *([progress.DownloadColumn()] if bytes else [utils.MofNColumn()]),
        *([progress.TransferSpeedColumn()] if bytes else [utils.SpeedColumn()]),
        progress.TimeRemainingColumn(compact=True),
        utils.TimeElapsedColumn(compact=True),
        progress.SpinnerColumn(),
        **kw,
    )


def get_pbar(pbar=None, **kw):
    new = False
    if not pbar and not mqdm_.pbar:
        pbar = new_pbar(**kw)
        new = True
    if pbar:
        if mqdm_.pbar:
            mqdm_.pbar.stop()
        mqdm_.pbar = pbar
    if new:
        pbar.start()
    return mqdm_.pbar


def _pbar_initializer(pbar):
    mqdm_.pbar = pbar


def print(*args, **kw):
    """Print with rich."""
    # if _remote is not None:
    #     _remote.print(*args, **kw)
    if pbar is not None:
        pbar.print(*args, **kw)
    return rich.print(*args, **kw)

def get(i=-1):
    """Get a progress bar instance."""
    try:
        return _instances[i]
    except IndexError:
        raise IndexError(f'No progress bar found at index {i} in list of length {len(_instances)}')

def set_description(desc, i=-1):
    """Set the description of the last progress bar."""
    return get(i).set_description(desc)

def _add_instance(bar):
    if bar not in _instances:
        _instances.append(bar)
    return bar

def _remove_instance(bar):
    while bar in _instances:
        _instances.remove(bar)


def pause(paused=True):
    if pbar is not None:
        if paused:
            pbar.stop()
        else:
            pbar.start()


def embed():
    """Embed an IPython shell in the current environment. This will make sure the progress bars don't interfere.
    
    This function is useful for debugging and interactive exploration.

    Does not work in subprocesses for obvious reasons.

    .. code-block:: python

        import mqdm

        for i in mqdm.mqdm(range(10)):
            if i == 5:
                mqdm.embed()
    """
    try:
        pause(True)
        from IPython import embed
        # IPython.InteractiveShellEmbed.mainloop
        # import inspect
        # frame = inspect.currentframe().f_back
        # namespace = frame.f_globals.copy()
        # namespace.update(frame.f_locals)
        embed(colors='neutral')
    finally:
        pause(False)


def iex(func):
    """Decorator to embed an IPython shell in the current environment when an exception is raised. This makes sure the progress bars don't interfere.
    
    This lets you do post-mortem debugging of the Exception stack trace.

    Does not work in subprocesses for obvious reasons.
    """
    import functools
    import ipdb
    @ipdb.iex
    def inner(*a, **kw):
        try:
            return func(*a, **kw)
        except Exception as e:
            pause(True)
            raise
    @functools.wraps(func)
    def outer(*a, **kw):
        try:
            return inner(*a, **kw)
        finally:
            pause(False)
    return outer


def as_remote():
    from .proxy import get_manager
    get_manager()


from . import utils
from .utils import args
from .bar import Bar
from .bars import Bars
pool = Bars.pool
mqdm = Bar.mqdm
mqdms = Bars.mqdms
mqdm_pool = Bars.pool

__all__ = [
    'mqdm',
    'mqdms',
    'mqdm_pool',
]