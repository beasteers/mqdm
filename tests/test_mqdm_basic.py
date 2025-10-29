import mqdm as M


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
