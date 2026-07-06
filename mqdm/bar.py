''''''
import time
import sys
from . import T_POOL_MODE
from . import utils
from .executor import _get_local
import mqdm as M


class mqdm:
    """Create a progress bar for an iterable. (tqdm-like interface)
        
        Args:
            iter (Iterable): The iterable to iterate over.
            desc (str): The description of the progress bar.
            bytes (bool): Whether to show bytes transferred.
            pbar (rich.progress.Progress): An existing progress bar to use.
            leave (bool): Whether to keep/remove the progress bar after completion.
            disable (bool): Whether to disable the progress bar.
            **kw: Additional keyword arguments to pass to the progress bar.
        """
    # Local mirrors stay valid even when disabled or detached from a live task.
    task_id = None           # stable task identity
    pbar = None              # the progress bar instance
    _desc = None             # the description of the progress bar
    _total = None            # the total number of items to iterate over
    _n = 0                   # the number of items completed
    _iter = None             # the item iterator
    entered = False          # whether the progress bar has called __enter__()
    started = False          # whether the progress bar has beed started (for lazy start)
    _task_dict = None        # detached serialized task state
    get_desc = None          # a function to get the description
    disable = False          # whether to disable the progress bar
    runtime = None           # runtime that owns this bar's state

    def __init__(
            self, 
            it=None, desc=None, *, 

            # mqdm arguments
            pool_mode=None, 
            runtime=None,
            disable=None, 
            # miniters=None, 
            fast_fps_delta=0.05, 
            task_id=None, 

            # progress bar arguments
            progress_kw=None, 
            auto_refresh: bool = True,
            refresh_per_second: float = 8,
            speed_estimate_period: float = 60.0,
            redirect_stdout: bool = True,
            redirect_stderr: bool = True,
            expand: bool = False,

            # rich task arguments
            init_kw=None, 
            start: bool = True,
            total: float|None = None,
            # leave: bool = True,
            # transient: bool = False,
            completed: int = 0,
            visible: bool = True,
            # refresh: bool = False,
            bytes: bool = False,
            **fields,
        ):
        if isinstance(it, str) and desc is None:  # infer string as description
            it, desc = None, it

        self._init_runtime(
            runtime=runtime,
            disable=disable,
            fast_fps_delta=fast_fps_delta,
            progress_kw=progress_kw,
            auto_refresh=auto_refresh,
            refresh_per_second=refresh_per_second,
            speed_estimate_period=speed_estimate_period,
            redirect_stdout=redirect_stdout,
            redirect_stderr=redirect_stderr,
            expand=expand,
        )

        start, bind_kw = self._init_task(
            pool_mode=pool_mode,
            task_id=task_id,
            start=start,
            desc=desc,
            total=total,
            init_kw=init_kw,
            completed=completed,
            visible=visible,
            bytes=bytes,
            **fields,
        )
        self.started = start

        self(it, desc=..., **bind_kw)  # bind iterable and update progress bar

    def _init_runtime(
            self, *,
            runtime,
            disable,
            fast_fps_delta,
            progress_kw,
            auto_refresh,
            refresh_per_second,
            speed_estimate_period,
            redirect_stdout,
            redirect_stderr,
            expand):
        self.runtime = runtime or _get_local('runtime', M._current_runtime())
        self.disable = self.disable if disable is None else disable
        self.fast_advance = _speed_increment(delta=fast_fps_delta, disable=self.disable, runtime=self.runtime)
        self._progress_kw = {
            **(progress_kw or {}),
            "auto_refresh": auto_refresh,
            "refresh_per_second": refresh_per_second,
            "speed_estimate_period": speed_estimate_period,
            "redirect_stdout": redirect_stdout,
            "redirect_stderr": redirect_stderr,
            "expand": expand,
        }

    def _init_task(
            self, *,
            pool_mode,
            task_id,
            start,
            desc,
            total,
            init_kw,
            completed,
            visible,
            bytes,
            **fields):
        bind_kw = {}
        init_kw = self._process_args(initial=True, **{
            **_get_local('defaults', {}), 
            **(init_kw or {}),
            'description': desc,
            'start': start,
            'total': total,
            'completed': completed,
            'visible': visible,
            'bytes': bytes,
            **fields,
        })

        if self.disable:
            if task_id is None:
                self.task_id = None
            elif isinstance(task_id, dict):
                self._task_dict = task_id
                self.task_id = task_id['id']
                self._n = task_id.get('completed', 0)
                self._total = task_id.get('total')
                self._desc = task_id.get('description')
                start = bool(task_id.get('start_time', start))
            else:
                self.task_id = task_id
            self.fast_advance.task_id = self.task_id
            return start, bind_kw

        pbar = self.runtime.get_pbar(pool_mode=pool_mode, **self._progress_kw)
        self.runtime.add_instance(self)

        if task_id is None:
            start = self._init_new_task(pbar, init_kw, start)
        else:
            start, bind_kw = self._init_existing_task(pbar, task_id, init_kw, start)

        self.fast_advance.task_id = self.task_id
        return start, bind_kw

    def _init_new_task(self, pbar, init_kw, start):
        init_kw.setdefault('total', self._total)
        init_kw.setdefault('description', '')
        self.task_id = pbar.add_task(**init_kw)
        return start

    def _init_existing_task(self, pbar, task_id, init_kw, start):
        bind_kw = {}
        if isinstance(task_id, dict):
            self._task_dict = task_dict = task_id
            task_id = task_id['id']
        else:
            bind_kw = init_kw
            try:
                task_dict = pbar.dump_task(task_id) or {}
            except KeyError:
                task_dict = {}

        self.task_id = task_id
        self._n = task_dict.get('completed', 0)
        self._total = task_dict.get('total')
        self._desc = task_dict.get('description')
        start = bool(task_dict.get('start_time', start))
        return start, bind_kw

    # ------------------------------ Dunder methods ------------------------------ #

    def __repr__(self) -> str:
        return f'<mqdm[{self.task_id}]({self._n}/{self._total}, {self._desc or ""!r})>'

    def __getstate__(self):
        state = self.__dict__.copy()
        state['get_desc'] = None  # cannot pickle lambda functions
        # state['_items'] = None  # cannot pickle iterators
        state['_iter'] = None  # cannot pickle iterators
        return state

    # def __getitem__(self, i: int):
    #     """Get an item at index."""
    #     return self._items[i]
    
    # def __bool__(self) -> bool:
    #     return self._total is None or self._total

    def __len__(self) -> int:
        """Get the total number of items."""
        return self._total or 0

    def __iter__(self) -> 'mqdm':
        return self

    def __next__(self):
        return next(self._iter)
    
    # ----------------------------- Lifecycle methods ---------------------------- #
    
    def __enter__(self) -> 'mqdm':
        self.entered = True
        return self.open()

    def __exit__(self, t, e, tb):
        self.entered = False
        self.close()
        pbar = self.runtime.pbar
        if isinstance(e, KeyboardInterrupt) and pbar is not None:
            pbar.stop()

    def __del__(self):
        try:
            if sys.meta_path is None:
                return 
            self.close()
        except (ImportError, BrokenPipeError, FileNotFoundError) as e:
            pass

    # ----------------------------- Iteration methods ---------------------------- #

    def _get_iter(self, iter, **kw):
        i = x = ...
        try:
            fast_advance = self.fast_advance
            it = enumerate(iter)
            i, x = next(it)
            self.runtime.ttl_pause_wait()
            self._n += 1
            fast_advance(0, arg=x, i=i, flush=True)
            yield x
            for i, x in it:
                self.runtime.ttl_pause_wait()
                self._n += 1
                fast_advance(1, arg=x, i=i)
                yield x
            # self._n += 1
            fast_advance(1, flush=True)
        except StopIteration:
            pass
        finally:
            fast_advance(0, flush=True)

    def __call__(self, iter, desc=None, total=None, **kw) -> 'mqdm':
        """Iterate over an iterable with a progress bar."""
        if isinstance(iter, str) and desc is None:  # infer string as description
            iter, desc = None, iter
        if iter is None:  # no iterable yet
            if total is not None:
                kw['total'] = total
            if desc not in (None, ...):
                kw['description'] = desc
            return self.update(0, **kw)
        if isinstance(iter, int):  # implicit range
            iter = range(iter)

        total = utils.try_len(iter, self._total) if total is None else total
        self.update(0, total=total, description=desc, **kw)
        def _with_iter():
            if self.entered:  # already called __enter__, don't call __exit__() when leaving
                yield from self._get_iter(iter, **kw)
                return
            with self:  # call __enter__() and __exit__()
                yield from self._get_iter(iter, **kw)
        # self._items = iter
        self._iter = _with_iter()
        return self
    
    # ------------------------------ Internal methods ----------------------------- #

    def _attach(self):
        """Attach local state to a live runtime progress task."""
        if self.disable: return

        pbar = self.runtime.get_pbar(start=False, **self._progress_kw)
        self.runtime.add_instance(self)
        if self._task_dict is not None:
            pbar.load_task(self._task_dict)
            self._task_dict = None
        self.set(total=self._total)

    def _detach(self, remove=None, soft=False):
        """Detach from the live task while preserving local task state."""
        pbar = self.runtime.pbar
        if self.disable or pbar is None: return

        if self._task_dict is None:
            self._task_dict = pbar.pop_task(self.task_id, remove=remove)
        self.runtime.remove_instance(self)
        self.runtime.clear_pbar(strict=False, soft=soft)

    def _process_args(self, *, initial=False, append_total=None, arg=..., i: int=None, **kw) -> dict:
        """Normalize task fields and keep local mirrors in sync."""
        kw = {k: v for k, v in kw.items() if v is not ...}
        if 'leave' in kw:  # tqdm compatibility
            kw['transient'] = not kw.pop('leave')

        # get progress and total
        if 'total' in kw:  # keep local copy of total
            self._total = kw['total']
        if append_total:
            kw['total'] = self._total = (self._total or 0) + append_total
        if kw.get('advance'):
            kw['advance'] = int(kw['advance'])
            self._n += kw['advance']
        if kw.get('advance') == 0:
            kw.pop('advance')
        if kw.get('completed') is not None:
            self._n = kw['completed'] = int(kw['completed'])

        if 'desc' in kw:  # tqdm compatibility
            kw['description'] = kw.pop('desc')
        if 'description' in kw and callable(kw['description']):
            self.get_desc = kw.pop('description')
            self.fast_advance.get_desc = self.get_desc
        if not initial and kw.get('description') is None and self.get_desc is not None and arg is not ...:
            kw['description'] = self.get_desc(arg, i)
        if kw.get('description') is not None:
            self._desc = kw['description']
        if 'description' in kw and kw['description'] is None:  # ignore None descriptions
            kw.pop('description')

        return kw

    # --------------------------- tqdm-like attributes --------------------------- #

    @property
    def n(self) -> int:
        """The number of items completed."""
        return self._n
    
    @n.setter
    def n(self, n: int):
        """Set the number of items completed."""
        self.set(completed=n)

    @property
    def total(self) -> int|None:
        """The total number of items to iterate over."""
        return self._total
    
    @total.setter
    def total(self, total: int|None):
        """Set the total number of items to iterate over."""
        self.set(total=total)

    # ------------------------------ public methods ------------------------------ #

    def open(self):
        """Add the task to the progress bar."""
        self.entered = True
        self._attach()
        return self

    def close(self, remove=None):
        """Remove the task from the progress bar."""
        self.entered = False
        self._detach(remove=remove)
        return self

    def print(self, *a, **kw) -> 'mqdm':
        """Print above the progress bar."""
        self.runtime.print(*a, **kw)
        return self

    def set_description(self, desc) -> 'mqdm':
        """Set the description of the progress bar."""
        return self.update(0, description=desc)

    def update(self, advance: int=1, **kw) -> 'mqdm':
        """Increment the progress bar."""
        return self.set(advance=advance, **kw)

    def set(self, **kw) -> 'mqdm':
        """Update progress bar fields."""
        kw = self._process_args(**kw)
        if self.disable: return self

        # update progress bar
        if kw:
            self.runtime.pbar.update_(self.task_id, **kw)
        return self


class _speed_increment:
    """Increment the progress bar in a very fast loop.
    Saves time by reducing inter-process IO.
    """
    __slots__ = ('n', 'nc', 't', 'disable', 'delta', 'get_desc', 'task_id', 'runtime')
    def __init__(self, runtime, delta=0, disable=False):
        self.delta = delta
        self.n = self.t = 0
        self.nc = ...
        self.get_desc = None
        self.task_id = None
        self.runtime = runtime
        self.disable = disable

    def flush(self):
        return self(0, flush=True)

    def __call__(self, n: int=1, completed: int=..., arg=..., i=..., flush=False):
        if self.disable:
            return
        
        if completed is not ...:
            self.nc = completed
            self.n = n = 0

        delta = self.delta
        if delta:
            # If the time since the last increment is less than some delta, increment a local counter
            # The only time this fails is if the iterations are highly irregular 
            # (e.g. a bunch of 1000fps followed by a 100 second iteration
            #       - could happen with overwrite=False type scenarios)
            t = time.time()
            last_t = self.t
            n0 = self.n
            n += n0
            if t - last_t < delta and not flush:
                self.n = n
                return

        pbar = self.runtime.pbar
        if pbar is None:
            return
        
        kw = {}
        if i is not ...:
            get_desc = self.get_desc
            if get_desc is not None:
                desc = get_desc(arg, i)
                if desc is not None:
                    kw['description'] = desc

        if self.nc is not ...:
            pbar.update(self.task_id, completed=self.nc + n, **kw)
        elif n:
            pbar.update(self.task_id, advance=n, **kw)

        if delta:
            # if n0:
            self.n = 0
            self.nc = ...
            self.t = t
