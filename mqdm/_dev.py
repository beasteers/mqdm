import sys
import functools
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


def bp(*a, prompt='ipython?> '):
    """Breakpoint"""
    with M.pause():
        if not prompt or _Prompt.ask(Text(prompt, style="dim cyan")):
            a and M.print(*a)
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
            M.pause(True)
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
            M.pause(False)
    return outer

def profile(func):
    """Decorator to profile a function using pyinstrument."""
    @functools.wraps(func)
    def outer(*a, **kw):
        import pyinstrument
        p = pyinstrument.Profiler()
        try:
            with p:
                return func(*a, **kw)
        finally:
            M.pause(True)
            p.print(color=True)
    return outer
