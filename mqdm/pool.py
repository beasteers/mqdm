import builtins
import traceback
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Iterable, Literal
from concurrent.futures import Future, as_completed

import mqdm as M

from . import utils
from .bar import mqdm
from .executor import T_POOL_MODE, _RemoteTraceback

T_DESC_FUNC = Callable[[M.args, int], str]


@dataclass
class _PoolPlan:
    fn: Callable
    iterable: Iterable
    desc: str | T_DESC_FUNC
    bar_kw: dict
    n_workers: int
    pool_mode: T_POOL_MODE
    ordered: bool
    squeeze: bool
    on_error: Literal['finish', 'cancel', 'skip']
    fn_kw: dict
    total: int
    runtime: object

    @property
    def inline_single(self) -> bool:
        return self.squeeze and self.total == 1

    @property
    def worker_bar_kw(self) -> dict:
        return {'transient': True, **self.bar_kw}


@dataclass
class _Task:
    index: int
    display_arg: utils.args
    future: Future


@dataclass
class _TaskOutcome:
    task: _Task
    value: Any = None
    error: Exception | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


def ipool(
        fn: Callable,
        iter: Iterable,
        desc: str | T_DESC_FUNC='',
        bar_kw: dict | None=None,
        n_workers: int=8,
        pool_mode: T_POOL_MODE='process',
        ordered_: bool=False,
        squeeze_: bool=True,
        on_error: Literal['finish', 'cancel', 'skip']='cancel',
        runtime=None,
        **kw) -> Iterable:
    """Execute a function in a process pool with a progress bar for each task."""
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
        runtime=runtime or M._runtime,
    )

    if plan.inline_single:
        yield _run_inline_single(plan)
        return

    remote_exceptions = {}
    try:
        with mqdm(desc=plan.desc, elapsed_speed=True, runtime=plan.runtime, **plan.bar_kw) as pbar:
            with M.executor(plan.pool_mode, bar_kw=plan.worker_bar_kw, max_workers=plan.n_workers, runtime=plan.runtime) as executor:
                try:
                    tasks = _submit_tasks(executor, plan, pbar)
                    for outcome in _iter_outcomes(tasks, ordered=plan.ordered):
                        pbar.update(arg=outcome.task.display_arg, i=outcome.task.index)
                        if outcome.succeeded:
                            yield outcome.value
                            continue
                        if plan.on_error == 'skip':
                            _add_func_args_str_to_exception(outcome.error, plan.fn, outcome.task.display_arg)
                            plan.runtime.print(''.join(traceback.format_exception(type(outcome.error), outcome.error, outcome.error.__traceback__)))
                            continue
                        if plan.on_error == 'cancel':
                            _add_func_args_str_to_exception(outcome.error, plan.fn, outcome.task.display_arg)
                            _cancel_pending(tasks, executor)
                            raise outcome.error
                        _append_remote_exception(remote_exceptions, outcome.error, plan.fn, outcome.task.display_arg)
                except KeyboardInterrupt:
                    plan.runtime.pause()
                    _shutdown_for_interrupt(executor, plan.pool_mode, plan.runtime)
                    raise
    except:
        plan.runtime.pause()
        raise

    if remote_exceptions:
        raise _combine_remote_exceptions(remote_exceptions)


def _make_pool_plan(
        *,
        fn: Callable,
        iterable: Iterable,
        desc: str | T_DESC_FUNC,
        bar_kw: dict | None,
        n_workers: int,
        pool_mode: T_POOL_MODE,
        ordered: bool,
        squeeze: bool,
        on_error: Literal['finish', 'cancel', 'skip'],
        fn_kw: dict,
        runtime) -> _PoolPlan:
    total = utils.try_len(iterable, -1)
    if squeeze and total >= 0 and n_workers > total:
        n_workers = total
    if squeeze and n_workers in {0, 1}:
        pool_mode = 'sequential'
    if pool_mode == 'sequential':
        ordered = True

    return _PoolPlan(
        fn=fn,
        iterable=iterable,
        desc=desc,
        bar_kw=bar_kw or {},
        n_workers=n_workers,
        pool_mode=pool_mode,
        ordered=ordered,
        squeeze=squeeze,
        on_error=on_error,
        fn_kw=fn_kw,
        total=total,
        runtime=runtime,
    )


def _run_inline_single(plan: _PoolPlan):
    arg = utils.args.from_item(next(builtins.iter(plan.iterable)), **plan.fn_kw)
    return arg(plan.fn)


def _submit_tasks(executor, plan: _PoolPlan, pbar: mqdm) -> list[_Task]:
    tasks = []
    for index, item in enumerate(plan.iterable):
        display_arg = utils.args.from_item(item)
        call_arg = utils.args.from_item(item)
        call_arg.kw = {**plan.fn_kw, **call_arg.kw}
        future = executor.submit(plan.fn, *call_arg.a, **call_arg.kw)
        tasks.append(_Task(index=index, display_arg=display_arg, future=future))
        pbar.set(append_total=1)
    return tasks


def _iter_outcomes(tasks: list[_Task], *, ordered: bool) -> Iterable[_TaskOutcome]:
    if ordered:
        task_iter = tasks
        future_map = None
    else:
        future_map = {task.future: task for task in tasks}
        task_iter = as_completed(future_map)

    for item in task_iter:
        task = item if ordered else future_map[item]
        future = task.future
        try:
            yield _TaskOutcome(task=task, value=future.result())
        except Exception as error:
            yield _TaskOutcome(task=task, error=error)


def _cancel_pending(tasks: list[_Task], executor) -> None:
    for task in tasks:
        if not task.future.done():
            task.future.cancel()
    executor.shutdown(wait=False, cancel_futures=True)


def _shutdown_for_interrupt(executor, pool_mode: T_POOL_MODE, runtime) -> None:
    if pool_mode == 'process':
        try:
            for pid, process in getattr(executor, '_processes', {}).items():
                print(f"Killing process {pid}...")
                process.kill()
        except Exception as e:
            runtime.print(f"Error killing processes: {e}")
    executor.shutdown(wait=False, cancel_futures=True)


def _add_func_args_str_to_exception(e, fn, arg):
    """Add the function name and arguments to the exception."""
    cause = getattr(e, '__cause__', None)
    if cause is not None and getattr(cause, 'tb', None) is not None:
        cause.tb = f"{cause.tb}\n\nError Thrown in Remote Function: {fn.__name__}{arg}"
    return e


def _append_remote_exception(excs, e, fn, arg):
    tb = getattr(getattr(e, '__cause__', None), 'tb', None)
    if tb is not None and isinstance(tb, str):
        k = (e.__class__, str(e), tb)
        if k not in excs:
            excs[k] = []
        excs[k].append(f"{fn.__name__}{arg}")
    return excs


def _combine_remote_exceptions(excs, n_fn_limit=10, n_tb_limit=10):
    """Merge the exception arguments into a single string."""
    merged = []
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


@wraps(ipool, ['__doc__'])
def pool(
        fn: Callable,
        iter: Iterable,
        desc: str | T_DESC_FUNC='',
        bar_kw: dict | None=None,
        n_workers: int=8,
        pool_mode: T_POOL_MODE='process',
        results_: list=None,
        ordered_: bool=True,
        squeeze_: bool=True,
        runtime=None,
        **kw) -> Iterable:
    results_ = [] if results_ is None else results_
    for x in ipool(fn, iter, desc=desc, bar_kw=bar_kw, n_workers=n_workers, pool_mode=pool_mode, ordered_=ordered_, squeeze_=squeeze_, runtime=runtime, **kw):
        results_.append(x)
    return results_
