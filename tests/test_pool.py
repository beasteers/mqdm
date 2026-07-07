from types import SimpleNamespace

from mqdm.pool import _submit_next


class _DummyExecutor:
    def submit(self, fn, *args, **kwargs):
        return ("future", fn, args, kwargs)


class _DummyBar:
    def __init__(self):
        self.calls = []

    def set(self, **kw):
        self.calls.append(kw)


def test_submit_next_does_not_grow_total_when_plan_total_is_known():
    pbar = _DummyBar()
    executor = _DummyExecutor()
    plan = SimpleNamespace(fn=lambda x: x, fn_kw={}, total=4)

    task = _submit_next(executor, plan, pbar, iter(enumerate([1, 2, 3, 4])))

    assert task is not None
    assert pbar.calls == []


def test_submit_next_grows_total_when_plan_total_is_unknown():
    pbar = _DummyBar()
    executor = _DummyExecutor()
    plan = SimpleNamespace(fn=lambda x: x, fn_kw={}, total=-1)

    task = _submit_next(executor, plan, pbar, iter(enumerate([1])))

    assert task is not None
    assert pbar.calls == [{"append_total": 1}]
