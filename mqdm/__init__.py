import sys
import rich
from rich import progress
from rich.prompt import Prompt
from rich.console import Text


_manager = None
_instances = []
pbar = None

import mqdm as mqdm_  # self
from . import proxy



def new_pbar(bytes=False, pool_mode=None, **kw):
    kw.setdefault('refresh_per_second', 8)
    cls = proxy.Progress
    if pool_mode == 'process':
        cls = proxy.get_manager().mqdm_Progress
    return cls(
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


def get_pbar(pbar=None, pool_mode=None, **kw):
    if not pbar and pool_mode == 'process' and not mqdm_._manager:
        pbar = new_pbar(pool_mode=pool_mode, **kw)
    elif not pbar and not mqdm_.pbar:
        pbar = new_pbar(pool_mode=pool_mode, **kw)
    if pbar:
        if mqdm_.pbar:
            mqdm_.pbar.stop()
        mqdm_.pbar = pbar
        pbar.start()
    return mqdm_.pbar


def print(*args, **kw):
    """Print with rich."""
    if pbar is not None:
        return pbar.print_(*args, **kw)
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


def embed(*a, prompt='ipython?> ', exit_prompt=True):
    """Embed an IPython shell in the current environment. This will make sure the progress bars don't interfere.
    
    This function is useful for debugging and interactive exploration.

    Does not work in subprocesses for obvious reasons.

    .. code-block:: python

        import mqdm

        for i in mqdm.mqdm(range(10)):
            if i == 5:
                mqdm.embed()
    """
    with pause():
        from ._embed import embed
        if not prompt or _Prompt.ask(Text(f'{prompt}', style="dim cyan")): 
            a and mqdm_.print(*a)
            embed(colors='neutral', stack_depth=1)
            exit_prompt and Prompt.ask(Text('continue?> ', style="bold magenta"))


class _Prompt(Prompt):
    prompt_suffix = '\033[F'

def bp(*a, prompt='ipython?> '):
    """Breakpoint"""
    with pause():
        if not prompt or Prompt.ask(Text(prompt, style="dim cyan")):
            a and mqdm_.print(*a)
            breakpoint()


def iex(func):
    """Decorator to embed an IPython shell in the current environment when an exception is raised. This makes sure the progress bars don't interfere.
    
    This lets you do post-mortem debugging of the Exception stack trace.

    Does not work in subprocesses for obvious reasons.
    """
    import functools, fnmatch
    from pdbr import pdbr_context
    # from ipdb import iex
    @pdbr_context()
    def inner(*a, **kw):
        _rich_traceback_omit = True
        try:
            return func(*a, **kw)
        except:
            pause(True)
            rich.console.Console().print_exception(suppress=[m for k, m in sys.modules.items() if any(
                fnmatch.fnmatch(k, p) for p in ['fire', 'concurrent.futures', 'threading', 'multiprocessing'])])
            cmds='h: help, u: up, d: down, l: code, v: vars, vt: varstree, w: stack, i {var}: inspect'
            rich.print("\n[bold dim]Commands - [/bold dim] " + ", ".join("[bold green]{}[/bold green]:[dim]{}[/dim]".format(*c.split(':')) for c in cmds.split(', ')))
            raise
    @functools.wraps(func)
    def outer(*a, **kw):
        try:
            return inner(*a, **kw)
        finally:
            pause(False)
    return outer


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