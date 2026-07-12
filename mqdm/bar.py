from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterable, AsyncIterator, Callable, Iterable, Iterator
from time import monotonic
from typing import TYPE_CHECKING, Any, Generic, TypeAlias, TypeVar

from multiprocessing.managers import RemoteError

from .runtime import Runtime
from . import utils
from .parallel.executor import _get_local
from .utils.proxy import CommandTransportClosed
import mqdm as M

if TYPE_CHECKING:
    from .backend import ProgressBackend, TaskState

# Raised when the shared progress manager/proxy is already gone — e.g. a worker
# finalizing its bars as the pool shuts down after an error. Updates to it are
# best-effort at that point, so these are swallowed during teardown.
_BACKEND_GONE = (RemoteError, EOFError, OSError)
_BACKEND_CLOSED = _BACKEND_GONE + (CommandTransportClosed,)

# Globally disable mqdm using environment variable. 
DISABLED = (os.getenv("MQDM_DISABLED") or "").lower() in ("1", "true", "yes", "y")

DEFAULT_REFRESH_PER_SECOND = 8

T = TypeVar('T')
TaskId: TypeAlias = int
DescFunc: TypeAlias = Callable[[T, int], str]


class mqdm(Generic[T]):
    """Wrap an iterable or manual task with an mqdm progress bar.

    The interface is intentionally close to ``tqdm`` while using Rich for
    rendering and mqdm's runtime model for worker-safe output.

    Args:
        it: Iterable to wrap. If an ``int`` is provided, it is treated as
            ``range(it)``.
        desc: Static description or per-item description callback.
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

    Example:
        ```python
        # wrap any iterable
        for x in mqdm.mqdm(items, desc="processing"):
            ...

        # an int is treated as range(n); a lone string is the description
        for i in mqdm.mqdm(100):
            ...

        # no iterable: a manual bar you drive yourself
        with mqdm.mqdm(total=len(items), desc="processing") as bar:
            for x in items:
                ...
                bar.advance()
        ```
    """
    # internal state
    _n: int = 0                       # the number of items completed
    _iter: Iterator[T] | None = None  # the item iterator
    _aiter: AsyncIterator[T] | None = None  # the async item iterator
    _total: float | None = None       # the total number of items to iterate over
    _desc: str | None = None          # the description of the progress bar

    # lifecycle state
    disable: bool = DISABLED          # whether to disable the progress bar
    entered: bool = False             # whether the progress bar has called __enter__()
    started: bool = False             # whether the progress bar has beed started (for lazy start)
    
    # task state
    task_id: TaskId | None = None     # stable task identity
    _task_dict: TaskState | None = None  # detached serialized task state

    # methods
    get_desc: DescFunc[T] | None = None  # a function to get the description
    _fast_advance: Callable[..., None] | None = None  # a function to update the progress bar in fast loops
    runtime: Runtime                  # runtime that owns this bar's state

    def __init__(
            self, 
            it: Iterable[T] | int | str | None=None, 
            desc: str | DescFunc[T] | None=None, 
            *, 

            # mqdm arguments
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

        pbar = self.runtime.get_pbar()
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
        state['_fast_advance'] = None  # cannot pickle closures
        # state['_items'] = None  # cannot pickle iterators
        state['_iter'] = None  # cannot pickle iterators
        state['_aiter'] = None  # cannot pickle async iterators
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
        """Iterate the bound iterable, advancing the bar per item (``for x in bar``).

        The bar must be bound to a sync iterable (via ``mqdm(it)`` or ``bar(it)``);
        iterating one bound to an async iterable raises — use ``async for`` instead.

        Example:
            ```python
            for x in mqdm.mqdm(items, desc="processing"):
                ...
            ```
        """
        _iter = self._iter
        if _iter is None:
            if self._aiter is not None:
                raise TypeError("mqdm object is bound to an async iterable; use 'async for'.")
            raise TypeError("mqdm object is not bound to an iterable.")
        return _iter

    def __next__(self) -> T:
        _iter = self._iter
        if _iter is None:
            if self._aiter is not None:
                raise TypeError("mqdm object is bound to an async iterable; use 'async for'.")
            raise TypeError("mqdm object is not bound to an iterable.")
        return next(_iter)

    def __aiter__(self) -> AsyncIterator[T]:
        """Async-iterate the bound async iterable, advancing per item (``async for x in bar``).

        The bar must be bound to an async iterable; using ``async for`` on a
        sync-bound bar raises — use a plain ``for`` instead.

        Example:
            ```python
            async for x in mqdm.mqdm(aiter_source(), desc="streaming"):
                ...
            ```
        """
        _aiter = self._aiter
        if _aiter is None:
            if self._iter is not None:
                raise TypeError("mqdm object is bound to a sync iterable; use 'for'.")
            raise TypeError("mqdm object is not bound to an async iterable.")
        return _aiter
    
    async def __anext__(self) -> T:
        _aiter = self._aiter
        if _aiter is None:
            if self._iter is not None:
                raise TypeError("mqdm object is bound to a sync iterable; use 'for'.")
            raise TypeError("mqdm object is not bound to an async iterable.")
        return await _aiter.__anext__()
    
    # ----------------------------- Lifecycle methods ---------------------------- #
    
    def __enter__(self) -> mqdm[T]:
        """Open the bar as a context manager, attaching it to the live display.

        Example:
            ```python
            with mqdm.mqdm(total=len(items), desc="processing") as bar:
                for x in items:
                    ...
                    bar.advance()
            ```
        """
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
        delta = 1 / (self.runtime.backend_options.get('refresh_per_second') or DEFAULT_REFRESH_PER_SECOND)
        runtime = self.runtime
        task_id = self.task_id

        def disabled_update(n: int=1, arg: T | object=..., flush: bool=False, wait: bool=True) -> None:
            D['_n'] += n
            return

        n_acc = 0
        t_last = 0
        def update(n: int=1, arg: T | object=..., flush: bool=False, wait: bool=True) -> None:
            nonlocal n_acc
            n_acc += n

            # If the time since the last increment is less than some delta, increment a local counter
            # The only time this fails is if the iterations are highly irregular 
            # (e.g. a bunch of 1000fps followed by a 100 second iteration
            #       - could happen with overwrite=False type scenarios)
            t = monotonic()
            if t - t_last >= delta or flush:
                do_flush(t, arg, wait)

        def do_flush(t: float, arg: T | object, wait: bool) -> None:
            nonlocal t_last, n_acc
            D['_n'] += n_acc

            pbar = runtime.pbar
            if pbar is not None:
                get_desc = self.get_desc
                pbar.try_update(
                    task_id, advance=n_acc, 
                    description=get_desc(arg, D['_n']-1) if arg is not ... and get_desc is not None else None
                )
                if wait:
                    ttl_pause_wait()
            else:
                task = self._task_dict
                if task is not None:
                    task['completed'] = D['_n']
                    get_desc = self.get_desc
                    if arg is not ... and get_desc is not None:
                        task['description'] = get_desc(arg, D['_n']-1)

            n_acc = 0
            t_last = t

        # return update
        return disabled_update if disable else update
    
    def _reset_fast_advance(self) -> Callable[..., None]:
        if self._fast_advance is not None:
            self._fast_advance(n=0, flush=True, wait=False)
        self._fast_advance = self._get_fast_advance()
        return self._fast_advance

    def _get_iter(self, it: Iterable[T]) -> Iterator[T]:
        with utils.noopcontext() if self.entered else self:
            update = self._reset_fast_advance()
            x: T | object = ...
            for x in it:
                yield x
                update(1, x)
            update(0, x, flush=True)

    async def _get_aiter(self, it: AsyncIterable[T]) -> AsyncIterator[T]:
        with utils.noopcontext() if self.entered else self:
            update = self._reset_fast_advance()
            x: T | object = ...
            async for x in it:
                yield x
                update(1, x)
            update(0, x, flush=True)

    def __call__(
        self,
        iter: Iterable[T] | AsyncIterable[T] | int | str | None,
        desc: str | DescFunc[T] | None=None,
        total: float | None=None,
        **kw: Any,
    ) -> mqdm[T]:
        """Bind (or rebind) the bar to an iterable and start counting.

        This backs ``mqdm(it, ...)`` and ``bar(it)``; iterating the result advances
        the bar for you. An ``int`` is treated as ``range(it)`` and a ``str`` as the
        description (when ``desc`` is omitted); ``total`` defaults to ``len(it)`` when
        the length is known. Passing ``None`` (no iterable) just applies the given
        fields, like :meth:`set`. Both sync and async iterables work — use
        ``async for`` for the latter.

        Example:
            ```python
            # open the bar first, then bind the iterable to it
            with mqdm.mqdm(desc="processing") as pbar:
                for x in pbar(items):
                    ...
            ```
        """
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
        self._iter = None
        self._aiter = None
        if isinstance(iter, AsyncIterable):
            self._aiter = self._get_aiter(iter)
        else:
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

    def _detach(self, remove: bool | None=None) -> None:
        """Detach from the live task while preserving local task state."""
        pbar = self.runtime.pbar
        if self.disable or pbar is None: return

        try:
            if self._fast_advance is not None:
                self._fast_advance(n=0, flush=True, wait=False)
            if self._task_dict is None:
                self._task_dict = pbar.pop_task(self.task_id, remove=remove)
            self.runtime.remove_instance(self)
            self.runtime.clear_pbar(strict=False)
        except _BACKEND_CLOSED:
            # Shared manager/proxy already torn down (e.g. worker shutdown after
            # a pool error). Detaching is best-effort, so drop it rather than
            # spewing "Exception ignored in" during generator finalization.
            self.runtime.remove_instance(self)

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
    
    def _resolve_description(self, kw: dict[str, Any], *, initial: bool=False, arg: T | object=..., i: int | None=None) -> dict[str, Any]:
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

        if reset_fast_advance and self._fast_advance is not None:
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
        """Attach the bar to the live display; reverses :meth:`close`.

        A bar is already attached when created and by ``with`` / iteration, so this
        is mainly for reattaching one you detached with :meth:`close`.

        Example:
            ```python
            bar.close()   # detach, keeping its state
            ...           # other terminal work
            bar.open()    # bring it back where it left off
            ```
        """
        self.entered = True
        self._attach()
        return self

    def close(self, remove: bool | None=None) -> mqdm[T]:
        """Detach the bar from the live display, preserving its task state.

        ``remove`` controls whether the row is erased: ``None`` (default) removes it
        only if the bar is transient; ``True`` / ``False`` force it either way. A
        closed bar can be reopened later with :meth:`open`.

        Example:
            ```python
            bar = mqdm.mqdm(total=len(steps), desc="processing")
            for step in steps:
                run(step)
                bar.advance()
            bar.close(remove=True)   # detach and erase the finished row
            ```
        """
        self.entered = False
        self._detach(remove=remove)
        return self

    def print(self, *a: Any, **kw: Any) -> mqdm[T]:
        """Print above the live bars and return the bar (for chaining).

        The bar-scoped form of :func:`mqdm.print` — worker-safe, renders above the
        display, and returns ``self`` so it chains: ``bar.print("done").close()``.
        """
        self.runtime.print(*a, **kw)
        return self

    def set_description(self, desc: str) -> mqdm[T]:
        """Relabel the bar — shorthand for ``set(description=...)``.

        Example:
            ```python
            for stage in stages:
                bar.set_description(f"stage: {stage}")
                ...
            ```
        """
        return self.set(description=desc)

    def update(self, advance: int=1, **kw: Any) -> mqdm[T]:
        """Increment the counter by ``advance`` — a convenience for ``set(advance=...)``.

        Applies immediately and accepts any other :meth:`set` field alongside the
        step. In a tight loop where you only move the counter, :meth:`advance` is
        ~10-20x faster.

        Example:
            ```python
            with mqdm.mqdm(total=len(chunks)) as bar:
                for chunk in chunks:
                    bar.update(len(chunk), description=f"read {chunk.name}")
            ```
        """
        return self.set(advance=advance, **kw)

    def advance(self, n: int=1, arg: Any=...) -> mqdm[T]:
        """Fast increment for tight loops — the way to step a bar by hand.

        Only moves the counter, and batches redraws to the refresh rate, so it
        sustains millions of steps per second (~10-20x faster than :meth:`update`).
        Pass ``arg=`` to also refresh a dynamic ``desc=lambda item, i: ...`` on the
        same cheap path.

        Because updates are batched, ``bar.n`` can lag by up to a frame until the
        next flush (reconciled when the bar closes). Use :meth:`set` / :meth:`update`
        when you need to change something other than the count, or need an exact
        ``bar.n`` right now.

        Note:
            Iterating with ``for x in mqdm(...)`` already advances for you — reach
            for this only in a manual loop.

        Example:
            ```python
            with mqdm.mqdm(total=len(rows)) as bar:
                for row in rows:
                    process(row)
                    bar.advance()
            ```
        """
        self._fast_advance(n, arg)
        return self

    def set(self, **kw: Any) -> mqdm[T]:
        """Change any field of the bar — count, label, total, visibility, or custom fields.

        Every facet is a keyword, and you can change several at once:

        - ``completed=`` sets the counter to an absolute value; ``advance=`` moves it
          by a relative amount.
        - ``total=`` rescales the bar mid-run.
        - ``description=`` relabels it; pass a callable ``desc=lambda item, i: ...``
          once and it is reused on every step.
        - ``visible=`` hides or shows the bar; ``leave=`` / ``transient=`` control
          whether the row stays on screen after it finishes.
        - any other keyword becomes a custom task field, for use with custom columns.

        For a plain increment in a hot loop, prefer :meth:`advance`.

        Example:
            ```python
            bar = mqdm.mqdm(total=100, desc="downloading")
            bar.set(completed=40, description="downloading · 40%")  # count + label together
            bar.set(total=160)                                      # grew mid-run
            bar.set(description="verifying", completed=0, total=3)   # re-scope for a new phase
            ```
        """
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
