"""Event-stream transport and built-in sinks.

The :class:`EventStream` helper bridges the gap between ``on_event``
(the raw hook on :class:`mqdm.Runtime`) and a real consumer: it provides
a correct-by-construction transport so events emitted inside workers
are reliably delivered to a sink running in the main process.

::

    import mqdm as M

    sink = M.events.ListSink()
    with M.events.event_stream(sink) as runtime:
        list(M.pool(work_fn, items, runtime=runtime))

    for event in sink.events:
        print(event["type"], event["context"].get("task_index"))
"""

from __future__ import annotations

import json
import multiprocessing as mp
import threading
from queue import Empty
from typing import Any, Callable, TextIO

import mqdm as M

from .events import EventEnvelope
from ..runtime import Runtime

_REQUEST_POLL_INTERVAL = 0.1


class EventStream:
    """Transport + drain for the mqdm event stream.

    Creates a :class:`multiprocessing.Queue`, sets
    ``runtime.on_event = queue.put`` (picklable, so workers can reach it),
    and runs a daemon thread in the main process that drains the queue
    and calls ``sink(event)``.

    For thread / sequential pools the queue is still used — the overhead
    is negligible and the single code path is simpler.  The drain thread
    polls at 0.1 s intervals; a sentinel ``None`` causes it to exit.

    Parameters:
        sink: Callable that receives each event dict.
        runtime: Existing :class:`Runtime` to attach to.  If ``None`` a
            fresh runtime is created — that is the common case.
    """

    def __init__(
        self,
        sink: Callable[[EventEnvelope], Any],
        runtime: Runtime | None = None,
    ) -> None:
        self._sink = sink
        self._queue: Any = mp.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if runtime is None:
            runtime = Runtime(on_event=self._queue.put)
        elif runtime.on_event is not None:
            raise ValueError(
                "The provided runtime already has an on_event sink. "
                "Pass a fresh Runtime or set runtime.on_event=None first."
            )
        else:
            runtime.on_event = self._queue.put
        self.runtime = runtime

    def start(self) -> EventStream:
        """Spawn the drain thread (idempotent)."""
        if self._thread is not None:
            return self
        self._stop.clear()
        thread = threading.Thread(
            target=self._drain, name="mqdm-event-drain", daemon=True,
        )
        thread.start()
        self._thread = thread
        return self

    def stop(self) -> None:
        """Signal the drain thread and wait for it to exit."""
        if self._thread is None:
            return
        self._stop.set()
        self._queue.put(None)
        self._thread.join(timeout=1.0)
        self._thread = None

    def close(self) -> None:
        """Alias for :meth:`stop`."""
        self.stop()

    def _drain(self) -> None:
        while True:
            try:
                event = self._queue.get(timeout=_REQUEST_POLL_INTERVAL)
            except Empty:
                if self._stop.is_set():
                    return
                continue
            if event is None:
                return
            try:
                self._sink(event)
            except Exception:
                pass

    def __enter__(self) -> Runtime:
        self.start()
        return self.runtime

    def __exit__(self, *args: Any) -> None:
        self.stop()

    def __del__(self) -> None:
        try:
            if self._thread is not None:
                self.stop()
        except Exception:
            pass


def event_stream(
    sink: Callable[[EventEnvelope], Any],
    runtime: Runtime | None = None,
) -> EventStream:
    """Create an :class:`EventStream` for *sink*.

    Returns an :class:`EventStream` instance that should be used as a
    context manager::

        with M.events.event_stream(my_sink) as runtime:
            M.pool(fn, items, runtime=runtime)
    """
    return EventStream(sink, runtime=runtime)


# --------------------------------------------------------------------------- #
#                               Built-in sinks                                #
# --------------------------------------------------------------------------- #


class ListSink:
    """Collect every event into an in-memory list.

    For thread / sequential pools the list is populated directly.
    For process pools the drain thread in the main process calls
    ``append``, so ``.events`` is always the single source of truth.

    ::

        sink = M.events.ListSink()
        with M.events.event_stream(sink) as runtime:
            M.pool(fn, items, runtime=runtime)
        first_error = next(e for e in sink.events if e["type"] == "task_failed")
    """

    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []

    def __call__(self, event: EventEnvelope) -> None:
        self.events.append(event)

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self):
        return iter(self.events)


class JsonlSink:
    """Write each event as one JSON line to *file*.

    *file* may be a path (``str``) or an already-open file-like object
    that accepts ``.write(s)`` and ``.flush()``.

    Payload fields that are not natively JSON-safe (e.g. the raw ``args``
    tuple on a ``print`` event, or the ``error`` repr on a ``task_failed``
    event) are serialised as their ``repr()`` so the JSONL file is always
    valid and portable.

    ::

        with M.events.JsonlSink("events.jsonl") as sink:
            with M.events.event_stream(sink) as runtime:
                M.pool(fn, items, runtime=runtime)
    """

    def __init__(self, file: str | TextIO) -> None:
        if isinstance(file, str):
            self._file: TextIO = open(file, "w")
            self._owns_file = True
        else:
            self._file = file
            self._owns_file = False

    def __call__(self, event: EventEnvelope) -> None:
        self._file.write(json.dumps(_normalize(event)) + "\n")
        self._file.flush()

    def __enter__(self) -> JsonlSink:
        return self

    def __exit__(self, *args: Any) -> None:
        if self._owns_file:
            self._file.close()


def _normalize(event: EventEnvelope) -> dict[str, Any]:
    """Return a JSON-safe copy of *event*.

    ``PrintEvent.args`` and ``PrintEvent.kw`` are rendered via ``repr()``
    so arbitrary objects survive the serialisation boundary.
    """
    out: dict[str, Any] = dict(event)
    etype = event.get("type", "")
    if etype == "print":
        out["args"] = [repr(a) for a in event.get("args", ())]
        out["kw"] = {k: repr(v) for k, v in event.get("kw", {}).items()}
    elif etype == "task_failed":
        out["error"] = repr(event.get("error", ""))
    return out


__all__ = [
    "EventStream",
    "JsonlSink",
    "ListSink",
    "event_stream",
]
