from __future__ import annotations

from typing import Any, Callable, Protocol, TypedDict, runtime_checkable


class TaskState(TypedDict, total=False):
    """Minimum detached task snapshot contract shared across backends.

    This is the state mqdm itself needs to reattach a logical task after a bar
    is temporarily detached from a live backend.
    """

    id: int
    description: str
    total: float | None
    completed: float
    visible: bool
    fields: dict[str, Any]
    start_time: float | None


class RichTaskState(TaskState, total=False):
    """Rich-specific snapshot fields used for restore and progress snapshots."""

    stop_time: float | None
    finished_time: float | None
    finished_speed: float | None
    _progress: list[tuple[float, float]] | None


#: Signature of a callable that creates a :class:`ProgressBackend`.
#:
#: ``runtime`` receives the calling :class:`mqdm.Runtime`.  ``columns``
#: is an optional column-tuple that overrides the backend's own defaults.
#: Extra keyword arguments are forwarded to the backend constructor.
ProgressBackendFactory = Callable[..., "ProgressBackend"]


class ProgressBackend(Protocol):
    """Core runtime/backend contract used by mqdm bars.

    This deliberately excludes optional capabilities such as process-mode
    promotion or backend-specific snapshot extensions.
    """

    multiprocess: bool

    # ---------------------------------- Control --------------------------------- #

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def refresh(self) -> None: ...

    # ---------------------------------- Output ---------------------------------- #

    def write(self, *args: Any, **kw: Any) -> Any: ...

    # ------------------------------ Task Management ----------------------------- #

    def add_task(self, **task_kw: Any) -> int: ...
    def try_update(self, task_id: int, **task_update: Any) -> None: ...
    def dump_task(self, task_id: int) -> TaskState | None: ...
    def load_task(self, task: TaskState, start: bool = True) -> None: ...
    def pop_task(self, task_id: int, remove: bool | None = None) -> TaskState | None: ...


@runtime_checkable
class ProxyConvertibleBackend(Protocol):
    """Optional capability for backends that can promote themselves for IPC."""

    def convert_proxy(self, command_dispatch=None) -> ProgressBackend: ...
