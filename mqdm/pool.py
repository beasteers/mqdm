from __future__ import annotations

import traceback
from collections.abc import Iterator
from concurrent.futures import Executor, Future, as_completed
from dataclasses import dataclass
from functools import wraps
from typing import Any, TypeVar, Callable, Literal, TypeAlias

import mqdm as M

from . import Runtime, utils
from .bar import mqdm
from .executor import T_POOL_MODE, _RemoteTraceback

T = TypeVar('T')
R = TypeVar('R')

DescFunc: TypeAlias = Callable[[utils.args, int], str]
ExceptionKey: TypeAlias = tuple[type[BaseException], str, str]
RemoteExceptionMap: TypeAlias = dict[ExceptionKey, list[str]]


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
    fn_kw: dict[str, Any]
    total: int
    max_in_flight: int
    runtime: Runtime

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
        on_error: Error policy. ``"cancel"`` raises immediately, ``"skip"``
            logs and continues, and ``"finish"`` aggregates failures and raises
            after submitted work completes.
        runtime: Runtime that should own the progress display.
        **kw: Extra keyword arguments forwarded to ``fn`` for every item.

    Yields:
        Results from ``fn``.
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
        fn_kw=kw,
        runtime=runtime or M._current_runtime(),
    )

    remote_exceptions: RemoteExceptionMap = {}

    def _emit(outcome: _TaskOutcome) -> Iterator[Any]:
        # Decide what (if anything) an outcome yields. `as_result_` yields a
        # Result record (identity + value/error); otherwise the bare value.
        if outcome.succeeded:
            yield _make_result(outcome) if as_result_ else outcome.value
            return
        if plan.on_error == 'skip':
            _add_func_args_str_to_exception(outcome.error, plan.fn, outcome.task.display_arg)
            plan.runtime.print(''.join(traceback.format_exception(type(outcome.error), outcome.error, outcome.error.__traceback__)))
            if as_result_:  # surface skipped failures inline instead of dropping them
                yield _make_result(outcome)
            return
        _append_remote_exception(remote_exceptions, outcome.error, plan.fn, outcome.task.display_arg)

    try:
        with mqdm(
            desc=plan.desc,
            total=plan.total if plan.total >= 0 else None,
            elapsed_speed=True,
            runtime=plan.runtime,
            pool_mode=plan.pool_mode,
            **plan.bar_kw,
        ) as pbar:
            executor = M.executor(plan.pool_mode, bar_kw=plan.worker_bar_kw, max_workers=plan.n_workers, runtime=plan.runtime)
            shutdown_wait = True
            shutdown_cancel_futures = False
            executor.__enter__()
            try:
                try:
                    indexed_iter = enumerate(plan.iterable)
                    in_flight = {}
                    ready = {}
                    next_index = 0

                    while len(in_flight) < plan.max_in_flight:
                        task = _submit_next(executor, plan, pbar, indexed_iter)
                        if task is None:
                            break
                        in_flight[task.future] = task

                    while in_flight:
                        future = next(as_completed(in_flight))
                        task = in_flight.pop(future)
                        outcome = _task_outcome(task)
                        pbar.update(arg=outcome.task.display_arg, i=outcome.task.index)

                        if not outcome.succeeded and plan.on_error == 'cancel':
                            _add_func_args_str_to_exception(outcome.error, plan.fn, outcome.task.display_arg)
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

                        while len(in_flight) < plan.max_in_flight:
                            task = _submit_next(executor, plan, pbar, indexed_iter)
                            if task is None:
                                break
                            in_flight[task.future] = task
                except KeyboardInterrupt:
                    plan.runtime.pause()
                    _shutdown_for_interrupt(executor, plan.pool_mode, plan.runtime)
                    shutdown_wait = False
                    shutdown_cancel_futures = True
                    raise
            finally:
                executor.shutdown(wait=shutdown_wait, cancel_futures=shutdown_cancel_futures)
    except:
        plan.runtime.pause()
        raise

    if remote_exceptions:
        raise _combine_remote_exceptions(remote_exceptions)


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
    for x in ipool(fn, iter, desc=desc, bar_kw=bar_kw, n_workers=n_workers, pool_mode=pool_mode, ordered_=ordered_, squeeze_=squeeze_, as_result_=as_result_, runtime=runtime, **kw):
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
        fn_kw=fn_kw,
        total=total,
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
    if plan.total < 0:
        pbar.set(append_total=1)
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


def _shutdown_for_interrupt(executor: Executor, pool_mode: T_POOL_MODE, runtime: Runtime) -> None:
    if pool_mode == 'process':
        try:
            for pid, process in getattr(executor, '_processes', {}).items():
                print(f"Killing process {pid}...")
                process.kill()
        except Exception as e:
            runtime.print(f"Error killing processes: {e}")
    executor.shutdown(wait=False, cancel_futures=True)


# ---------------------------- Exception Handling ---------------------------- #


def _add_func_args_str_to_exception(e: BaseException, fn: Callable[..., Any], arg: utils.args) -> BaseException:
    """Add the function name and arguments to the exception."""
    cause = getattr(e, '__cause__', None)
    if cause is not None and getattr(cause, 'tb', None) is not None:
        cause.tb = f"{cause.tb}\n\nError Thrown in Remote Function: {fn.__name__}{arg}"
    return e


def _append_remote_exception(excs: RemoteExceptionMap, e: BaseException, fn: Callable[..., Any], arg: utils.args) -> RemoteExceptionMap:
    tb = getattr(getattr(e, '__cause__', None), 'tb', None)
    if not isinstance(tb, str):
        tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__)).rstrip()
    k = (e.__class__, str(e), tb)
    if k not in excs:
        excs[k] = []
    excs[k].append(f"{fn.__name__}{arg}")
    return excs


def _combine_remote_exceptions(excs: RemoteExceptionMap, n_fn_limit: int = 10, n_tb_limit: int = 10) -> BaseException:
    """Merge the exception arguments into a single string."""
    merged: list[str] = []
    n_fns = sum(len(args) for args in excs.values())
    for (t, st, tb), args in sorted(excs.items(), key=lambda x: len(x[0]), reverse=True)[:n_tb_limit]:
        arg_str = '\n'.join(args[:n_fn_limit])
        merged.append(f"{tb}\n Seen in {len(args)} Remote Function(s): \n{arg_str}")
        if len(args) > n_fn_limit:
            merged.append(f"... and {len(args) - n_fn_limit} more.")

    if len(excs) > n_tb_limit:
        merged.append(f"... and {len(excs) - n_tb_limit} more exceptions.")

    if len(excs) == 1:
        (t, st, tb), args = next(iter(excs.items()))
        msg = f"{st} -- observed in {n_fns} remote function calls."
        cls = t
    else:
        msg = f"{len(excs)} distinct exceptions observed in {n_fns} remote function calls."
        cls = RuntimeError

    e = cls(msg)
    e.__cause__ = _RemoteTraceback("\n".join(merged))
    return e
