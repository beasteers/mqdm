import os
import time
from time import monotonic
import multiprocessing as mp
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
        args=', '.join([f'\n  {x!r}' for x in self.a] + [f'\n  {k}={v!r}' for k, v in self.kw.items()])
        args = args + '\n' if args else ''
        return f"({args})"

    def __getitem__(self, i):
        return self.a[i] if isinstance(i, int) else self.kw[i]

    def __call__(self, fn, *a, **kw):
        return fn(*self.a, *a, **dict(self.kw, **kw))

    @classmethod
    def from_item(cls, x, *a, **kw):
        return cls(*(x.a + a), **{**x.kw, **kw}) if isinstance(x, cls) else cls(x, *a, **kw)

    @classmethod
    def from_items(cls, items, *a, **kw):
        return [cls.from_item(x, *a, **kw) for x in items]
    
    @classmethod
    def from_tuples(cls, items, *a, **kw):
        return [cls.from_item(*x, *a, **kw) for x in items]
    
class fn(args):
    def __init__(self, func, *a, **kw):
        if isinstance(func, args):
            a = func.a + a
            kw = {**func.kw, **kw}
            func = func.fn
        assert callable(func), "fn's first argument must be a callable function."
        self.fn = func
        super().__init__(*a, **kw)

    def __call__(self, *a, **kw):
        return self.fn(*self.a, *a, **dict(self.kw, **kw))


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


class fopen:
    """Open a file with a progress bar."""
    def __init__(self, fname: os.PathLike, mode='r', pbar: 'M.mqdm'=None, **kw):
        self.total = os.path.getsize(fname)
        self.fd = open(fname, mode)
        self._tell = self.fd.tell if 'b' in mode else self.fd.buffer.tell
        self._pos = self._tell()
        if pbar is None:
            kw.setdefault('desc', os.path.basename(fname))
            pbar = M.mqdm(bytes=True, **kw)
        self.pbar = pbar
        self._pbar_managed = not pbar.entered
        pbar.set(total=self.total)
        
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
        try:
            line = next(self.fd)
        except StopIteration:
            self.pbar.fast_advance(n=0, flush=True, wait=False)
            raise
        pos = self._tell()
        self.pbar.fast_advance(n=pos - self._pos)
        self._pos = pos
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


def fn_throttle(fn, seconds):
    """Limit the rate of a function call."""
    if seconds is None:
        return fn
    next_call_time = 0
    def wrapper(*a, **kw):
        nonlocal next_call_time
        now = monotonic()
        if now >= next_call_time:
            next_call_time = now + seconds
            fn(*a, **kw)

    return wrapper


class noopcontext:
    """A no-op context manager."""
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass
