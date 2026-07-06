import mqdm as M


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


def test_pool_sequential_ordered_and_unordered():
    def square(x):
        return x * x

    data = list(range(6))

    # ordered
    ordered = list(M.ipool(square, data, pool_mode='sequential', ordered_=True, n_workers=1))
    assert ordered == [x * x for x in data]

    # unordered (should contain the same items regardless of order)
    unordered = list(M.ipool(square, data, pool_mode='sequential', ordered_=False, n_workers=1))
    assert sorted(unordered) == sorted([x * x for x in data])


def test_ipool_single_non_subscriptable_iterable():
    results = list(M.ipool(lambda x: x * 2, {3}, pool_mode='sequential', n_workers=1))

    assert results == [6]


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
