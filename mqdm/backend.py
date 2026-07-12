from __future__ import annotations

from typing import Any, Protocol, TypedDict, runtime_checkable


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


@runtime_checkable
class ProgressBackendFactory(Protocol):
    """Factory for constructing runtime progress backend instances.

    Factories may choose their own default columns when ``columns`` is ``None``.
    """

    def create(
        self,
        *,
        runtime: Any,
        columns: tuple[Any, ...] | None = None,
        **kw: Any,
    ) -> "ProgressBackend": ...


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

    def convert_proxy(self, command_bridge=None) -> ProgressBackend: ...
