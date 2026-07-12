from types import SimpleNamespace
import sys

import mqdm as M
from mqdm import _dev


def test_timeit_supports_plain_and_factory_decorator(capsys):
    @_dev.timeit
    def plain():
        return 1

    @_dev.timeit()
    def factory():
        return 2

    assert plain() == 1
    assert factory() == 2

    out = capsys.readouterr().out
    assert "Function plain took" in out
    assert "Function factory took" in out


def test_profile_restores_pause_state(monkeypatch):
    runtime = M.Runtime()
    calls = []

    class FakeProfiler:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            calls.append("enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            calls.append("exit")

        def print(self, **kw):
            calls.append("print")

    monkeypatch.setitem(sys.modules, "pyinstrument", SimpleNamespace(Profiler=FakeProfiler))

    @_dev.profile
    def run():
        return 7

    try:
        from mqdm.executor import _thread_local_data
        had_runtime = hasattr(_thread_local_data, "runtime")
        old_runtime = getattr(_thread_local_data, "runtime", None)
        _thread_local_data.runtime = runtime

        assert run() == 7
        assert runtime.pause_event.is_set()
        assert calls == ["enter", "exit", "print"]
    finally:
        if had_runtime:
            _thread_local_data.runtime = old_runtime
        else:
            delattr(_thread_local_data, "runtime")
