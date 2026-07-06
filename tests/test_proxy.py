from types import SimpleNamespace

import pytest

import mqdm as M
from mqdm import proxy as proxy_mod
from mqdm.proxy import Progress


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
