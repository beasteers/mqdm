import time
from contextlib import contextmanager

import rich
from rich import progress


import mqdm as M  # self
from . import proxy
from . import utils
# from .executor import SequentialExecutor, ProcessPoolExecutor, ThreadPoolExecutor, Executor
from .executor import executor, T_POOL_MODE, Initializer
from ._dev import embed, inp, bp, iex, profile, timeit
from .utils import args, fopen, ratelimit
M.input = inp

_logging_config: dict|None = None
_manager: 'proxy.MqdmManager' = None
_instances: 'list[M.mqdm]' = []
_keep = False
pbar: 'proxy.Progress|proxy.ProgressProxy' = None


# ---------------------------------------------------------------------------- #
#                               Progress methods                               #
# ---------------------------------------------------------------------------- #


def _new_pbar(pool_mode: T_POOL_MODE=None, bytes=False, **kw) -> 'proxy.Progress|proxy.ProgressProxy':
    kw.setdefault('refresh_per_second', 8)
    return proxy.get_progress_instance(
        pool_mode,
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


def _get_pbar(pool_mode: T_POOL_MODE=None, start=True, **kw) -> 'proxy.Progress|proxy.ProgressProxy':
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
            M.pbar.start()
            M.pbar.refresh()
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
        return list(_instances.values())[i]()
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



import weakref
from collections import OrderedDict

_instances = OrderedDict()

def _add_instance(bar):
    if bar not in _instances:
        _instances[hash(bar)] = weakref.ref(bar)
    return bar

def _remove_instance(bar):
    _instances.pop(hash(bar), None)  # Safely remove without error if bar is not found

def _close_instances():
    for bar_ref in list(_instances.values()):  # Make sure to use list() to avoid modifying while iterating
        bar = bar_ref()
        if bar is not None:
            bar.close()
    _instances.clear()

import atexit
atexit.register(_close_instances)


def _pause_wait():
    M._pause_event.wait()

_last_pause_wait_time = 0
_pause_wait_ttl_seconds = 0.2
def _ttl_pause_wait(): # lru_cache(1)(_pause_wait)(int(time.time()/ttl))
    global _last_pause_wait_time
    current_time = int(time.time() / _pause_wait_ttl_seconds)
    if current_time != _last_pause_wait_time:
        _last_pause_wait_time = current_time
        M._pause_event.wait()


def pause(paused=True):
    """Pause the progress bars. Useful for opening an interactive shell or printing stack traces."""
    prev_paused = getattr(pbar, 'paused', False)
    if pbar is not None:
        pbar.paused = paused
        if paused:
            pbar.stop()
            M._pause_event.clear()
        else:
            pbar.start()
            M._pause_event.set()
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
from ._logging import install as install_logging, uninstall as uninstall_logging


# more descriptive names to avoid polluting the namespace
mqpool = pool
mqipool = ipool

__all__ = [
    'mqdm',
    'mqpool',
    'mqipool',
]
