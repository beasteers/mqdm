from types import SimpleNamespace

import pytest
from rich.console import Console

import mqdm as M
from mqdm import proxy as proxy_mod
from mqdm.proxy import Progress, ProgressProxy


def test_load_task_restores_finished_metadata():
    progress = Progress(disable=True)
    task_id = progress.add_task("done", total=3, start=True)
    progress.update(task_id, advance=3)
    progress.stop_task(task_id)

    task = progress.tasks[task_id]
    task.finished_speed = 12.5
    snapshot = progress.dump_task(task_id)

    restored = Progress(disable=True)
    restored.load_task(snapshot, start=False)
    restored_task = restored.tasks[task_id]

    assert restored_task.finished
    assert restored_task.start_time == task.start_time
    assert restored_task.stop_time == task.stop_time
    assert restored_task.finished_time == task.finished_time
    assert restored_task.finished_speed == 12.5


def test_convert_proxy_restores_local_tasks_after_manager_failure(monkeypatch):
    progress = Progress(disable=True)
    first = progress.add_task("one", total=2, start=False)
    second = progress.add_task("two", total=4, start=True, completed=1, transient=True)
    snapshot = progress.dump_tasks()

    class BrokenManager:
        def mqdm_Progress(self, *args, **kwargs):
            raise RuntimeError("boom")

    runtime = SimpleNamespace(get_manager=lambda: BrokenManager())

    with pytest.raises(RuntimeError, match="boom"):
        progress.convert_proxy(runtime=runtime)

    assert progress.dump_tasks() == snapshot
    assert set(progress._tasks) == {first, second}
    assert progress._tasks[second].fields["transient"] is True


def test_load_task_advances_task_index():
    progress = Progress(disable=True)

    progress.load_task({
        "id": 7,
        "description": "restored",
        "total": 10,
        "completed": 3,
        "visible": True,
        "fields": {},
        "start_time": 1.0,
    }, start=False)

    new_task_id = progress.add_task("new", total=1)

    assert new_task_id == 8


def test_runtime_get_manager_failure_does_not_poison_runtime(monkeypatch):
    runtime = M.Runtime()

    def fail_start(self):
        raise RuntimeError("boom")

    monkeypatch.setattr(proxy_mod.MqdmManager, "start", fail_start)

    with pytest.raises(RuntimeError, match="boom"):
        runtime.get_manager()

    assert runtime.manager is None


def test_progress_write_prints_to_own_console():
    import io

    console = Console(file=io.StringIO(), force_terminal=True)
    progress = Progress(disable=True, console=console)

    progress.write("hello")

    assert "hello" in console.file.getvalue()


def test_runtime_get_pbar_converts_with_owning_runtime(monkeypatch):
    runtime = M.Runtime()
    progress = Progress(disable=True)
    runtime.pbar = progress
    captured = {}

    class Proxy:
        multiprocess = True

        def start(self):
            return None

    def fake_convert_proxy(*, runtime=None):
        captured["runtime"] = runtime
        return Proxy()

    monkeypatch.setattr(progress, "convert_proxy", fake_convert_proxy)

    proxy = runtime.get_pbar(pool_mode="process", start=False)

    assert isinstance(proxy, Proxy)
    assert runtime.pbar is proxy
    assert captured["runtime"] is runtime


def test_progress_proxy_rich_console_uses_renderable_group():
    progress = Progress(disable=True)
    progress.add_task("demo", total=1, completed=0)
    proxy = SimpleNamespace(_render_progress=lambda: progress)

    renderables = list(ProgressProxy.__rich_console__(proxy, Console(), None))

    assert len(renderables) == 1
    assert hasattr(renderables[0], "__rich_console__")


def _task_snapshot(**kw):
    from mqdm.proxy import TaskSnapshot

    defaults = dict(
        id=0, description="demo", total=100, completed=0, visible=True, fields={},
        start_time=None, stop_time=None, finished_time=None, finished_speed=None, _progress=[],
    )
    defaults.update(kw)
    return TaskSnapshot(**defaults).to_dict()


class _FakeProgressProxy:
    """Exercises ProgressProxy._render_progress without a live manager."""

    _mirror = None
    _render_progress = ProgressProxy._render_progress

    def __init__(self, render_state, live_states):
        self._render_state = render_state
        self._live_states = list(live_states)
        self.render_calls = 0
        self.live_calls = 0

    def dump_render_state(self):
        self.render_calls += 1
        return self._render_state

    def dump_live_state(self):
        state = self._live_states[min(self.live_calls, len(self._live_states) - 1)]
        self.live_calls += 1
        return state


def test_render_progress_caches_mirror_and_reflects_updates():
    render_state = {
        "columns": ["[progress.description]{task.description}"],
        "init_options": {},
        "now": 1000.0,
        "tasks": {0: _task_snapshot(start_time=999.0, completed=0)},
    }
    live_state = {"now": 1002.0, "tasks": {0: _task_snapshot(start_time=999.0, completed=50)}}
    proxy = _FakeProgressProxy(render_state, [live_state])

    mirror_a = proxy._render_progress()
    mirror_b = proxy._render_progress()

    # Static state pulled once; subsequent frames only pull live task state.
    assert mirror_a is mirror_b
    assert proxy.render_calls == 1
    assert proxy.live_calls == 1

    task = mirror_b._tasks[0]
    assert task.completed == 50
    # elapsed uses the source clock (now - start_time), not the local monotonic().
    assert task.elapsed == 1002.0 - 999.0


def test_render_progress_drops_removed_tasks():
    render_state = {
        "columns": ["x"],
        "init_options": {},
        "now": 10.0,
        "tasks": {0: _task_snapshot(id=0), 1: _task_snapshot(id=1)},
    }
    proxy = _FakeProgressProxy(render_state, [{"now": 11.0, "tasks": {0: _task_snapshot(id=0)}}])

    first = proxy._render_progress()
    assert set(first._tasks) == {0, 1}

    second = proxy._render_progress()
    assert set(second._tasks) == {0}


def test_progress_silent_uses_in_memory_console():
    progress = Progress(disable=True, silent=True)

    assert progress.console.file is not None
    assert hasattr(progress.console.file, "getvalue")
    assert progress._init_options["silent"] is True
    assert "console" not in progress._init_options
