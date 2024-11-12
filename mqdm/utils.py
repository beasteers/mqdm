import os
import time
import multiprocessing as mp
from rich import progress
import mqdm as M

# ---------------------------------------------------------------------------- #
#                                     Utils                                    #
# ---------------------------------------------------------------------------- #


def is_main_process():
    """Check if the current process is the main process."""
    return mp.current_process().name == 'MainProcess'

def process_name():
    """Get the name of the current process."""
    return mp.current_process().name

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

    def __repr__(self):
        args=', '.join([f'{x!r}' for x in self.a] + [f'{k}={v!r}' for k, v in self.kw.items()])
        return f"args({args})"

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
#                         Custom Progress Column Types                         #
# ---------------------------------------------------------------------------- #


class MofNColumn(progress.DownloadColumn):
    '''A progress column that shows the current vs. total count of items.'''
    def __init__(self, bytes=False, separator="/", **kw):
        self.bytes = bytes
        self.separator = separator
        super().__init__(**kw)

    def render(self, task):
        bytes = task.fields.get("bytes", self.bytes)
        if bytes:
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
        bytes = task.fields.get("bytes", self.bytes)
        if bytes:
            return super().render(task)
        speed = task.finished_speed or task.speed
        if speed is None:
            return progress.Text(f"{speed}", style="progress.data.speed")
        end = '/s'
        if 0 < speed < 1:
            speed = 1 / speed
            speed, suffix = time_units(speed)
            end = '/x'
            return progress.Text(f"{speed:.1f}{suffix}{end}", justify='right', style="progress.data.speed")
        unit, suffix = progress.filesize.pick_unit_and_suffix(
            int(speed), 
            ["x", "K", "M", "B", "T"], 
            # ["", "×10³", "×10⁶", "×10⁹", "×10¹²"], 
            1000)
        return progress.Text(f"{speed/unit:.1f}{suffix}{end}", justify='right', style="progress.data.speed")

def time_units(seconds):
    for d, u in [(60, 's'), (60, 'm'), (24, 'h'), (365, 'd')]:
        if seconds < d:
            return seconds, u
        seconds /= d
    return seconds, 'y'


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



class fopen:
    """Open a file with a progress bar."""
    def __init__(self, fname: os.PathLike, mode='r', pbar: 'M.mqdm'=None, **kw):
        self.total = os.path.getsize(fname)
        self.fd = open(fname, mode)
        if pbar is None:
            kw.setdefault('desc', os.path.basename(fname))
            pbar = M.mqdm(init_kw={'bytes': True}, **kw)
        self.pbar = pbar
        self._pbar_managed = not pbar.entered
        pbar.update(total=self.total)
        
    def __enter__(self):
        self.fd.__enter__()
        if self._pbar_managed:
            self.pbar.__enter__()
        return self
    
    def __exit__(self, *args):
        self.fd.__exit__(*args)
        if self._pbar_managed:
            self.pbar.__exit__(*args)

    def __iter__(self):
        return self

    def __next__(self):
        line = next(self.fd)
        self.pbar.fast_advance(len(line))
        return line

    def __getattr__(self, name):
        return getattr(self.fd, name)
    
    def set(self, **kw):
        self.pbar.set(**kw)
        return self
    
    def set_description(self, desc):
        self.pbar.set_description(desc)
        return self


def ratelimit(iter, seconds):
    """Limit the rate of an iterator."""
    if seconds is None:
        return iter
    lag = 0
    t0 = time.time()
    for x in iter:
        yield x
        t = time.time()
        dt = seconds - (t - t0) - lag
        if dt > 0:
            time.sleep(dt)
        lag = max(-dt, 0)
        t0 = t + max(0, dt)
