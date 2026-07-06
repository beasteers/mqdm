import atexit
import threading
import time
import weakref
from collections import OrderedDict
from contextlib import contextmanager

import rich
from rich import progress

import mqdm as M  # self
from . import utils


class Runtime:
    def __init__(self):
        self.pbar = None
        self.manager = None
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.shutdown_event = threading.Event()
        self.shutdown_event.set()
        self.instances = OrderedDict()
        self.keep = False
        self.logging_config = None
        self.last_pause_wait_time = 0
        self.pause_wait_ttl_seconds = 0.2

    def new_pbar(self, pool_mode=None, bytes=False, **kw):
        from . import proxy

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
            runtime=self,
            **kw,
        )

    def get_pbar(self, pool_mode=None, start=True, **kw):
        pbar = self.pbar
        if pbar is None:
            pbar = self.pbar = self.new_pbar(pool_mode=pool_mode, **kw)
        elif pool_mode == 'process' and not pbar.multiprocess:
            pbar = self.pbar = pbar.convert_proxy(runtime=self)
        if start:
            pbar.start()
        return pbar

    def clear_pbar(self, strict=True, force=False, soft=False):
        if force:
            for bar_ref in reversed(list(self.instances.values())):
                bar = bar_ref()
                if bar is not None:
                    bar.close(remove=False)
                    bar.disable = True
            if self.pbar is not None:
                self.pbar.stop()
            self.pbar = None
        if self.instances:
            if strict:
                raise RuntimeError("Cannot clear progress bar while instances are still active.")
        elif not utils.is_main_process():
            if strict:
                raise RuntimeError("Cannot clear progress bar in a subprocess.")
        elif soft or self.keep:
            if self.pbar is not None:
                self.pbar.refresh()
        else:
            if self.pbar is not None:
                self.pbar.start()
                self.pbar.refresh()
                self.pbar.stop()
            self.pbar = None

    def add_instance(self, bar):
        self.instances.setdefault(hash(bar), weakref.ref(bar))
        return bar

    def remove_instance(self, bar):
        self.instances.pop(hash(bar), None)

    def get_instance(self, i=-1):
        try:
            return list(self.instances.values())[i]()
        except IndexError:
            raise IndexError(f'No progress bar found at index {i} in list of length {len(self.instances)}')

    def close_instances(self):
        for bar_ref in list(self.instances.values()):
            bar = bar_ref()
            if bar is not None:
                bar.close()
        self.instances.clear()

    def pause_wait(self):
        self.pause_event.wait()

    def ttl_pause_wait(self):
        current_time = int(time.time() / self.pause_wait_ttl_seconds)
        if current_time != self.last_pause_wait_time:
            self.last_pause_wait_time = current_time
            self.pause_event.wait()

    def pause(self, paused=True):
        pbar = self.pbar
        prev_paused = getattr(pbar, 'paused', False)
        if pbar is not None:
            pbar.paused = paused
            if paused:
                pbar.stop()
                self.pause_event.clear()
            else:
                pbar.start()
                self.pause_event.set()
        return _pause_exit(prev_paused)

    def print(self, *args, **kw):
        if self.pbar is not None:
            return self.pbar.print(*args, **kw)
        return rich.print(*args, **kw)

    def install_worker_context(self, *, pbar, pause_event, shutdown_event, logging_config):
        self.pbar = pbar
        self.pause_event = pause_event
        self.shutdown_event = shutdown_event
        self.logging_config = logging_config


_runtime = Runtime()


def _get_pbar(pool_mode=None, start=True, **kw):
    return _runtime.get_pbar(pool_mode=pool_mode, start=start, **kw)


def _clear_pbar(strict=True, force=False, soft=False):
    return _runtime.clear_pbar(strict=strict, force=force, soft=soft)


def _add_instance(bar):
    return _runtime.add_instance(bar)


def _remove_instance(bar):
    return _runtime.remove_instance(bar)


def _close_instances():
    return _runtime.close_instances()


@contextmanager
def group():
    """Group progress bars."""
    try:
        _runtime.keep = True
        yield
    finally:
        _runtime.keep = False
        _runtime.clear_pbar()


def print(*args, **kw):
    """Print with rich."""
    return _runtime.print(*args, **kw)


def get(i=-1):
    """Get an mqdm instance."""
    return _runtime.get_instance(i)


def set_description(desc, i=-1):
    """Set the description of the last progress bar."""
    return get(i).set_description(desc)


def set(i=-1, **kw):
    """Set the last progress bar."""
    return get(i).set(**kw)


def update(n=1, i=-1, **kw):
    """Update the last progress bar."""
    return get(i).update(n, **kw)


def _pause_wait():
    _runtime.pause_wait()


def _ttl_pause_wait():
    _runtime.ttl_pause_wait()


def pause(paused=True):
    """Pause the progress bars. Useful for opening an interactive shell or printing stack traces."""
    return _runtime.pause(paused)


class _pause_exit:
    def __init__(self, prev_paused):
        self.prev_paused = prev_paused
        _pause_exit.last = self

    def __enter__(self):
        pass

    def __exit__(self, c, exc, t):
        if not exc and not self.prev_paused and self is _pause_exit.last:
            pause(False)


atexit.register(_close_instances)


from .executor import executor, T_POOL_MODE, Initializer
from ._dev import embed, inp, bp, iex, profile, timeit
from .utils import args, fn, fopen, ratelimit

M.input = inp

from .bar import mqdm
from .pool import pool, ipool
from ._logging import install as install_logging, uninstall as uninstall_logging


mqpool = pool
mqipool = ipool

__all__ = [
    'mqdm',
    'mqpool',
    'mqipool',
]
