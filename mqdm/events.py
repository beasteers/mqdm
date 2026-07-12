"""Event model for the mqdm event stream.

mqdm emits structured events during pool runs when a runtime has an
``on_event`` sink attached.  Events fall into two categories:

**Output events** — forwarded to a console by default; routed to the
event sink when one is configured:

- ``print`` — explicit ``mqdm.print()`` / ``bar.print()`` calls
- ``log``   — stdlib logging records captured by ``MQDMHandler``

**Telemetry events** — no default behaviour; always routed to the event
sink (no-op when no sink is attached):

- ``task_started``  — a pool task has been dispatched to a worker
- ``task_finished`` — a pool task completed without error
- ``task_failed``   — a pool task raised an exception

Every event carries a common envelope of ``type``, ``time``, and
``context``.  The ``context`` block includes worker identity fields
(``worker``, ``pid``, ``process_name``, ``thread_name``) placed by
:func:`mqdm.executor._worker_identity`, the ``task_index`` correlating
it back to the input iterable, and any user-supplied context set via
``runtime.context(**kw)``.

.. note::

   ``time`` is a :func:`time.time` float captured at the emit call site
   on the emitting process.  In a process pool the worker clock and the
   consumer clock are independent, so timestamps are useful for
   *within-worker* ordering and for telemetry consumers that record an
   additional ingest timestamp of their own.
"""

from __future__ import annotations

import enum
from typing import Any, TypedDict


class EventType(str, enum.Enum):
    """Known event type strings emitted by mqdm."""

    PRINT = "print"
    LOG = "log"
    TASK_STARTED = "task_started"
    TASK_FINISHED = "task_finished"
    TASK_FAILED = "task_failed"


class EventContext(TypedDict, total=False):
    """Correlation context present on every event.

    The well-known keys below are always available.  User code may add
    arbitrary ``str``-keyed values through ``runtime.context(**kw)``
    and ``runtime.set_base_context(**kw)``.
    """

    worker: str | int
    pid: int
    process_name: str
    thread_name: str
    task_index: int


class EventEnvelope(TypedDict, total=False):
    """Common fields guaranteed on every event dict.

    ``context`` is a dict whose concrete keys are described by
    :class:`EventContext`.  ``total=False`` allows event-specific
    payload keys (``args``, ``message``, ``error``, etc.) to coexist
    on the same dict.
    """

    type: str
    time: float
    context: EventContext


# --------------------------------------------------------------------------- #
#                           Event payload shapes                              #
# --------------------------------------------------------------------------- #


class PrintEvent(EventEnvelope, total=False):
    """Emitted via :meth:`mqdm.Runtime.print` / ``mqdm.print()``."""

    type: str  # "print"
    args: tuple[Any, ...]
    kw: dict[str, Any]


class LogEvent(EventEnvelope, total=False):
    """Emitted by :class:`mqdm.MQDMHandler` for stdlib logging records."""

    type: str  # "log"
    message: str
    markup: bool
    logger_name: str
    level: int
    level_name: str


class TaskStartedEvent(EventEnvelope, total=False):
    """Emitted when a pool task begins executing in a worker.

    Correlation is via ``context["task_index"]`` — no extra payload.
    """

    type: str  # "task_started"


class TaskFinishedEvent(EventEnvelope, total=False):
    """Emitted when a pool task completes successfully.

    Correlation is via ``context["task_index"]`` — no extra payload.
    """

    type: str  # "task_finished"


class TaskFailedEvent(EventEnvelope, total=False):
    """Emitted when a pool task raises an exception.

    The error is transmitted as ``repr(exc)`` to stay picklable
    across process boundaries.
    """

    type: str  # "task_failed"
    error: str


# Union of all known event shapes (for type-narrowing in consumers):
Event = (
    PrintEvent | LogEvent | TaskStartedEvent | TaskFinishedEvent | TaskFailedEvent
)
