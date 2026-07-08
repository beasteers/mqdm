from contextlib import contextmanager

import mqdm as M  # self

from .runtime import Runtime, _current_runtime, _runtime


@contextmanager
def group():
    """Group progress bars."""
    runtime = _current_runtime()
    runtime.keep_depth += 1
    runtime.keep = True
    try:
        yield
    finally:
        runtime.keep_depth = max(runtime.keep_depth - 1, 0)
        runtime.keep = runtime.keep_depth > 0
        if not runtime.keep:
            runtime.clear_pbar()


def print(*args, **kw):
    """Print with rich."""
    return _current_runtime().print(*args, **kw)


def get(i=-1):
    """Get an mqdm instance."""
    return _current_runtime().get_instance(i)


def set_description(desc, i=-1):
    """Set the description of the last progress bar."""
    return get(i).set_description(desc)


def set(i=-1, **kw):
    """Set the last progress bar."""
    return get(i).set(**kw)


def update(n=1, i=-1, **kw):
    """Update the last progress bar."""
    return get(i).update(n, **kw)


def pause(paused=True):
    """Pause the progress bars. Useful for opening an interactive shell or printing stack traces."""
    return _current_runtime().pause(paused)


# ---------------------------------- Logging --------------------------------- #


def install_logging(logger=None, *, level=None, capture_warnings='process', markup=True, formatter=None, runtime=None):
    """Install an MQDMHandler on a logger for a runtime."""
    runtime = runtime or _current_runtime()
    return runtime.install_logging(
        logger=logger,
        level=level,
        capture_warnings=capture_warnings,
        markup=markup,
        formatter=formatter,
    )


def uninstall_logging(*, logger=None, runtime=None):
    """Remove an MQDMHandler from a logger for a runtime."""
    runtime = runtime or _current_runtime()
    return runtime.uninstall_logging(logger=logger)

# ----------------------------------- Utils ---------------------------------- #

from .executor import T_POOL_MODE, executor
from .utils import args, fn, fopen, ratelimit
from ._logging import MQDMHandler

# ----------------------------------- Core ----------------------------------- #

from .bar import mqdm
from .pool import ipool, pool

# ----------------------------- Development utils ---------------------------- #

from ._dev import bp, embed, iex, inp, profile, timeit
M.input = inp

__all__ = [
    'mqdm',
    'pool',
    'ipool',
]
