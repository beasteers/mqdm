import mqdm as M
import pickle
import pytest
import time


def _runtime_worker(x):
    runtime_is_custom = M._current_runtime() is not M._runtime
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
    with pytest.raises(ValueError, match="observed in 1 remote function calls"):
        list(M.ipool(_boom, [1], pool_mode=pool_mode, n_workers=2, on_error='finish'))


@pytest.mark.parametrize('pool_mode', ['sequential', 'thread'])
def test_ipool_on_error_finish_raises_after_yielding_successes(pool_mode):
    def work(x):
        if x == 1:
            raise ValueError("boom")
        return x * 2

    results = []
    with pytest.raises(ValueError, match="observed in 1 remote function calls"):
        for value in M.ipool(work, [0, 1], pool_mode=pool_mode, n_workers=2, ordered_=True, on_error='finish'):
            results.append(value)

    assert results == [0]


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
        assert M._runtime is not runtime
    finally:
        bar.close()

    assert runtime.pbar is None


def test_runtime_is_pickleable():
    runtime = M.Runtime()

    restored = pickle.loads(pickle.dumps(runtime))

    assert isinstance(restored, M.Runtime)
    assert restored.manager is None
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
    assert restored.fast_advance is None


def test_runtime_progress_options_are_runtime_scoped():
    runtime = M.Runtime(refresh_per_second=0.5, expand=True)

    assert runtime.progress_options["refresh_per_second"] == 0.5
    assert runtime.progress_options["expand"] is True


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
