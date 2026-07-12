import asyncio
import mqdm as M
from mqdm.runtime import _runtime
import pickle
import pytest
import time


def _runtime_worker(x):
    runtime_is_custom = M._current_runtime() is not _runtime
    for _ in M.mqdm(range(1), disable=True):
        pass
    return runtime_is_custom, x + 1


def _boom(_):
    raise ValueError("boom")


def test_mqdm_string_argument_sets_description():
    bar = M.mqdm("hello", disable=True)

    assert bar.total is None
    assert bar.n == 0
    assert bar._desc == "hello"
    assert bar._iter is None


def test_mqdm_iter_counts_when_disabled():
    bar = M.mqdm(disable=True)
    n_total = 5
    for _ in bar(range(n_total)):
        pass

    # Internal counters should be updated even when disabled
    assert bar.n == n_total
    assert bar.total == n_total


def test_mqdm_async_iter_counts_when_disabled():
    async def source():
        for i in range(5):
            yield i

    async def run():
        bar = M.mqdm(disable=True)
        async for _ in bar(source()):
            pass
        return bar

    bar = asyncio.run(run())

    assert bar.n == 5
    assert bar.total is None


def test_mqdm_async_iter_rejects_sync_for():
    async def source():
        yield 1

    bar = M.mqdm(source(), disable=True)

    with pytest.raises(TypeError, match="use 'async for'"):
        iter(bar)


def test_mqdm_sync_iter_rejects_async_for():
    async def run():
        bar = M.mqdm([1], disable=True)
        with pytest.raises(TypeError, match="use 'for'"):
            async for _ in bar:
                pass

    asyncio.run(run())


@pytest.mark.parametrize(('ordered', 'expected'), [
    (True, [x * x for x in range(6)]),
    (False, sorted([x * x for x in range(6)])),
])
def test_pool_sequential_ordered_and_unordered(ordered, expected):
    def square(x):
        return x * x

    data = list(range(6))
    results = list(M.ipool(square, data, pool_mode='sequential', ordered_=ordered, n_workers=1))
    if ordered:
        assert results == expected
    else:
        assert sorted(results) == expected


def test_ipool_single_non_subscriptable_iterable():
    results = list(M.ipool(lambda x: x * 2, {3}, pool_mode='sequential', n_workers=1))

    assert results == [6]


def test_ipool_single_item_respects_on_error_skip():
    results = list(M.ipool(_boom, [1], pool_mode='sequential', n_workers=1, on_error='skip'))

    assert results == []


@pytest.mark.parametrize('pool_mode', ['sequential', 'thread'])
def test_ipool_on_error_finish_aggregates_local_exceptions(pool_mode):
    with pytest.raises(M.PoolError, match="ValueError in 1 task") as ei:
        list(M.ipool(_boom, [1], pool_mode=pool_mode, n_workers=2, on_error='finish'))
    assert ei.value.count == 1
    assert type(ei.value.results[0].error) is ValueError


@pytest.mark.parametrize('pool_mode', ['sequential', 'thread'])
def test_ipool_on_error_finish_raises_after_yielding_successes(pool_mode):
    def work(x):
        if x == 1:
            raise ValueError("boom")
        return x * 2

    results = []
    with pytest.raises(M.PoolError, match="ValueError in 1 task"):
        for value in M.ipool(work, [0, 1], pool_mode=pool_mode, n_workers=2, ordered_=True, on_error='finish'):
            results.append(value)

    assert results == [0]


@pytest.mark.parametrize('pool_mode', ['sequential', 'thread'])
def test_ipool_on_error_finish_dedupes_across_messages(pool_mode):
    # Same exception type raised at the same line with *different* messages
    # should collapse into a single group (message-independent dedup).
    def work(x):
        raise KeyError(f"key_{x}")

    with pytest.raises(M.PoolError) as ei:
        list(M.ipool(work, [1, 2, 3], pool_mode=pool_mode, n_workers=2, on_error='finish'))

    err = ei.value
    assert err.count == 3                                 # all 3 failures kept
    assert {type(r.error) for r in err.results} == {KeyError}
    assert str(err).count(" Seen in ") == 1              # collapsed to one group
    assert "Seen in 3 call(s)" in str(err)


@pytest.mark.parametrize('pool_mode', ['sequential', 'thread'])
def test_ipool_on_error_finish_groups_distinct_exceptions(pool_mode):
    def work(x):
        if x % 2 == 0:
            raise ValueError("even")
        raise KeyError("odd")

    with pytest.raises(M.PoolError, match="2 distinct exceptions across 4 task") as ei:
        list(M.ipool(work, [0, 1, 2, 3], pool_mode=pool_mode, n_workers=2, on_error='finish'))
    assert {type(r.error) for r in ei.value.results} == {ValueError, KeyError}
    assert ei.value.count == 4


@pytest.mark.parametrize('pool_mode', ['sequential', 'thread'])
def test_ipool_as_result_suppresses_raising(pool_mode):
    # Option A: as_result_ hands back a Result per task and never raises,
    # regardless of on_error.
    def work(x):
        if x == 1:
            raise ValueError("boom")
        return x * 10

    for oe in ('cancel', 'finish', 'skip'):
        results = list(M.ipool(
            work, [0, 1, 2], pool_mode=pool_mode, n_workers=2,
            ordered_=True, as_result_=True, on_error=oe,
        ))
        assert [r.ok for r in results] == [True, False, True]
        assert [r.index for r in results] == [0, 1, 2]
        assert results[0].value == 0 and results[2].value == 20
        assert type(results[1].error) is ValueError


def test_ipool_threaded_generator_streams_without_eager_submission():
    submitted = []

    def source():
        for i in range(5):
            submitted.append(i)
            yield i

    def work(x):
        time.sleep(0.01)
        return x

    results = M.ipool(work, source(), pool_mode='thread', n_workers=2, ordered_=False)

    first = next(results)

    assert first in range(5)
    assert len(submitted) <= 2

    rest = list(results)
    assert sorted([first, *rest]) == list(range(5))


def test_ipool_threaded_ordered_mode_buffers_completed_results():
    def work(x):
        time.sleep(0.01 * (3 - x))
        return x

    results = list(M.ipool(work, [0, 1, 2], pool_mode='thread', n_workers=3, ordered_=True))

    assert results == [0, 1, 2]


def test_ipool_threaded_ordered_cancel_raises_before_slow_prior_task_finishes():
    def work(x):
        if x == 0:
            time.sleep(0.2)
            return x
        if x == 1:
            raise ValueError("boom")
        return x

    start = time.monotonic()
    with pytest.raises(ValueError, match="boom"):
        list(M.ipool(work, [0, 1], pool_mode='thread', n_workers=2, ordered_=True, on_error='cancel'))

    assert time.monotonic() - start < 0.15


def test_mqdm_restores_from_task_dict():
    bar = M.mqdm(
        task_id={
            'id': 7,
            'description': 'restored',
            'total': 9,
            'completed': 4,
            'start_time': 1.0,
        },
    )

    try:
        assert bar.task_id == 7
        assert bar.n == 4
        assert bar.total == 9
        assert bar._desc == 'restored'
        assert bar._task_dict['id'] == 7
    finally:
        bar.close()


def test_mqdm_restores_from_task_dict_when_disabled():
    bar = M.mqdm(
        task_id={
            'id': 7,
            'description': 'restored',
            'total': 9,
            'completed': 4,
            'start_time': 1.0,
        },
        disable=True,
    )

    assert bar.task_id == 7
    assert bar.n == 4
    assert bar.total == 9
    assert bar._desc == 'restored'
    assert bar._task_dict['id'] == 7


def test_mqdm_can_use_custom_runtime():
    runtime = M.Runtime()
    bar = M.mqdm(total=2, runtime=runtime)

    try:
        assert bar.runtime is runtime
        assert runtime.pbar is not None
        assert _runtime is not runtime
    finally:
        bar.close()

    assert runtime.pbar is None


def test_runtime_is_pickleable():
    runtime = M.Runtime()

    restored = pickle.loads(pickle.dumps(runtime))

    assert isinstance(restored, M.Runtime)
    assert restored.command_dispatch is None
    assert not restored.instances
    assert restored.pause_event.is_set()
    assert restored.shutdown_event.is_set()


def test_runtime_with_local_progress_is_pickleable():
    runtime = M.Runtime()
    bar = M.mqdm(total=1, runtime=runtime)

    try:
        restored = pickle.loads(pickle.dumps(runtime))
    finally:
        bar.close()

    assert isinstance(restored, M.Runtime)
    assert restored.pbar is None


def test_disabled_mqdm_is_pickleable():
    bar = M.mqdm("hello", disable=True)

    restored = pickle.loads(pickle.dumps(bar))

    assert restored.disable is True
    assert restored._desc == "hello"
    assert restored._iter is None
    assert restored._fast_advance is None


def test_runtime_backend_options_are_runtime_scoped():
    runtime = M.Runtime(refresh_per_second=0.5, expand=True)

    assert runtime.backend_options["refresh_per_second"] == 0.5
    assert runtime.backend_options["expand"] is True


def test_runtime_configure_rejects_changes_after_progress_creation():
    runtime = M.Runtime()
    bar = M.mqdm(total=1, runtime=runtime)

    try:
        with pytest.raises(RuntimeError, match="Cannot configure runtime progress options"):
            runtime.configure(refresh_per_second=12)
    finally:
        bar.close()


@pytest.mark.parametrize(('pool_mode', 'fn', 'expected', 'n_workers', 'squeeze'), [
    ('sequential', lambda x: x + 1, [2, 3], 1, True),
    ('thread', _runtime_worker, [(True, 2), (True, 3)], 2, False),
    ('process', _runtime_worker, [(True, 2), (True, 3)], 2, False),
])
def test_ipool_can_use_custom_runtime(pool_mode, fn, expected, n_workers, squeeze):
    runtime = M.Runtime()

    try:
        results = list(M.ipool(fn, [1, 2], runtime=runtime, pool_mode=pool_mode, n_workers=n_workers, squeeze_=squeeze))
    except (EOFError, PermissionError, OSError) as exc:
        if pool_mode != 'process':
            raise
        pytest.skip(f"process-mode runtime propagation unavailable in this environment: {exc}")

    if pool_mode == 'process':
        assert sorted(results) == expected
    else:
        assert results == expected
    assert runtime.pbar is None
