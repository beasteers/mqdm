import logging
import warnings

import mqdm as M

_warning_capture_refcount = 0


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


def _acquire_warning_capture() -> None:
    global _warning_capture_refcount
    if _warning_capture_refcount == 0:
        warnings.simplefilter("default")
        logging.captureWarnings(True)
    _warning_capture_refcount += 1


def _release_warning_capture() -> None:
    global _warning_capture_refcount
    if _warning_capture_refcount == 0:
        return
    _warning_capture_refcount -= 1
    if _warning_capture_refcount == 0:
        logging.captureWarnings(False)


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

def _install_from_config(cfg: dict | None) -> None:
    """Internal: install handler in workers using stored runtime logging config."""
    if not cfg:
        return
    M._current_runtime().install_logging(
        logger=None,
        level=cfg.get("level"),
        capture_warnings=cfg.get("capture_warnings", False),
        markup=cfg.get("markup", True),
        formatter=logging.Formatter(cfg["formatter_fmt"], cfg.get("formatter_datefmt")) 
                  if cfg.get("formatter_fmt") else None,
    )
