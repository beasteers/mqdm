import functools
import time

import mqdm as M

# ---------------------------------------------------------------------------- #
#                               Drop-in Consoles                               #
# ---------------------------------------------------------------------------- #

_PromptCls = None
def _ask_prompt(prompt: str, style: str = "dim cyan") -> bool:
    # This is so we can make rich a lazy import
    global _PromptCls
    from rich.prompt import Prompt
    from rich.console import Text
    if _PromptCls is None:
        class _Prompt(Prompt):
            prompt_suffix = ''
            def get_input(self, console, *a, **kw):
                x = super().get_input(console, *a, **kw)
                console.print('\033[F\033[A', end='')
                return x
        _PromptCls = _Prompt
    return _PromptCls.ask(Text(prompt, style=style))

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
        if not prompt or _ask_prompt(f'{prompt}', style="dim cyan"):
            a and M.print(*a)
            embed(colors='neutral', stack_depth=1)
            exit_prompt and _ask_prompt('continue?> ', style="bold magenta")


def bp(*a, prompt='breakpoint?> '):
    """Breakpoint"""
    with M.pause():
        a and M.print(*a)
        if not prompt or _ask_prompt(prompt, style="dim cyan"):
            breakpoint()


def iex(func):
    """Decorator to enter an interactive post-mortem debugger on exception.

    Tries ``pdbr``, then ``ipdb``, then stdlib ``pdb``.  Catches
    ``BaseException`` so Ctrl-C (``KeyboardInterrupt``) also drops into
    the debugger at the interruption point.
    """
    @functools.wraps(func)
    def outer(*a, **kw):
        try:
            return func(*a, **kw)
        except (Exception, KeyboardInterrupt) as e:
            tb = e.__traceback__
            if tb is not None:
                M.pause(True)
                _print_rich_traceback()
                _get_debugger().post_mortem(tb)
                M.pause(False)
    return outer




def _get_debugger():
    try:
        import pdbr as pdb_mod
    except ImportError:
        try:
            import ipdb as pdb_mod
        except ImportError:
            import pdb as pdb_mod
    return pdb_mod


_FRAMEWORK_MODULES = ('fire', 'concurrent.futures', 'threading', 'multiprocessing')


def _print_rich_traceback():
    import fnmatch
    import sys
    import rich
    from rich.console import Console
    Console().print_exception(
        suppress=[
            m for k, m in sys.modules.items()
            if any(fnmatch.fnmatch(k, p) for p in _FRAMEWORK_MODULES)
        ]
    )
    cmds = 'h: help, u: up, d: down, l: code, v: vars, vt: varstree, w: stack, i {var}: inspect'
    rich.print("\n[bold dim]Commands - [/bold dim] " + ", ".join(
        "[bold green]{}[/bold green]:[dim]{}[/dim]".format(*c.split(':')) for c in cmds.split(', ')
    ))


# ---------------------------------------------------------------------------- #
#                                   Profiling                                  #
# ---------------------------------------------------------------------------- #


def profile(func=None, **pkw):
    """Decorator to profile a function using pyinstrument."""
    profiler_kw = {**profile.kw, **{k: pkw.pop(k) for k in ['interval', 'use_timing_thread', 'async_mode'] if k in pkw}}
    def wrapper(func):
        @functools.wraps(func)
        def outer(*a, **kw):
            import pyinstrument
            p = pyinstrument.Profiler(**(profiler_kw or {}))
            try:
                with p:
                    return func(*a, **kw)
            finally:
                with M.pause():
                    pkw.setdefault('color', True)
                    p.print(**pkw)
        return outer
    return wrapper(func) if func is not None else wrapper
profile.kw = {}


def timeit(func=None, **pkw):
    def wrap(func):
        @functools.wraps(func)
        def wrapper(*a, **kw):
            start = time.perf_counter()
            try:
                return func(*a, **kw)
            finally:
                end = time.perf_counter()
                print(f"Function {func.__name__} took {end - start:.4f} seconds")
        return wrapper
    return wrap(func) if func is not None else wrap
