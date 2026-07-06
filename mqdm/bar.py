from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Iterator
from time import monotonic
from typing import TYPE_CHECKING, Any, Generic, TypeAlias, TypeVar, TypedDict

from .runtime import Runtime
from . import utils
from .executor import _get_local
import mqdm as M

if TYPE_CHECKING:
    from .runtime import ProgressLike


T = TypeVar('T')
TaskId: TypeAlias = int
DescFunc: TypeAlias = Callable[[T, int], str]


class TaskState(TypedDict, total=False):
    id: int
    description: str
    total: float | None
    completed: int
    visible: bool
    start_time: float | None
    fields: dict[str, Any]


class mqdm(Generic[T]):
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
    task_id: TaskId | None = None     # stable task identity
    pbar: ProgressLike | None = None  # the progress bar instance
    _desc: str | None = None          # the description of the progress bar
    _total: float | None = None       # the total number of items to iterate over
    _n: int = 0                       # the number of items completed
    _iter: Iterator[T] | None = None  # the item iterator
    entered: bool = False             # whether the progress bar has called __enter__()
    started: bool = False             # whether the progress bar has beed started (for lazy start)
    _task_dict: TaskState | None = None  # detached serialized task state
    get_desc: DescFunc[T] | None = None  # a function to get the description
    disable: bool = False             # whether to disable the progress bar
    runtime: Runtime                  # runtime that owns this bar's state
    fast_advance: Callable[..., None] | None = None  # a function to update the progress bar in fast loops

    def __init__(
            self, 
            it: Iterable[T] | int | str | None=None, desc: str | DescFunc[T] | None=None, *, 

            # mqdm arguments
            pool_mode=None,
            runtime: Runtime | None=None,
            disable: bool | None=None,
            # miniters=None, 
            fast_fps_delta: float | None=None, # deprecated, use refresh_per_second instead
            task_id: TaskId | TaskState | None=None,

            # progress bar arguments
            progress_kw: dict[str, Any] | None=None,
            auto_refresh: bool = True,
            refresh_per_second: float = 8,
            speed_estimate_period: float = 60.0,
            redirect_stdout: bool = True,
            redirect_stderr: bool = True,
            expand: bool = False,

            # rich task arguments
            init_kw: dict[str, Any] | None=None,
            start: bool = True,
            total: float|None = None,
            # leave: bool = True,
            # transient: bool = False,
            completed: int = 0,
            visible: bool = True,
            # refresh: bool = False,
            bytes: bool = False,
            **fields: Any,
        ) -> None:
        if isinstance(it, str) and desc is None:  # infer string as description
            it, desc = None, it

        self._init_runtime(
            runtime=runtime,
            disable=disable,
            fast_fps_delta=fast_fps_delta or (1/(refresh_per_second or 8)),
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
        self._reset_fast_advance()

        self(it, desc=..., **bind_kw)  # bind iterable and update progress bar

    def _init_runtime(
            self, *,
            runtime: Runtime | None,
            disable: bool | None,
            fast_fps_delta: float,
            progress_kw: dict[str, Any] | None,
            auto_refresh: bool,
            refresh_per_second: float,
            speed_estimate_period: float,
            redirect_stdout: bool,
            redirect_stderr: bool,
            expand: bool) -> None:
        self.runtime = runtime or _get_local('runtime', M._current_runtime())
        self.disable = self.disable if disable is None else disable
        self._progress_kw: dict[str, Any] = {
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
            task_id: TaskId | TaskState | None,
            start: bool,
            desc: str | DescFunc[T] | None,
            total: float | None,
            init_kw: dict[str, Any] | None,
            completed: int,
            visible: bool,
            bytes: bool,
            **fields: Any) -> tuple[bool, dict[str, Any]]:
        bind_kw: dict[str, Any] = {}
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
            return start, bind_kw

        pbar = self.runtime.get_pbar(pool_mode=pool_mode, **self._progress_kw)
        self.runtime.add_instance(self)

        if task_id is None:
            start = self._init_new_task(pbar, init_kw, start)
        else:
            start, bind_kw = self._init_existing_task(pbar, task_id, init_kw, start)

        return start, bind_kw

    def _init_new_task(self, pbar: ProgressLike, init_kw: dict[str, Any], start: bool) -> bool:
        init_kw.setdefault('total', self._total)
        init_kw.setdefault('description', '')
        self.task_id = pbar.add_task(**init_kw)
        return start

    def _init_existing_task(
        self,
        pbar: ProgressLike,
        task_id: TaskId | TaskState,
        init_kw: dict[str, Any],
        start: bool,
    ) -> tuple[bool, dict[str, Any]]:
        bind_kw: dict[str, Any] = {}
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
        state: dict[str, Any] = self.__dict__.copy()
        state['get_desc'] = None  # cannot pickle lambda functions
        state['fast_advance'] = None  # cannot pickle closures
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
        return int(self._total or 0)

    def __iter__(self) -> Iterator[T]:
        if self._iter is None:
            raise TypeError("mqdm object is not bound to an iterable.")
        return self._iter

    def __next__(self) -> T:
        if self._iter is None:
            raise TypeError("mqdm object is not bound to an iterable.")
        return next(self._iter)
    
    # ----------------------------- Lifecycle methods ---------------------------- #
    
    def __enter__(self) -> mqdm[T]:
        self.entered = True
        return self.open()

    def __exit__(self, t: object, e: BaseException | None, tb: object) -> None:
        self.entered = False
        self.close()
        pbar = self.runtime.pbar
        if isinstance(e, KeyboardInterrupt) and pbar is not None:
            pbar.stop()

    def __del__(self) -> None:
        try:
            if sys.meta_path is None:
                return 
            self.close()
        except (ImportError, BrokenPipeError, FileNotFoundError) as e:
            pass

    # ----------------------------- Iteration methods ---------------------------- #

    def _get_fast_advance(self) -> Callable[..., None]:
        D: dict[str, Any] = self.__dict__
        disable = self.disable
        ttl_pause_wait = utils.fn_throttle(self.runtime.pause_event.wait, self.runtime.pause_wait_ttl_seconds)
        delta = 1 / (self._progress_kw['refresh_per_second'] or 8)
        runtime = self.runtime
        task_id = self.task_id
        get_desc = self.get_desc

        def disabled_update(x: T | object=..., n: int=1, flush: bool=False, wait: bool=True) -> None:
            D['_n'] += n
            return

        n_acc = 0
        t_last = 0
        def update(x: T | object=..., n: int=1, flush: bool=False, wait: bool=True) -> None:
            nonlocal n_acc
            n_acc += n

            # If the time since the last increment is less than some delta, increment a local counter
            # The only time this fails is if the iterations are highly irregular 
            # (e.g. a bunch of 1000fps followed by a 100 second iteration
            #       - could happen with overwrite=False type scenarios)
            t = monotonic()
            if t - t_last >= delta or flush:
                do_flush(t, x, wait)

        def do_flush(t: float, x: T | object, wait: bool) -> None:
            nonlocal t_last, n_acc
            D['_n'] += n_acc

            pbar = runtime.pbar
            if pbar is not None:
                pbar.update_(
                    task_id, advance=n_acc, 
                    description=get_desc(x, D['_n']-1) if x is not ... and get_desc is not None else None
                )
                if wait:
                    ttl_pause_wait()
            else:
                task = self._task_dict
                if task is not None:
                    task['completed'] = D['_n']
                    if x is not ... and get_desc is not None:
                        task['description'] = get_desc(x, D['_n']-1)

            n_acc = 0
            t_last = t

        # return update
        return disabled_update if disable else update
    
    def _reset_fast_advance(self) -> Callable[..., None]:
        if self.fast_advance is not None:
            self.fast_advance(n=0, flush=True, wait=False)
        self.fast_advance = self._get_fast_advance()
        return self.fast_advance

    def _get_iter(self, it: Iterable[T]) -> Iterator[T]:
        with utils.noopcontext() if self.entered else self:
            update = self._reset_fast_advance()
            it = iter(it)
            try:
                x = next(it)
                update(x, 1, flush=True)
                yield x
            except StopIteration:
                update(..., 0, flush=True)
                return 

            for x in it:
                update(x, 1)
                yield x
            update(x, 0, flush=True)

    def __call__(
        self,
        iter: Iterable[T] | int | str | None,
        desc: str | DescFunc[T] | None=None,
        total: float | None=None,
        **kw: Any,
    ) -> mqdm[T]:
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
        self._iter = self._get_iter(iter)
        return self
    
    # ------------------------------ Internal methods ----------------------------- #

    def _attach(self) -> None:
        """Attach local state to a live runtime progress task."""
        if self.disable: return

        pbar = self.runtime.get_pbar(start=False, **self._progress_kw)
        self.runtime.add_instance(self)
        if self._task_dict is not None:
            pbar.load_task(self._task_dict)
            self._task_dict = None
        self.set(total=self._total)
        self._reset_fast_advance()

    def _detach(self, remove: bool | None=None, soft: bool=False) -> None:
        """Detach from the live task while preserving local task state."""
        pbar = self.runtime.pbar
        if self.disable or pbar is None: return

        if self.fast_advance is not None:
            self.fast_advance(n=0, flush=True, wait=False)
        if self._task_dict is None:
            self._task_dict = pbar.pop_task(self.task_id, remove=remove)
        self.runtime.remove_instance(self)
        self.runtime.clear_pbar(strict=False, soft=soft)

    def _set_task_dict(self, kw: dict[str, Any]) -> None:
        task = self._task_dict
        if task is None:
            return
        task['completed'] = self._n
        if 'total' in kw:
            task['total'] = kw['total']
        if 'description' in kw:
            task['description'] = kw['description']
        if 'visible' in kw:
            task['visible'] = kw['visible']

        fields = task.setdefault('fields', {})
        for key, value in kw.items():
            if key not in {'advance', 'completed', 'total', 'description', 'visible', 'refresh'}:
                fields[key] = value

    def _process_args(
        self,
        *,
        initial: bool=False,
        append_total: int | None=None,
        arg: T | object=...,
        i: int | None=None,
        **kw: Any,
    ) -> dict[str, Any]:
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
        return int(self._total) if self._total is not None else None
    
    @total.setter
    def total(self, total: int|None):
        """Set the total number of items to iterate over."""
        self.set(total=total)

    # ------------------------------ public methods ------------------------------ #

    def open(self) -> mqdm[T]:
        """Add the task to the progress bar."""
        self.entered = True
        self._attach()
        return self

    def close(self, remove: bool | None=None) -> mqdm[T]:
        """Remove the task from the progress bar."""
        self.entered = False
        self._detach(remove=remove)
        return self

    def print(self, *a: Any, **kw: Any) -> mqdm[T]:
        """Print above the progress bar."""
        self.runtime.print(*a, **kw)
        return self

    def set_description(self, desc: str) -> mqdm[T]:
        """Set the description of the progress bar."""
        return self.set(description=desc)

    def update(self, advance: int=1, **kw: Any) -> mqdm[T]:
        """Increment the progress bar."""
        return self.set(advance=advance, **kw)

    def set(self, **kw: Any) -> mqdm[T]:
        """Update progress bar fields."""
        kw = self._process_args(**kw)
        if self.disable: return self

        if not kw:
            return self

        pbar = self.runtime.pbar
        if pbar is not None:
            pbar.update_(self.task_id, **kw)
            return self
        if self._task_dict is not None:
            self._set_task_dict(kw)
            return self
        raise RuntimeError("Cannot update mqdm bar without an attached progress bar or detached task state.")
