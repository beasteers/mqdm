import sys
from typing import Literal, cast, TextIO, IO, Optional
from concurrent.futures import Future, Executor, ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures._base import FINISHED, RUNNING
import multiprocessing as mp
import rich
from rich import progress
from rich.prompt import Prompt
from rich.console import Text

import mqdm as M


# ---------------------------------------------------------------------------- #
#                                     Utils                                    #
# ---------------------------------------------------------------------------- #


def is_main_process():
    """Check if the current process is the main process."""
    return mp.current_process().name == 'MainProcess'


class args:
    '''Storing Function Arguments for later.
    
    Example:
    ```
    def fn(a, b=2, c=3):
        print(a, b, c)

    fn_args = [args(i, c=i*2) for i in range(3)]
    for arg in fn_args:
        arg(fn, b=2)
    ```
    '''
    def __init__(self, *a, **kw):
        self.a = a
        self.kw = kw

    def __getitem__(self, i):
        return self.a[i] if isinstance(i, int) else self.kw[i]

    def __call__(self, fn, *a, **kw):
        return fn(*self.a, *a, **dict(self.kw, **kw)) if callable(fn) else fn
    
    @classmethod
    def call(cls, fn, x, *a, **kw):
        return cls.from_item(x)(fn, *a, **kw)
    
    @classmethod
    def from_item(cls, x, *a, **kw):
        return x.merge_general(*a, **kw) if isinstance(x, cls) else cls(x, *a, **kw)

    @classmethod
    def from_items(cls, items, *a, **kw):
        return [cls.from_item(x, *a, **kw) for x in items]

    def merge_general(self, *a, **kw):
        return args(*self.a, *a, **dict(kw, **self.kw))


def maybe_call(fn, *a, **kw):
    """Call the value if it is callable. Otherwise, return it."""
    return fn(*a, **kw) if callable(fn) else fn


def try_len(it, default=None):
    """Try to get the length of an object, returning a default value if it fails."""
    if it is None:
        return default
    if isinstance(it, int):
        return it
    try:
        return len(it)
    except TypeError:
        pass

    try:
        x = type(it).__length_hint__(it)
        return x if isinstance(x, int) else default
    except (AttributeError, TypeError):
        return default

# ---------------------------------------------------------------------------- #
#                         Concurrent Futures Executors                         #
# ---------------------------------------------------------------------------- #

class SequentialFuture(Future):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._evaluated = False
        with self._condition:  # so as_completed will return it
            self._state = FINISHED

    def _evaluate(self):
        if not self._evaluated:
            with self._condition:
                self._state = RUNNING
            try:
                self.set_result(self._fn(*self._args, **self._kwargs))
            except Exception as exc:
                self.set_exception(exc)
            self._evaluated = True

    def result(self, timeout=None):
        self._evaluate()
        return super().result(timeout)
    
    def exception(self, timeout=None):
        self._evaluate()
        return super().exception(timeout)


class SequentialExecutor(Executor):
    def __init__(self, max_workers=None, initializer=None, initargs=()):
        super().__init__()
        self._initializer = initializer
        self._initargs = initargs

    def __enter__(self):
        if self._initializer is not None:
            self._initializer(*self._initargs)
        return super().__enter__()

    def submit(self, fn, *args, **kwargs):
        return SequentialFuture(fn, *args, **kwargs)


import threading
_thread_local_data = threading.local()
def pbar_initializer(pbar, defaults=None):
    """Initialize the progress bar for the worker thread/process."""
    if pbar is not None:
        M.pbar = pbar
    _thread_local_data.defaults = defaults or {}

def _get_local(key, default=None):
    """Get a thread-local variable."""
    return getattr(_thread_local_data, key, default)

# def _pbar_initializer(pbar, parent_task_id):
#     """Initialize the progress bar for the worker thread/process."""
#     M.pbar = pbar
#     _thread_local_data.parent_task_id = parent_task_id

T_POOL_MODE = Literal['process', 'thread', 'sequential', None]
POOL_EXECUTORS = {
    'thread': ThreadPoolExecutor,
    'process': ProcessPoolExecutor,
    'sequential': SequentialExecutor,
    None: SequentialExecutor,
}

def executor(pool_mode: T_POOL_MODE='process', bar_kw: dict=None, **kw) -> Executor:
    """Return the appropriate executor for the pool mode of the progress bar."""
    pbar = M._get_pbar(pool_mode=pool_mode)
    return POOL_EXECUTORS[pool_mode](initializer=pbar_initializer, initargs=[pbar, bar_kw or {}], **kw)


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
    prompt_suffix = '\033[F'


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


# ---------------------------------------------------------------------------- #
#                         Custom Progress Column Types                         #
# ---------------------------------------------------------------------------- #


class MofNColumn(progress.DownloadColumn):
    '''A progress column that shows the current vs. total count of items.'''
    def __init__(self, bytes=False, separator="/", **kw):
        self.bytes = bytes
        self.separator = separator
        super().__init__(**kw)

    def render(self, task):
        if self.bytes:
            return super().render(task)
        total = f'{int(task.total):,}' if task.total is not None else "?"
        return progress.Text(
            f"{int(task.completed):,d}{self.separator}{total}",
            style="progress.download",
            justify='right'
        )


class SpeedColumn(progress.TransferSpeedColumn):
    """Renders human readable transfer speed."""
    def __init__(self, bytes=False, unit_scale=1, **kw):
        self.bytes = bytes
        self.unit_scale = unit_scale
        super().__init__(**kw)

    def render(self, task):
        """Show data transfer speed."""
        if self.bytes:
            return super().render(task)
        speed = task.finished_speed or task.speed
        if speed is None:
            return progress.Text("", style="progress.data.speed")
        end = 'x/s'
        if speed < 1:
            speed = 1 / speed
            end = 's/x'
        unit, suffix = progress.filesize.pick_unit_and_suffix(
            int(speed), ["", "×10³", "×10⁶", "×10⁹", "×10¹²"], 1000)
        return progress.Text(f"{speed/unit:.1f}{suffix}{end}", justify='right', style="progress.data.speed")


class TimeElapsedColumn(progress.TimeRemainingColumn):
    """Renders time elapsed."""
    def __init__(self, compact: bool = False, **kw):
        self._compact = compact
        super().__init__(**kw)

    def render(self, task):
        """Show time elapsed."""
        elapsed = task.finished_time if task.finished else task.elapsed
        if elapsed is None:
            return progress.Text("--:--" if self._compact else "-:--:--", style="progress.elapsed")
        minutes, seconds = divmod(int(elapsed), 60)
        hours, minutes = divmod(minutes, 60)
        return progress.Text(
            (f"{hours:d}:" if hours or not self._compact else "") + 
            f"{minutes:02d}:{seconds:02d}", style="progress.elapsed")

# class LogBarColumn(progress.BarColumn):
#     def render(self, task):
#         return progress.Group(
#             super().render(task),
#             progress.Text(task.description, style="progress.description"),
#         )


from rich.file_proxy import FileProxy
class _RedirectIO:
    def __init__(self, console: rich.console.Console, redirect_stdout: bool = True, redirect_stderr: bool = True):
        self.console_compatible = console.is_terminal or console.is_jupyter
        self._redirect_stdout = redirect_stdout
        self._redirect_stderr = redirect_stderr
        self._restore_stdout: Optional[IO[str]] = None
        self._restore_stderr: Optional[IO[str]] = None

    def __enter__(self):
        self.enable()
        return self
    
    def __exit__(self, *exc):
        self.disable()

    def __del__(self):
        self.disable()

    def enable(self) -> None:
        """Enable redirecting of stdout / stderr."""
        if self.console_compatible:
            if self._redirect_stdout and not isinstance(sys.stdout, FileProxy):
                self._restore_stdout = sys.stdout
                sys.stdout = cast("TextIO", FileProxy(self.console, sys.stdout))
            if self._redirect_stderr and not isinstance(sys.stderr, FileProxy):
                self._restore_stderr = sys.stderr
                sys.stderr = cast("TextIO", FileProxy(self.console, sys.stderr))

    def disable(self) -> None:
        """Disable redirecting of stdout / stderr."""
        if self._restore_stdout:
            sys.stdout = cast("TextIO", self._restore_stdout)
            self._restore_stdout = None
        if self._restore_stderr:
            sys.stderr = cast("TextIO", self._restore_stderr)
            self._restore_stderr = None