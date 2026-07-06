import mqdm as M
import pytest


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
