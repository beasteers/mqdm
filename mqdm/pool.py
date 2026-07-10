from __future__ import annotations

import re
import traceback
from collections.abc import Iterator
from concurrent.futures import Executor, Future, as_completed
from dataclasses import dataclass
from functools import wraps
from time import monotonic
from typing import Any, TypeVar, Callable, Literal, TypeAlias

import mqdm as M

from . import Runtime, utils
from .bar import mqdm
from .executor import T_POOL_MODE

T = TypeVar('T')
R = TypeVar('R')

DescFunc: TypeAlias = Callable[[utils.args, int], str]
# Failures are grouped for display by a message-independent signature: the
# exception type plus its traceback frame locations. This means e.g.
# ``KeyError('a')`` and ``KeyError('b')`` raised at the same line collapse into
# one group.
FailureKey: TypeAlias = tuple[type[BaseException], tuple[tuple[str, str], ...]]


class PoolError(Exception):
    """Aggregates the failures from a pool run (``on_error='finish'``).

    A single distinct exception across many calls, or many distinct exceptions,
    all surface as one ``PoolError`` — there is no single "right" class to
    re-raise when tasks fail in different ways. The rendered message groups
    identical failures and lists the calls that produced them; ``results`` holds
    the failed :class:`Result` records (each with its ``index``, ``arg`` and the
    original ``error``) for programmatic inspection.
    """
    def __init__(self, detail: str, results: list[Result]) -> None:
        super().__init__(detail)
        self.results = results

    @property
    def count(self) -> int:
        """Total number of failed calls."""
        return len(self.results)


@dataclass
class _PoolPlan:
    fn: Callable[..., R]
    iterable: Iterator[Any]
    desc: str | DescFunc
    bar_kw: dict[str, Any]
    n_workers: int
    pool_mode: T_POOL_MODE
    ordered: bool
    squeeze: bool
    on_error: Literal['finish', 'cancel', 'skip']
    on_interrupt: Literal['terminate', 'kill']
    interrupt_grace: float
    fn_kw: dict[str, Any]
    total: int
    discovered_total: int
    max_in_flight: int
    runtime: Runtime
    submitted: int = 0

    @property
    def worker_bar_kw(self) -> dict[str, Any]:
        return {'transient': True, **self.bar_kw}


@dataclass
class _Task:
    index: int
    display_arg: utils.args
    future: Future[R]


@dataclass
class _TaskOutcome:
    task: _Task
    value: R | None = None
    error: BaseException | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass
class Result:
    """A single task's outcome: its input, return value, and any error.

    ``index`` matches the ``task_index`` carried on the event stream, so a result
    correlates to its live events by key rather than by completion order.
    """
    index: int
    arg: utils.args
    value: R | None = None
    error: BaseException | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _make_result(outcome: _TaskOutcome) -> Result:
    return Result(index=outcome.task.index, arg=outcome.task.display_arg, value=outcome.value, error=outcome.error)


# ---------------------------------------------------------------------------- #
#                                 Pool / iPool                                 #
# ---------------------------------------------------------------------------- #


def ipool(
        fn: Callable[..., R],
        iter: Iterator[Any] | list[Any] | tuple[Any, ...] | set[Any] | range,
        desc: str | DescFunc='',
        bar_kw: dict[str, Any] | None=None,
        n_workers: int=8,
        pool_mode: T_POOL_MODE='process',
        ordered_: bool=False,
        squeeze_: bool=True,
        as_result_: bool=False,
        on_error: Literal['finish', 'cancel', 'skip']='cancel',
        on_interrupt: Literal['terminate', 'kill']='terminate',
        interrupt_grace: float=2.0,
        runtime: Runtime | None=None,
        **kw: Any) -> Iterator[R]:
    """Run a function over an iterable with pooled workers and progress updates.

    Args:
        fn: Function to call for each item.
        iter: Items to process. Each item is passed to ``fn`` directly unless it
            is wrapped in ``mqdm.args``.
        desc: Static description or callback used for the top-level progress bar.
        bar_kw: Extra keyword arguments forwarded to the top-level progress bar.
        n_workers: Maximum number of workers to use.
        pool_mode: Execution mode: ``"process"``, ``"thread"``, or
            ``"sequential"``.
        ordered_: Whether results should be yielded in input order.
        squeeze_: Whether to reduce worker count for very small inputs.
        as_result_: Yield a :class:`Result` per task (ok or error) instead of
            bare return values, and never raise on task failure — the caller
            inspects ``.ok``/``.error``. This takes precedence over ``on_error``.
        on_error: Error policy when ``as_result_`` is false. ``"cancel"`` raises
            the first failure immediately, ``"skip"`` logs each and continues,
            and ``"finish"`` runs everything then raises a :class:`PoolError`
            aggregating all failures.
        on_interrupt: How to stop process-pool workers on ``KeyboardInterrupt``:
            ``"terminate"`` (SIGTERM) lets workers catch it and clean up,
            ``"kill"`` (SIGKILL) is uncatchable but guaranteed.
        interrupt_grace: Seconds to let still-running workers exit on their own
            (they received the same Ctrl-C) before force-signalling stragglers.
        runtime: Runtime that should own the progress display.
        **kw: Extra keyword arguments forwarded to ``fn`` for every item.

    Yields:
        Return values from ``fn`` (or :class:`Result` records if ``as_result_``).

    Raises:
        PoolError: If ``on_error='finish'`` and any task failed.
    """
    plan = _make_pool_plan(
        fn=fn,
        iterable=iter,
        desc=desc,
        bar_kw=bar_kw,
        n_workers=n_workers,
        pool_mode=pool_mode,
        ordered=ordered_,
        squeeze=squeeze_,
        on_error=on_error,
        on_interrupt=on_interrupt,
        interrupt_grace=interrupt_grace,
        fn_kw=kw,
        runtime=runtime or M._current_runtime(),
    )

    failed_results: list[Result] = []

    def _emit(outcome: _TaskOutcome) -> Iterator[Any]:
        # Decide what (if anything) an outcome yields. `as_result_` takes over
        # error handling entirely: every task comes back as a Result (ok or
        # error) and nothing is raised or logged — the caller inspects `.error`.
        if as_result_:
            yield _make_result(outcome)
            return
        if outcome.succeeded:
            yield outcome.value
            return
        if plan.on_error == 'skip':
            call = _call_repr(plan.fn, outcome.task.index, outcome.task.display_arg)
            plan.runtime.print(f"{_traceback_text(outcome.error)}\n\nRaised by {call}")
            return
        failed_results.append(_make_result(outcome))  # on_error='finish': aggregate

    try:
        with mqdm(
            desc=plan.desc,
            total=plan.total if plan.total >= 0 else None,
            runtime=plan.runtime,
            pool_mode=plan.pool_mode,
            **plan.bar_kw,
        ) as pbar:
            executor = M.get_executor(plan.pool_mode, bar_kw=plan.worker_bar_kw, max_workers=plan.n_workers, runtime=plan.runtime)
            shutdown_wait = True
            shutdown_cancel_futures = False
            executor.__enter__()
            try:
                try:
                    indexed_iter = enumerate(plan.iterable)
                    in_flight = {}
                    ready = {}
                    next_index = 0

                    def _fill() -> None:
                        while len(in_flight) < plan.max_in_flight:
                            task = _submit_next(executor, plan, pbar, indexed_iter)
                            if task is None:
                                break
                            in_flight[task.future] = task

                    _fill()
                    while in_flight:
                        future = next(as_completed(in_flight))
                        task = in_flight.pop(future)
                        outcome = _task_outcome(task)
                        pbar.update(arg=outcome.task.display_arg, i=outcome.task.index)

                        if not as_result_ and not outcome.succeeded and plan.on_error == 'cancel':
                            _annotate_exception(outcome.error, plan.fn, outcome.task.index, outcome.task.display_arg)
                            _cancel_pending(list(in_flight.values()), executor)
                            shutdown_wait = False
                            shutdown_cancel_futures = True
                            raise outcome.error

                        if plan.ordered:
                            ready[task.index] = outcome
                            while next_index in ready:
                                yield from _emit(ready.pop(next_index))
                                next_index += 1
                        else:
                            yield from _emit(outcome)

                        _fill()
                except KeyboardInterrupt:
                    plan.runtime.pause()
                    _shutdown_for_interrupt(
                        executor, plan.pool_mode, plan.runtime,
                        op=plan.on_interrupt, grace=plan.interrupt_grace,
                    )
                    shutdown_wait = False
                    shutdown_cancel_futures = True
                    raise
            finally:
                executor.shutdown(wait=shutdown_wait, cancel_futures=shutdown_cancel_futures)
    except:
        plan.runtime.pause()
        raise

    if failed_results:
        raise _build_pool_error(plan.fn, failed_results)


@wraps(ipool, ['__doc__'])
def pool(
        fn: Callable[..., R],
        iter: Iterator[Any] | list[Any] | tuple[Any, ...] | set[Any] | range,
        desc: str | DescFunc='',
        bar_kw: dict[str, Any] | None=None,
        n_workers: int=8,
        pool_mode: T_POOL_MODE='process',
        results_: list[R] | None=None,
        ordered_: bool=True,
        squeeze_: bool=True,
        as_result_: bool=False,
        on_interrupt: Literal['terminate', 'kill']='terminate',
        interrupt_grace: float=2.0,
        runtime: Runtime | None=None,
        **kw: Any) -> list[R]:
    """Collect ``ipool`` results into a list.

    Args:
        fn: Function to call for each item.
        iter: Items to process.
        desc: Static description or callback used for the top-level progress bar.
        bar_kw: Extra keyword arguments forwarded to the top-level progress bar.
        n_workers: Maximum number of workers to use.
        pool_mode: Execution mode: ``"process"``, ``"thread"``, or
            ``"sequential"``.
        results_: Optional list to append results into.
        ordered_: Whether results should be returned in input order.
        squeeze_: Whether to reduce worker count for very small inputs.
        runtime: Runtime that should own the progress display.
        **kw: Extra keyword arguments forwarded to ``fn`` for every item.

    Returns:
        A list of collected results.
    """
    results_ = [] if results_ is None else results_
    for x in ipool(fn, iter, desc=desc, bar_kw=bar_kw, n_workers=n_workers, pool_mode=pool_mode, ordered_=ordered_, squeeze_=squeeze_, as_result_=as_result_, on_interrupt=on_interrupt, interrupt_grace=interrupt_grace, runtime=runtime, **kw):
        results_.append(x)
    return results_




# ---------------------------------------------------------------------------- #
#                                     Utils                                    #
# ---------------------------------------------------------------------------- #



# ----------------------------------- Plan ----------------------------------- #


def _make_pool_plan(
        *,
        fn: Callable[..., R],
        iterable: Iterator[Any] | list[Any] | tuple[Any, ...] | set[Any] | range,
        desc: str | DescFunc,
        bar_kw: dict[str, Any] | None,
        n_workers: int,
        pool_mode: T_POOL_MODE,
        ordered: bool,
        squeeze: bool,
        on_error: Literal['finish', 'cancel', 'skip'],
        on_interrupt: Literal['terminate', 'kill'],
        interrupt_grace: float,
        fn_kw: dict[str, Any],
        runtime: Runtime) -> _PoolPlan:
    total = utils.try_len(iterable, -1)
    if squeeze and total >= 0 and n_workers > total:
        n_workers = total
    if squeeze and n_workers in {0, 1}:
        pool_mode = 'sequential'
    if pool_mode == 'sequential':
        ordered = True

    return _PoolPlan(
        fn=fn,
        iterable=iter(iterable),
        desc=desc,
        bar_kw=bar_kw or {},
        n_workers=n_workers,
        pool_mode=pool_mode,
        ordered=ordered,
        squeeze=squeeze,
        on_error=on_error,
        on_interrupt=on_interrupt,
        interrupt_grace=interrupt_grace,
        fn_kw=fn_kw,
        total=total,
        discovered_total=max(total, 0),
        max_in_flight=max(n_workers, 1),
        runtime=runtime,
    )


# ------------------------------- Task Handling ------------------------------ #


def _submit_next(executor: Executor, plan: _PoolPlan, pbar: mqdm, indexed_iter: Iterator[tuple[int, Any]]) -> _Task | None:
    try:
        index, item = next(indexed_iter)
    except StopIteration:
        return None

    display_arg = utils.args.from_item(item)
    call_arg = utils.args.from_item(item)
    call_arg.kw = {**plan.fn_kw, **call_arg.kw}
    future = executor.submit(_task_call, index, plan.fn, call_arg.a, call_arg.kw)
    plan.submitted += 1
    set_kw: dict[str, Any] = {'started': plan.submitted}  # in-flight + done, for the two-tone bar
    if plan.total < 0:
        plan.discovered_total += 1
        set_kw['total'] = plan.discovered_total
    pbar.set(**set_kw)
    return _Task(index=index, display_arg=display_arg, future=future)


def _task_call(index, fn, args, kw):
    """Run a task in the worker, tagging events with ``task_index`` and emitting
    lifecycle events when a sink is attached.

    Only the cheap ``task_index`` rides the context — the arg/result stay on the
    main process (which submitted them) and are correlated there, so large inputs
    are never re-serialized per event.
    """
    runtime = M._current_runtime()
    emit = runtime.on_event is not None
    with runtime.context(task_index=index):
        if emit:
            runtime.emit("task_started")
        try:
            result = fn(*args, **kw)
        except BaseException as e:
            if emit:
                runtime.emit("task_failed", error=repr(e))
            raise
        if emit:
            runtime.emit("task_finished")
        return result


def _task_outcome(task: _Task) -> _TaskOutcome:
    try:
        return _TaskOutcome(task=task, value=task.future.result())
    except BaseException as error:
        return _TaskOutcome(task=task, error=error)


def _cancel_pending(tasks: list[_Task], executor: Executor) -> None:
    for task in tasks:
        if not task.future.done():
            task.future.cancel()
    executor.shutdown(wait=False, cancel_futures=True)


def _shutdown_for_interrupt(
    executor: Executor,
    pool_mode: T_POOL_MODE,
    runtime: Runtime,
    op: Literal['terminate', 'kill'] = 'terminate',
    grace: float = 2.0,
) -> None:
    """Stop worker processes after an interrupt without ever blocking forever.

    Threads can't be force-stopped, so non-process pools just drop queued work
    and let running tasks unwind. For process pools we replicate the stdlib 3.14
    ``terminate_workers``/``kill_workers`` pattern (snapshot the processes, shut
    the executor down non-blocking so a wedged worker can't deadlock us, then
    signal the survivors) with an added ``grace`` window: workers received the
    same Ctrl-C SIGINT and are likely already unwinding, so we let them exit on
    their own and force-signal only the stragglers still alive after ``grace``.
    """
    if op not in ('terminate', 'kill'):
        op = 'terminate'
    if pool_mode != 'process':
        executor.shutdown(wait=False, cancel_futures=True)
        return

    # Snapshot before shutdown(); it invalidates ._processes.
    procs = list((getattr(executor, '_processes', None) or {}).values())
    native = getattr(executor, f'{op}_workers', None)
    if native is not None and not grace:
        native()  # Python 3.14+: snapshot + non-blocking shutdown + signal.
        return

    executor.shutdown(wait=False, cancel_futures=True)
    if grace and procs:
        deadline = monotonic() + grace
        for p in procs:
            p.join(timeout=max(0.0, deadline - monotonic()))
    for p in procs:
        try:
            if p.is_alive():
                getattr(p, op)()  # terminate() -> SIGTERM, kill() -> SIGKILL
        except (ProcessLookupError, ValueError):
            pass  # already exited/closed


# ---------------------------- Exception Handling ---------------------------- #


_FRAME_RE = re.compile(r'^\s*File "(?P<file>.+)", line (?P<line>\d+)', re.MULTILINE)


def _call_repr(fn: Callable[..., Any], index: int, arg: utils.args) -> str:
    """Human-readable ``[i] fn(args)`` for a failed call (robust to partials etc.)."""
    return f"task {index}: {arg}"


def _traceback_text(e: BaseException) -> str:
    """The formatted traceback for a task failure.

    Process-pool exceptions carry the remote traceback as a preformatted string
    on ``__cause__`` (CPython's private ``_RemoteTraceback.tb``); this is the one
    place we read it. Thread/sequential failures keep a real traceback, which we
    format the same way, so callers get a consistent string in every pool mode.
    """
    tb = getattr(getattr(e, '__cause__', None), 'tb', None)
    if isinstance(tb, str):
        return tb.strip()
    return ''.join(traceback.format_exception(type(e), e, e.__traceback__)).rstrip()


def _failure_key(e: BaseException, tb_text: str) -> FailureKey:
    """A message-independent grouping key: exception type + frame locations."""
    frames = tuple(_FRAME_RE.findall(tb_text))
    return (type(e), frames)


def _annotate_exception(e: BaseException, fn: Callable[..., Any], index: int, arg: utils.args) -> BaseException:
    """Note which call raised ``e`` (used before re-raising on ``on_error='cancel'``).

    Uses ``BaseException.add_note`` (3.11+) so the original exception type and
    traceback are preserved untouched; on older Pythons this is a no-op (the
    remote traceback still identifies the failure).
    """
    add_note = getattr(e, 'add_note', None)
    if add_note is not None:
        add_note(f"mqdm: raised by {_call_repr(fn, index, arg)}")
    return e


def _build_pool_error(fn: Callable[..., Any], results: list[Result], n_call_limit: int = 10, n_group_limit: int = 10) -> PoolError:
    """Render the failed results into a single ``PoolError``.

    Grouping (by exception type + traceback frames) happens here, once, purely
    for the rendered message — ``results`` stays a flat list of every failure.
    """
    groups: dict[FailureKey, list[Result]] = {}
    for r in results:
        groups.setdefault(_failure_key(r.error, _traceback_text(r.error)), []).append(r)
    ordered = sorted(groups.values(), key=len, reverse=True)

    blocks: list[str] = []
    for group in ordered[:n_group_limit]:
        calls = '\n'.join(_call_repr(fn, r.index, r.arg) for r in group[:n_call_limit])
        if len(group) > n_call_limit:
            calls += f"\n... and {len(group) - n_call_limit} more call(s)."
        blocks.append(f"{_traceback_text(group[0].error)}\n Seen in {len(group)} call(s):\n{calls}")
    if len(ordered) > n_group_limit:
        blocks.append(f"... and {len(ordered) - n_group_limit} more distinct exception(s).")

    if len(ordered) == 1:
        summary = f"{type(ordered[0][0].error).__name__} in {len(results)} task(s)."
    else:
        summary = f"{len(ordered)} distinct exceptions across {len(results)} task(s)."
    detail = summary + "\n\n" + "\n\n".join(blocks)
    return PoolError(detail, results)
