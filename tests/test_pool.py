from types import SimpleNamespace

from mqdm.pool import _submit_next
from mqdm._process_pool_keyboard import process_worker_keyboard_interrupt


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
    plan = SimpleNamespace(fn=lambda x: x, fn_kw={}, total=4, submitted=0)

    task = _submit_next(executor, plan, pbar, iter(enumerate([1, 2, 3, 4])))

    assert task is not None
    assert plan.submitted == 1
    assert pbar.calls == [{"started": 1}]  # started tracked; total untouched


def test_submit_next_grows_total_when_plan_total_is_unknown():
    pbar = _DummyBar()
    executor = _DummyExecutor()
    plan = SimpleNamespace(fn=lambda x: x, fn_kw={}, total=-1, discovered_total=0, submitted=0)

    task = _submit_next(executor, plan, pbar, iter(enumerate([1])))

    assert task is not None
    assert plan.discovered_total == 1
    assert plan.submitted == 1
    assert pbar.calls == [{"started": 1, "total": 1}]


class _InterruptingQueue:
    def get(self, block=True):
        raise KeyboardInterrupt


class _UnusedResultQueue:
    def put(self, value):
        raise AssertionError("idle interrupt should exit before reporting a result")


def test_process_worker_keyboard_interrupt_exits_cleanly_when_interrupted_while_idle():
    process_worker_keyboard_interrupt(
        _InterruptingQueue(),
        _UnusedResultQueue(),
        initializer=None,
        initargs=(),
    )
