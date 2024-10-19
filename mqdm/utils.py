import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import rich
from rich import progress


POOL_EXECUTORS = {
    'thread': ThreadPoolExecutor,
    'process': ProcessPoolExecutor,
}

def is_main_process():
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
    return fn(*a, **kw) if callable(fn) else fn


def try_len(it, default=None):
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