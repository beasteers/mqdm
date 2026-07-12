from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterable, AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Any, Callable, Literal, TypeVar, TypeAlias

import mqdm as M

from . import Runtime, utils
from .bar import mqdm
from .pool import (
    DescFunc,
    PoolError,
    Result,
    _PoolPlanBase,
    _annotate_exception,
    _build_pool_error,
    _call_repr,
    _emit_outcome,
    _make_result,
    _task_event_context,
    _traceback_text,
)

R = TypeVar("R")

OnError: TypeAlias = Literal["finish", "cancel", "skip"]


@dataclass
class _AsyncPoolPlan(_PoolPlanBase):
    iterable: AsyncIterable[Any] | Iterable[Any]
    submitted: int = 0


@dataclass
class _AsyncTask:
    index: int
    display_arg: utils.args
    task: asyncio.Task[R]


@dataclass
class _AsyncTaskOutcome:
    task: _AsyncTask
    value: R | None = None
    error: BaseException | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


async def aipool(
    fn: Callable[..., R],
    iter: AsyncIterable[Any] | Iterable[Any],
    desc: str | DescFunc = "",
    bar_kw: dict[str, Any] | None = None,
    n_workers: int = 8,
    ordered_: bool = False,
    squeeze_: bool = True,
    as_result_: bool = False,
    on_error: OnError = "cancel",
    runtime: Runtime | None = None,
    **kw: Any,
) -> AsyncIterator[R]:
    """Run async work over an iterable with bounded asyncio concurrency.

    Args:
        fn: Async callable to run for each item. Sync callables are executed via
            ``asyncio.to_thread``.
        iter: Items to process. Supports both sync and async iterables.
        desc: Static description or callback used for the top-level progress bar.
        bar_kw: Extra keyword arguments forwarded to the top-level progress bar.
        n_workers: Maximum number of in-flight asyncio tasks.
        ordered_: Whether results should be yielded in input order.
        squeeze_: Whether to reduce concurrency for very small known inputs.
        as_result_: Yield a :class:`Result` per task instead of raising task
            failures.
        on_error: Error policy when ``as_result_`` is false.
        runtime: Runtime that should own the progress display.
        **kw: Extra keyword arguments forwarded to ``fn`` for every item.
    """
    plan = _make_async_pool_plan(
        fn=fn,
        iterable=iter,
        desc=desc,
        bar_kw=bar_kw,
        n_workers=n_workers,
        ordered=ordered_,
        squeeze=squeeze_,
        on_error=on_error,
        fn_kw=kw,
        runtime=runtime or M._current_runtime(),
    )

    failed_results: list[Result] = []
    indexed_iter = _indexed_async_iter(plan.iterable)
    in_flight: dict[asyncio.Task[R], _AsyncTask] = {}
    ready: dict[int, _AsyncTaskOutcome] = {}
    next_index = 0

    async def _fill() -> None:
        while len(in_flight) < plan.max_in_flight:
            task = await _submit_next_async(indexed_iter, plan, pbar)
            if task is None:
                break
            in_flight[task.task] = task

    try:
        with mqdm(
            desc=plan.desc,
            total=plan.total if plan.total >= 0 else None,
            runtime=plan.runtime,
            **plan.bar_kw,
        ) as pbar:
            await _fill()
            while in_flight:
                done, _ = await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    current = in_flight.pop(task)
                    outcome = await _task_outcome_async(current)
                    pbar.update(arg=outcome.task.display_arg, i=outcome.task.index)

                    if not as_result_ and not outcome.succeeded and plan.on_error == "cancel":
                        _annotate_exception(outcome.error, plan.fn, outcome.task.index, outcome.task.display_arg)
                        await _cancel_pending_async(list(in_flight))
                        raise outcome.error

                    if plan.ordered:
                        ready[current.index] = outcome
                        while next_index in ready:
                            for value in _emit_outcome(ready.pop(next_index), plan, as_result_, failed_results):
                                yield value
                            next_index += 1
                    else:
                        for value in _emit_outcome(outcome, plan, as_result_, failed_results):
                            yield value

                await _fill()
    except BaseException:
        plan.runtime.pause()
        await _cancel_pending_async(list(in_flight))
        raise

    if failed_results:
        raise _build_pool_error(plan.fn, failed_results)


async def apool(
    fn: Callable[..., R],
    iter: AsyncIterable[Any] | Iterable[Any],
    desc: str | DescFunc = "",
    bar_kw: dict[str, Any] | None = None,
    n_workers: int = 8,
    ordered_: bool = True,
    squeeze_: bool = True,
    as_result_: bool = False,
    on_error: OnError = "cancel",
    runtime: Runtime | None = None,
    **kw: Any,
) -> list[R]:
    """Collect ``aipool`` results into a list."""
    results: list[R] = []
    async for value in aipool(
        fn,
        iter,
        desc=desc,
        bar_kw=bar_kw,
        n_workers=n_workers,
        ordered_=ordered_,
        squeeze_=squeeze_,
        as_result_=as_result_,
        on_error=on_error,
        runtime=runtime,
        **kw,
    ):
        results.append(value)
    return results


def _make_async_pool_plan(
    *,
    fn: Callable[..., R],
    iterable: AsyncIterable[Any] | Iterable[Any],
    desc: str | DescFunc,
    bar_kw: dict[str, Any] | None,
    n_workers: int,
    ordered: bool,
    squeeze: bool,
    on_error: OnError,
    fn_kw: dict[str, Any],
    runtime: Runtime,
) -> _AsyncPoolPlan:
    total = utils.try_len(iterable, -1)
    n_workers = max(n_workers, 1)
    if squeeze and total >= 0 and n_workers > total:
        n_workers = max(total, 1)
    return _AsyncPoolPlan(
        fn=fn,
        iterable=iterable,
        desc=desc,
        bar_kw=bar_kw or {},
        n_workers=n_workers,
        ordered=ordered,
        squeeze=squeeze,
        on_error=on_error,
        fn_kw=fn_kw,
        total=total,
        discovered_total=max(total, 0),
        max_in_flight=n_workers,
        runtime=runtime,
    )


async def _indexed_async_iter(iterable: AsyncIterable[Any] | Iterable[Any]) -> AsyncIterator[tuple[int, Any]]:
    if isinstance(iterable, AsyncIterable):
        index = 0
        async for item in iterable:
            yield index, item
            index += 1
        return

    for index, item in enumerate(iterable):
        yield index, item


async def _submit_next_async(
    indexed_iter: AsyncIterator[tuple[int, Any]],
    plan: _AsyncPoolPlan,
    pbar: mqdm,
) -> _AsyncTask | None:
    try:
        index, item = await anext(indexed_iter)
    except StopAsyncIteration:
        return None

    display_arg = utils.args.from_item(item)
    call_arg = utils.args.from_item(item)
    call_arg.kw = {**plan.fn_kw, **call_arg.kw}
    task = asyncio.create_task(_task_call_async(index, plan.fn, call_arg.a, call_arg.kw))
    plan.submitted += 1
    set_kw: dict[str, Any] = {"started": plan.submitted}
    if plan.total < 0:
        plan.discovered_total += 1
        set_kw["total"] = plan.discovered_total
    pbar.set(**set_kw)
    return _AsyncTask(index=index, display_arg=display_arg, task=task)


async def _task_call_async(index: int, fn: Callable[..., R], args: tuple[Any, ...], kw: dict[str, Any]) -> R:
    with _task_event_context(index):
        return await _run_async_callable(fn, *args, **kw)


async def _run_async_callable(fn: Callable[..., R], *args: Any, **kw: Any) -> R:
    if inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(getattr(fn, "__call__", None)):
        return await fn(*args, **kw)
    result = await asyncio.to_thread(fn, *args, **kw)
    if inspect.isawaitable(result):
        return await result
    return result


async def _task_outcome_async(task: _AsyncTask) -> _AsyncTaskOutcome:
    try:
        return _AsyncTaskOutcome(task=task, value=await task.task)
    except BaseException as error:
        return _AsyncTaskOutcome(task=task, error=error)


async def _cancel_pending_async(tasks: list[asyncio.Task[Any]]) -> None:
    if not tasks:
        return
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
