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
    from .executor import T_POOL_MODE
    from .backend import ProgressBackend


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
    """Wrap an iterable or manual task with an mqdm progress bar.

    The interface is intentionally close to ``tqdm`` while using Rich for
    rendering and mqdm's runtime model for worker-safe output.

    Args:
        it: Iterable to wrap. If an ``int`` is provided, it is treated as
            ``range(it)``.
        desc: Static description or per-item description callback.
        pool_mode: Optional worker mode hint used when binding to pooled work.
        runtime: Runtime that should own this bar. Defaults to the current
            runtime.
        disable: Whether rendering should be disabled while counters continue to
            update.
        task_id: Existing task identifier or detached task state to restore.
        task_kw: Extra keyword arguments for the initial task creation.
        start: Whether the task should start immediately.
        total: Optional total item count.
        completed: Initial completed count.
        visible: Whether the task should be visible.
        bytes: Whether to render byte-oriented columns.
        **fields: Additional task fields forwarded to Rich.
    """
    # internal state
    _n: int = 0                       # the number of items completed
    _iter: Iterator[T] | None = None  # the item iterator
    _total: float | None = None       # the total number of items to iterate over
    _desc: str | None = None          # the description of the progress bar

    # lifecycle state
    disable: bool = False             # whether to disable the progress bar
    entered: bool = False             # whether the progress bar has called __enter__()
    started: bool = False             # whether the progress bar has beed started (for lazy start)
    
    # task state
    task_id: TaskId | None = None     # stable task identity
    _task_dict: TaskState | None = None  # detached serialized task state

    # methods
    get_desc: DescFunc[T] | None = None  # a function to get the description
    fast_advance: Callable[..., None] | None = None  # a function to update the progress bar in fast loops
    runtime: Runtime                  # runtime that owns this bar's state

    def __init__(
            self, 
            it: Iterable[T] | int | str | None=None, 
            desc: str | DescFunc[T] | None=None, 
            *, 

            # mqdm arguments
            pool_mode: T_POOL_MODE=None,
            disable: bool | None=None,
            runtime: Runtime | None=None,
            task_id: TaskId | TaskState | None=None,

            # rich task arguments
            task_kw: dict[str, Any] | None=None,
            completed: int = 0,
            total: float|None = None,
            start: bool = True,
            visible: bool = True,
            bytes: bool = False,
            # leave: bool = True,
            # transient: bool = False,
            # refresh: bool = False,
            **fields: Any,
        ) -> None:
        if isinstance(it, str) and desc is None:  # infer string as description
            it, desc = None, it

        self._init_runtime(
            runtime=runtime,
            disable=disable,
        )

        bind_kw = self._init_task(
            pool_mode=pool_mode,
            task_id=task_id,
            start=start,
            task_kw={
                **(task_kw or {}),
                'total': total,
                'completed': completed,
                'description': desc,
                'visible': visible,
                'bytes': bytes,
                **fields,
            },
        )
        self._reset_fast_advance()

        self(it, desc=..., **bind_kw)  # bind iterable and update progress bar

    def _init_runtime(
            self, *,
            runtime: Runtime | None,
            disable: bool | None) -> None:
        self.runtime = runtime or M._current_runtime()
        self.disable = self.disable if disable is None else disable

    def _init_task(
            self, *,
            pool_mode,
            task_id: TaskId | TaskState | None,
            task_kw: dict[str, Any] | None,
            start: bool,
    ) -> dict[str, Any]:
        bind_kw: dict[str, Any] = {}
        task_kw = self._process_args(initial=True, **{
            **_get_local('defaults', {}), 
            **task_kw,
        })

        if self.disable:
            self._init_disabled(task_id, start)
            return bind_kw

        pbar = self.runtime.get_pbar(pool_mode=pool_mode)
        if start:
            pbar.start()
        self.runtime.add_instance(self)

        if task_id is None:
            self._init_new_task(pbar, task_kw, start)
        else:
            bind_kw = self._init_existing_task(pbar, task_id, task_kw, start)

        return bind_kw

    def _init_disabled(self, task_id: TaskId | TaskState | None, start: bool) -> None:
        if isinstance(task_id, dict):
            self._task_dict = task_id
            self._init_state_from_task_dict(task_id.get('id'), task_id, start=start)
            return

        self.task_id = task_id
        self.started = start

    def _init_new_task(self, pbar: ProgressBackend, task_kw: dict[str, Any], start: bool) -> None:
        task_kw.setdefault('total', self._total)
        task_kw.setdefault('description', '')
        self.task_id = pbar.add_task(**task_kw)
        self.started = start

    def _init_existing_task(
        self,
        pbar: ProgressBackend,
        task_id: TaskId | TaskState,
        task_kw: dict[str, Any],
        start: bool,
    ) -> dict[str, Any]:
        bind_kw: dict[str, Any] = {}
        if isinstance(task_id, dict):
            self._task_dict = task_dict = task_id
            task_id = task_id['id']
        else:
            bind_kw = task_kw
            try:
                task_dict = pbar.dump_task(task_id) or {}
            except KeyError:
                task_dict = {}

        self._init_state_from_task_dict(task_id, task_dict, start=start)
        return bind_kw
    
    def _init_state_from_task_dict(self, task_id, task_dict: TaskState, start: bool=False) -> None:
        self.task_id = task_id or task_dict.get('id')
        self._n = task_dict.get('completed', 0)
        self._total = task_dict.get('total')
        self._desc = task_dict.get('description')
        self.started = bool(task_dict.get('start_time', start))

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
        except Exception:
            pass

    # ----------------------------- Iteration methods ---------------------------- #

    def _get_fast_advance(self) -> Callable[..., None]:
        D: dict[str, Any] = self.__dict__
        disable = self.disable
        ttl_pause_wait = utils.fn_throttle(self.runtime.pause_event.wait, self.runtime.pause_wait_ttl_seconds)
        delta = 1 / (self.runtime.progress_options.get('refresh_per_second') or 8)
        runtime = self.runtime
        task_id = self.task_id

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
                get_desc = self.get_desc
                pbar.try_update(
                    task_id, advance=n_acc, 
                    description=get_desc(x, D['_n']-1) if x is not ... and get_desc is not None else None
                )
                if wait:
                    ttl_pause_wait()
            else:
                task = self._task_dict
                if task is not None:
                    task['completed'] = D['_n']
                    get_desc = self.get_desc
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
            x: T | object = ...
            for x in it:
                yield x
                update(x, 1)
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
            return self.set(**kw)
        elif isinstance(iter, int):  # implicit range
            iter = range(iter)

        total = utils.try_len(iter, self._total) if total is None else total
        self.update(0, total=total, description=desc, **kw)
        self._iter = self._get_iter(iter)
        return self
    
    # ------------------------------ Internal methods ----------------------------- #

    def _attach(self) -> None:
        """Attach local state to a live runtime progress task."""
        if self.disable: return

        pbar = self.runtime.get_pbar()
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
        arg: T | object=...,
        i: int | None=None,
        **kw: Any,
    ) -> dict[str, Any]:
        """Normalize task fields and keep local mirrors in sync."""
        kw = self._normalize_aliases(kw)
        kw = self._resolve_description(kw, initial=initial, arg=arg, i=i)
        kw = self._apply_local_state(kw)
        return kw
    
    def _normalize_aliases(self, kw: dict[str, Any]) -> dict[str, Any]:
        kw = {k: v for k, v in kw.items() if v is not ...}

        if "desc" in kw:
            kw["description"] = kw.pop("desc")
        if "leave" in kw:
            kw["transient"] = not kw.pop("leave")
        return kw
    
    def _resolve_description(self, kw: dict[str, Any], *, initial: bool=False, arg: T | object=..., i: int | None=None) -> tuple[dict[str, Any], bool]:
        if "description" in kw and callable(kw["description"]):
            self.get_desc = kw.pop("description")
            
        if not initial and kw.get("description") is None and self.get_desc is not None and arg is not ...:
            kw["description"] = self.get_desc(arg, i)
        if kw.get("description") is None:
            kw.pop("description", None)
        return kw
    
    def _apply_local_state(self, kw: dict[str, Any], reset_fast_advance: bool=False) -> dict[str, Any]:
        if "total" in kw:
            self._total = kw["total"]

        if kw.get("advance") is not None:
            kw["advance"] = advance = int(kw["advance"])
            self._n += advance
            if advance == 0:
                kw.pop("advance")

        if kw.get("completed") is not None:
            self._n = kw["completed"] = int(kw["completed"])

        if kw.get("description") is not None:
            self._desc = kw["description"]

        if reset_fast_advance and self.fast_advance is not None:
            self._reset_fast_advance()

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
            pbar.try_update(self.task_id, **kw)
            return self
        if self._task_dict is not None:
            self._set_task_dict(kw)
            return self
        raise RuntimeError("Cannot update mqdm bar without an attached progress bar or detached task state.")
