import asyncio
import threading

import pytest

import mqdm as M


async def _collect(async_iterable):
    return [item async for item in async_iterable]


def test_aipool_async_function_unordered():
    async def work(x):
        await asyncio.sleep(0.01 * (3 - x))
        return x * 2

    results = asyncio.run(_collect(M.aipool(work, [0, 1, 2], n_workers=3, ordered_=False)))

    assert sorted(results) == [0, 2, 4]


def test_apool_async_function_ordered():
    async def work(x):
        await asyncio.sleep(0.01 * (3 - x))
        return x * 3

    results = asyncio.run(M.apool(work, [0, 1, 2], n_workers=3, ordered_=True))

    assert results == [0, 3, 6]


def test_apool_sync_function_uses_thread_fallback():
    main_thread = threading.current_thread().name

    def work(x):
        return threading.current_thread().name != main_thread, x + 1

    results = asyncio.run(M.apool(work, [0, 1], n_workers=2))

    assert results == [(True, 1), (True, 2)]


def test_aipool_supports_async_iterable_and_bounded_submission():
    submitted = []

    async def source():
        for i in range(5):
            submitted.append(i)
            yield i

    async def work(x):
        await asyncio.sleep(0.01)
        return x

    async def run():
        results = M.aipool(work, source(), n_workers=2, ordered_=False)
        first = await anext(results)
        assert first in range(5)
        assert len(submitted) <= 2
        rest = [item async for item in results]
        return [first, *rest]

    results = asyncio.run(run())

    assert sorted(results) == list(range(5))


def test_aipool_as_result_suppresses_raising():
    async def work(x):
        if x == 1:
            raise ValueError("boom")
        return x * 10

    results = asyncio.run(_collect(M.aipool(work, [0, 1, 2], n_workers=2, ordered_=True, as_result_=True)))

    assert [r.ok for r in results] == [True, False, True]
    assert [r.index for r in results] == [0, 1, 2]
    assert results[0].value == 0 and results[2].value == 20
    assert type(results[1].error) is ValueError


def test_aipool_on_error_finish_aggregates_async_exceptions():
    async def work(x):
        if x == 1:
            raise ValueError("boom")
        return x * 2

    with pytest.raises(M.PoolError, match="ValueError in 1 task"):
        asyncio.run(_collect(M.aipool(work, [0, 1], n_workers=2, ordered_=True, on_error="finish")))
