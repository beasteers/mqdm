from __future__ import annotations

from typing import Any, Protocol, TypedDict, runtime_checkable


class TaskState(TypedDict, total=False):
    """Detached or transport-safe task snapshot shared across backends."""

    id: int
    description: str
    total: float | None
    completed: float
    visible: bool
    fields: dict[str, Any]
    start_time: float | None
    stop_time: float | None
    finished_time: float | None
    finished_speed: float | None
    _progress: list[tuple[float, float]] | None


class ProgressBackend(Protocol):
    """Internal progress backend contract used by mqdm runtime and bars."""

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

    def convert_proxy(self, runtime=None) -> ProgressBackend: ...
