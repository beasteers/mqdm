import mqdm as M  # self
from .runtime import Runtime, _current_runtime, configure


def sustain():
    """Keep the live progress display alive across this block.

    A sequence of separate bars normally renders one at a time — each freezes
    into the scrollback as the next begins. Inside ``sustain()`` they stack and
    stay visible together as one growing panel, with ``print``/logging streaming
    above them. Nestable.
    """
    return _current_runtime().sustain()


def print(*args, **kw):
    """Print above active progress bars."""
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


def install_logging(logger=None, *, level=None, capture_warnings='process', markup=True, formatter=None):
    """Install an MQDMHandler on a logger for a runtime."""
    return _current_runtime().install_logging(
        logger=logger,
        level=level,
        capture_warnings=capture_warnings,
        markup=markup,
        formatter=formatter,
    )


def uninstall_logging(*, logger=None):
    """Remove an MQDMHandler from a logger for a runtime."""
    return _current_runtime().uninstall_logging(logger=logger)

# ----------------------------------- Utils ---------------------------------- #

from . import utils
from .executor import T_POOL_MODE, get_executor
from .utils import args, fn, fopen, ratelimit
from ._logging import MQDMHandler

# ---------------------------------- Events ---------------------------------- #

from . import events
from . import event_stream

# ----------------------------------- Core ----------------------------------- #

from .bar import mqdm
from .pool import ipool, pool, PoolError
from .apool import aipool, apool

# ----------------------------- Development utils ---------------------------- #

from ._dev import bp, embed, iex, profile, timeit

__all__ = [
    'mqdm',
    'pool',
    'ipool',
    'apool',
    'aipool',
    'print',
    'sustain',
    'pause',
    'args',
    'PoolError',
    'configure',
]
