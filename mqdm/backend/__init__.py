from __future__ import annotations

from typing import Any

from .backend import (
    ProgressBackend,
    ProgressBackendFactory,
    ProxyConvertibleBackend,
    RichTaskState,
    TaskState,
)
from .backend import ProgressBackendFactory as _PF  # noqa: F401 — re-export



def create_backend(
    *,
    runtime: Any,
    **kw: Any,
) -> ProgressBackend:
    from . import rich

    return rich.Progress(**kw)

