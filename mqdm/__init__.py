from .runtime import Runtime, _current_runtime, configure


def sustain():
    """Keep the live progress display alive across this block.

    A sequence of separate bars normally renders one at a time — each freezes
    into the scrollback as the next begins. Inside ``sustain()`` they stack and
    stay visible together as one growing panel, with ``print``/logging streaming
    above them. Nestable.

    Example:
        ```python
        with mqdm.sustain():
            for i in range(3):
                for _ in mqdm.mqdm(range(4), desc=f"section {i}"):
                    ...
        ```
    """
    return _current_runtime().sustain()


def print(*args, **kw):
    """Print above the live bars — worker-safe, unlike the builtin ``print``.

    Takes the same arguments as ``rich.print`` and renders the output above the
    active progress display instead of tearing through it. Works from pool workers
    too: output is routed to the process that owns the display, so it lands in one
    coordinated place. Use this (or ``logging``) instead of the builtin ``print``
    while bars are live.

    Example:
        ```python
        for path in mqdm.mqdm(paths):
            if is_interesting(path):
                mqdm.print("found", path)   # stays above the bar
        ```
    """
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
    """Freeze the live display for a ``with`` block, then resume — for using the terminal.

    Holds the bars' state and stops rendering so you can safely drop into an
    interactive shell, ``pdb``, a stack trace, or a prompt on a clean screen. As a
    context manager the bars resume automatically on exit; ``pause(False)`` resumes
    immediately.

    Example:
        ```python
        for i in mqdm.mqdm(range(100)):
            if something_wrong(i):
                with mqdm.pause():
                    import IPython; IPython.embed()   # clean screen, bars frozen
        ```
    """
    return _current_runtime().pause(paused)


# ---------------------------------- Logging --------------------------------- #


def install_logging(logger=None, *, level=None, capture_warnings='process', markup=True, formatter=None):
    """Route a logger's records above the live bars (and across pool workers).

    Attaches an mqdm handler to ``logger`` (the root logger by default) so log
    output renders above the progress display instead of clobbering it, and worker
    logs are forwarded to the display owner. ``capture_warnings='process'`` also
    captures :mod:`warnings` in process-pool workers. See
    :meth:`Runtime.install_logging` for the full argument reference.

    Example:
        ```python
        import logging
        mqdm.install_logging(level=logging.INFO)
        logging.getLogger(__name__).info("started")   # appears above the bars
        ```
    """
    return _current_runtime().install_logging(
        logger=logger,
        level=level,
        capture_warnings=capture_warnings,
        markup=markup,
        formatter=formatter,
    )


def uninstall_logging(*, logger=None):
    """Remove mqdm's log routing from ``logger`` (the root logger by default).

    Reverses :func:`install_logging` and releases any warning capture it enabled.
    """
    return _current_runtime().uninstall_logging(logger=logger)

# ----------------------------------- Utils ---------------------------------- #

from . import utils
from .parallel.executor import T_POOL_MODE, get_executor, Initializer
from .utils import args, fn, fopen, ratelimit
from .utils._logging import MQDMHandler

# --------------------------------- Columns ---------------------------------- #
# Progress columns for customizing bar layout via ``backend_options["columns"]``.
from .utils import columns

# ---------------------------------- Events ---------------------------------- #

from . import events

# ----------------------------------- Core ----------------------------------- #

from .bar import mqdm
from .parallel.pool import ipool, pool, PoolError, Result
from .parallel.apool import aipool, apool

# ----------------------------- Development utils ---------------------------- #

from .utils._dev import bp, embed, iex, profile, timeit

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
