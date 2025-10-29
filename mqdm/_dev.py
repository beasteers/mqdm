import sys
import time
import functools
from types import TracebackType
import rich
from rich.prompt import Prompt
from rich.console import Text

import mqdm as M

# ---------------------------------------------------------------------------- #
#                                  Debug Tools                                 #
# ---------------------------------------------------------------------------- #


def embed(*a, prompt='ipython?> ', exit_prompt=True):
    """Embed an IPython shell in the current environment. This will make sure the progress bars don't interfere.
    
    This function is useful for debugging and interactive exploration.

    Does not work in subprocesses for obvious reasons.

    .. code-block:: python

        import mqdm

        for i in mqdm_.mqdm(range(10)):
            if i == 5:
                mqdm_.embed()
    """
    with M.pause():
        from ._embed import embed
        if not prompt or _Prompt.ask(Text(f'{prompt}', style="dim cyan")): 
            a and M.print(*a)
            embed(colors='neutral', stack_depth=1)
            exit_prompt and _Prompt.ask(Text('continue?> ', style="bold magenta"))


class _Prompt(Prompt):
    prompt_suffix = ''
    def get_input(self, console, *a, **kw):
        x = super().get_input(console, *a, **kw)
        console.print('\033[F\033[A', end='')
        return x


def inp(prompt=''):
    """Prompt for input in the terminal. This function is useful for debugging and interactive exploration."""
    with M.pause():
        return _Prompt.ask(Text(prompt or '', style="dim cyan"))


def bp(*a, prompt='breakpoint?> '):
    """Breakpoint"""
    with M.pause():
        a and M.print(*a)
        if not prompt or _Prompt.ask(Text(prompt, style="dim cyan")):
            breakpoint()


def pdb():
    try:
        import pdbr as pdb
    except ImportError:
        try:
            import ipdb as pdb
        except ImportError:
            import pdb
    return pdb


def post_mortem(tb: TracebackType):
    def _print_exc():
        import fnmatch
        rich.console.Console().print_exception(
            suppress=[m for k, m in sys.modules.items() if any(
                fnmatch.fnmatch(k, p) for p in ['fire', 'concurrent.futures', 'threading', 'multiprocessing'])]
        )
        cmds = 'h: help, u: up, d: down, l: code, v: vars, vt: varstree, w: stack, i {var}: inspect'
        rich.print("\n[bold dim]Commands - [/bold dim] " + ", ".join(
            "[bold green]{}[/bold green]:[dim]{}[/dim]".format(*c.split(':')) for c in cmds.split(', ')
        ))

    if tb is not None:
        M.pause(True)
        _print_exc()
        pdb().post_mortem(tb)
        M.pause(False)


def iex(func):
    """Decorator to embed an interactive post-mortem debugger on exception.

    Tries to use `pdbr` if installed; otherwise, prints a rich traceback and re-raises.
    Does not work in subprocesses for obvious reasons.
    """
    import functools
    @functools.wraps(func)
    def outer(*a, **kw):
        _rich_traceback_omit = True
        try:
            return func(*a, **kw)
        except BaseException as e:
            post_mortem(getattr(e, '__traceback__', None))
    return outer


def profile(func=None, **pkw):
    """Decorator to profile a function using pyinstrument."""
    profiler_kw = {k: pkw.pop(k) for k in ['interval', 'use_timing_thread', 'async_mode'] if k in pkw}
    def wrapper(func):
        @functools.wraps(func)
        def outer(*a, **kw):
            import pyinstrument
            p = pyinstrument.Profiler(**(profiler_kw or {}))
            try:
                with p:
                    return func(*a, **kw)
            finally:
                M.pause(True)
                pkw.setdefault('color', True)
                p.print(**pkw)
        return outer
    return wrapper(func) if func is not None else wrapper


def timeit(func=None, **pkw):
    @functools.wraps(func)
    def wrapper(*a, **kw):
        start = time.perf_counter()
        try:
            return func(*a, **kw)
        finally:
            end = time.perf_counter()
            print(f"Function {func.__name__} took {end - start:.4f} seconds")
    return wrapper
