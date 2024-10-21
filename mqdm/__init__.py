from contextlib import contextmanager

import rich
from rich import progress


import mqdm as M  # self
from . import proxy
from . import utils
from .utils import T_POOL_MODE
from .utils import args, executor
from .utils import embed, inp, bp, iex


_manager = None
_instances = []
_keep = False
pbar: 'proxy.Progress|proxy.ProgressProxy' = None


# ---------------------------------------------------------------------------- #
#                               Progress methods                               #
# ---------------------------------------------------------------------------- #


def _new_pbar(pool_mode: T_POOL_MODE=None, bytes=False, **kw):
    kw.setdefault('refresh_per_second', 8)
    return proxy.get_progress_cls(pool_mode)(
        "[progress.description]{task.description}",
        progress.BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.0f}%",
        utils.MofNColumn(bytes=bytes),
        utils.SpeedColumn(bytes=bytes),
        utils.TimeElapsedColumn(compact=True),
        progress.TimeRemainingColumn(compact=True),
        progress.SpinnerColumn(),
        **kw,
    )


def _get_pbar(pool_mode: T_POOL_MODE=None, start=True, **kw):
    # no progress bar yet, create one
    if not M.pbar:
        # print("New progress bar", pool_mode)
        M.pbar = _new_pbar(pool_mode=pool_mode, **kw)
    # need to create multiprocess-compatible progress bar
    elif pool_mode == 'process' and not M.pbar.multiprocess:
        # print("Converting proxy")
        M.pbar = M.pbar.convert_proxy()
    if start:
        M.pbar.start()
    return M.pbar


def _clear_pbar(strict=True, force=False, soft=False):
    """Clear the progress bar."""
    if force:
        for bar in _instances[::-1]:
            bar._remove(False)
            bar.disable = True
        M.pbar.stop()
        M.pbar = None
    if M._instances:
        if strict:
            raise RuntimeError("Cannot clear progress bar while instances are still active.")
    elif not utils.is_main_process():
        if strict:
            raise RuntimeError("Cannot clear progress bar in a subprocess.")
    elif soft or M._keep:
        if M.pbar is not None:
            M.pbar.refresh()
    else:
        if M.pbar is not None:
            M.pbar.stop()
        M.pbar = None


@contextmanager
def group():
    """Group progress bars."""
    try:
        M._keep = True
        yield 
    finally:
        M._keep = False
        _clear_pbar()


# ---------------------------------------------------------------------------- #
#                            Global context methods                            #
# ---------------------------------------------------------------------------- #


def print(*args, **kw):
    """Print with rich."""
    if pbar is not None:
        return pbar.print(*args, **kw)
    return rich.print(*args, **kw)


def get(i=-1):
    """Get an mqdm instance."""
    try:
        return _instances[i]
    except IndexError:
        raise IndexError(f'No progress bar found at index {i} in list of length {len(_instances)}')


def set_description(desc, i=-1):
    """Set the description of the last progress bar."""
    return get(i).set_description(desc)


def set(i=-1, **kw):
    """Set the last progress bar."""
    return get(i).set(**kw)


def update(n=1, i=-1, **kw):
    """Update the last progress bar."""
    return get(i).update(n, **kw)


def _add_instance(bar):
    if bar not in _instances:
        _instances.append(bar)
    return bar

def _remove_instance(bar):
    while bar in _instances:
        _instances.remove(bar)


def pause(paused=True):
    """Pause the progress bars. Useful for opening an interactive shell or printing stack traces."""
    prev_paused = getattr(pbar, 'paused', False)
    if pbar is not None:
        pbar.paused = paused
        if paused:
            pbar.stop()
        else:
            pbar.start()
    return _pause_exit(prev_paused)

class _pause_exit:
    def __init__(self, prev_paused):
        self.prev_paused = prev_paused  # it was paused before we got here
        _pause_exit.last = self  # if another pause was called, ignore this one
    def __enter__(self): pass
    def __exit__(self, c, exc, t): 
        if not exc and not self.prev_paused and self is _pause_exit.last:  # dont unpause for exceptions
            pause(False)


# ---------------------------------------------------------------------------- #
#                               Primary interface                              #
# ---------------------------------------------------------------------------- #


from .bar import mqdm, pool, ipool

# more descriptive names to avoid polluting the namespace
mqpool = pool
mqipool = ipool

__all__ = [
    'mqdm',
    'mqpool',
    'mqipool',
]