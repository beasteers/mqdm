import json
import time

import pytest

import mqdm as M
from mqdm.event_stream import JsonlSink, ListSink, event_stream


def test_list_sink_collects_events():
    sink = ListSink()
    with event_stream(sink) as rt:
        rt.emit("print", args=("hello",), kw={})
        rt.emit("log", message="test", markup=False, logger_name="x", level=20, level_name="INFO")

    assert len(sink) == 2
    types = [e["type"] for e in sink]
    assert types == ["print", "log"]


def test_list_sink_collects_telemetry_events():
    sink = ListSink()
    with event_stream(sink) as rt:
        rt.emit("task_started")
        rt.emit("task_finished")
        rt.emit("task_failed", error="ValueError('boom')")

    assert len(sink) == 3
    assert [e["type"] for e in sink] == ["task_started", "task_finished", "task_failed"]


def test_event_carries_time_stamp():
    sink = ListSink()
    before = time.time()
    with event_stream(sink) as rt:
        rt.emit("task_started")
    after = time.time()

    t = sink.events[0]["time"]
    assert isinstance(t, float)
    assert before <= t <= after


def test_event_carries_context():
    sink = ListSink()
    with event_stream(sink) as rt:
        with rt.context(task_index=7, crew="alpha"):
            rt.emit("task_started")

    ctx = sink.events[0]["context"]
    assert ctx["task_index"] == 7
    assert ctx["crew"] == "alpha"


def test_event_stream_context_manager_starts_and_stops():
    sink = ListSink()
    stream = event_stream(sink)
    assert stream._thread is None

    with stream as rt:
        assert stream._thread is not None
        assert stream._thread.is_alive()
        rt.emit("task_started")
        time.sleep(0.15)  # let the drain thread pick it up

    assert stream._thread is None
    assert len(sink) == 1


def test_event_stream_runtime_is_usable_for_pool():
    sink = ListSink()
    stream = event_stream(sink)
    assert stream.runtime is not None
    assert stream.runtime.on_event is not None


def test_event_stream_rejects_runtime_with_existing_sink():
    rt = M.Runtime(on_event=lambda e: None)

    with pytest.raises(ValueError, match="already has an on_event"):
        event_stream(ListSink(), runtime=rt)


def test_list_sink_iteration():
    sink = ListSink()
    with event_stream(sink) as rt:
        rt.emit("task_started")
        rt.emit("task_finished")

    types = [e["type"] for e in sink]
    assert types == ["task_started", "task_finished"]


def test_jsonl_sink_writes_valid_json_lines(tmp_path):
    path = tmp_path / "events.jsonl"
    with JsonlSink(str(path)) as sink:
        with event_stream(sink) as rt:
            rt.emit("task_started")
            rt.emit("task_failed", error=repr(ValueError("boom")))

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert "type" in obj
        assert "time" in obj
        assert "context" in obj


def test_jsonl_sink_normalizes_print_args(tmp_path):
    path = tmp_path / "events.jsonl"
    with JsonlSink(str(path)) as sink:
        with event_stream(sink) as rt:
            rt.print("hello", 123, markup=True)

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["type"] == "print"
    assert obj["args"] == ["'hello'", "123"]
    assert obj["kw"] == {"markup": "True"}


def test_jsonl_sink_normalizes_task_failed_error(tmp_path):
    path = tmp_path / "events.jsonl"
    with JsonlSink(str(path)) as sink:
        with event_stream(sink) as rt:
            rt.emit("task_failed", error="ValueError('boom')")

    obj = json.loads(path.read_text().strip())
    assert obj["type"] == "task_failed"
    assert "ValueError" in obj["error"]


def test_jsonl_sink_works_with_file_object(tmp_path):
    path = tmp_path / "events.jsonl"
    with open(str(path), "w") as f:
        with JsonlSink(f) as sink:
            with event_stream(sink) as rt:
                rt.emit("task_started")

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["type"] == "task_started"


def test_event_stream_uses_pool_threaded():
    sink = ListSink()
    with event_stream(sink) as rt:
        results = list(M.ipool(
            lambda x: x * 2, [1, 2, 3],
            pool_mode="thread", n_workers=2,
            runtime=rt,
        ))

    assert sorted(results) == [2, 4, 6]
    task_events = [e for e in sink if e["type"] in ("task_started", "task_finished", "task_failed")]
    assert len(task_events) >= 6  # one started + one finished per task


def test_list_sink_empty_after_close():
    sink = ListSink()
    with event_stream(sink) as rt:
        pass  # no events

    assert len(sink) == 0


def test_event_stream_idempotent_start():
    sink = ListSink()
    stream = event_stream(sink)
    stream.start()
    first_thread = stream._thread
    stream.start()
    assert stream._thread is first_thread
    stream.stop()


def test_event_stream_close_is_stop():
    sink = ListSink()
    stream = event_stream(sink)
    stream.start()
    assert stream._thread is not None
    stream.close()
    assert stream._thread is None
