import logging
import warnings
from typing import Any, Callable

import mqdm as M


class MQDMHandler(logging.Handler):
    """A logging handler that routes records through mqdm.print so output
    is rendered above progress bars and works across processes.

    Note: formats to plain strings for safe cross-process transmission.
    """
    LEVEL_STYLE = {
        logging.DEBUG: "dim",
        logging.INFO: "",
        logging.WARNING: "yellow",
        logging.ERROR: "red",
        logging.CRITICAL: "bold red",
    }

    def __init__(self, runtime, *, markup: bool = True, level: int = logging.NOTSET):
        super().__init__(level)
        self.runtime = runtime
        self.markup = markup

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            if self.markup:
                style = self.LEVEL_STYLE.get(record.levelno, "")
                if style:
                    msg = f"[{style}]{msg}[/{style}]"
            self.runtime.print(msg)
        except Exception:
            self.handleError(record)

    @classmethod
    def ensure_on_logger(cls, logger: logging.Logger, runtime: M.Runtime, formatter=None, **kw) -> 'MQDMHandler':
        """Ensure a logger has a single MQDMHandler for the given runtime."""
        existing = next((h for h in logger.handlers if isinstance(h, MQDMHandler) and h.runtime is runtime), None)
        handler = existing or cls(runtime, **kw)
        if 'markup' in kw:
            handler.markup = kw['markup']
        handler.setFormatter(formatter or getattr(handler, 'formatter', None) or _make_default_formatter())
        if existing is None:
            logger.addHandler(handler)
            runtime.logging_handlers.add(handler)
        return handler

    @classmethod
    def remove_from_logger(cls, logger: logging.Logger, runtime: M.Runtime) -> None:
        """Remove all MQDMHandlers for a runtime from a logger."""
        to_remove = [h for h in logger.handlers if isinstance(h, cls) and h.runtime is runtime]
        for handler in to_remove:
            logger.removeHandler(handler)
            runtime.logging_handlers.discard(handler)


def _make_default_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------- #
#                                   Warnings                                   #
# ---------------------------------------------------------------------------- #


_warning_capture_refcount = 0
_warnings_showwarning: Callable[..., Any] | None = None


def _acquire_warning_capture() -> None:
    global _warnings_showwarning
    global _warning_capture_refcount
    if _warning_capture_refcount == 0:
        warnings.simplefilter("default")
        if _warnings_showwarning is None:
            _warnings_showwarning = warnings.showwarning
        warnings.showwarning = _showwarning
    _warning_capture_refcount += 1


def _release_warning_capture() -> None:
    global _warnings_showwarning
    global _warning_capture_refcount
    if _warning_capture_refcount == 0:
        return
    _warning_capture_refcount -= 1
    if _warning_capture_refcount == 0:
        if _warnings_showwarning is not None:
            warnings.showwarning = _warnings_showwarning
            _warnings_showwarning = None


def _showwarning(message, category, filename, lineno, file=None, line=None) -> None:
    if file is not None:
        if _warnings_showwarning is not None:
            _warnings_showwarning(message, category, filename, lineno, file, line)
        return

    rendered = warnings.formatwarning(message, category, filename, lineno, line)
    logger = logging.getLogger("py.warnings")
    logger.warning("%s", rendered)


def capture_warnings(runtime=None) -> None:
    runtime = runtime or M._current_runtime()
    if runtime.capture_warnings:
        return
    _acquire_warning_capture()
    runtime.capture_warnings = True
    cfg = runtime.logging_config or {}
    runtime.logging_config = {**cfg, "capture_warnings": True}


def release_warnings(runtime=None) -> None:
    runtime = runtime or M._current_runtime()
    if not runtime.capture_warnings:
        return
    _release_warning_capture()
    runtime.capture_warnings = False
    cfg = runtime.logging_config or {}
    runtime.logging_config = {**cfg, "capture_warnings": False}

