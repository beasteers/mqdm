import logging
import warnings
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


def _make_default_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def install(
    logger: logging.Logger = None,
    *,
    level: int = None,
    replace_root: bool = False,
    capture_warnings: bool = True,
    markup: bool = True,
    formatter: logging.Formatter | None = None,
    runtime=None,
) -> None:
    """Install an mqdm-aware logging handler on the root logger.

    - replace_root: if True, clears existing root handlers before adding ours.
    - capture_warnings: if True, directs Python warnings to the logging system.
    - formatter: optional logging.Formatter; a sensible default is used otherwise.

    Also stores minimal configuration so worker processes can mirror logging.
    """
    runtime = runtime or M._current_runtime()
    if logger is None:
        logger = logging.getLogger()
    if replace_root:
        logger.handlers.clear()

    # Avoid duplicate handlers for the same runtime; allow distinct runtimes.
    existing = next((h for h in logger.handlers if isinstance(h, MQDMHandler) and h.runtime is runtime), None)
    handler = existing or MQDMHandler(runtime, markup=markup)
    handler.setFormatter(formatter or getattr(handler, 'formatter', None) or _make_default_formatter())
    if not existing:
        logger.addHandler(handler)
        runtime.logging_handlers.add(handler)
    if level is not None:
        logger.setLevel(level)

    if capture_warnings:
        warnings.simplefilter("default")
        logging.captureWarnings(True)

    # Save minimal config for worker processes to mirror
    runtime.logging_config = {
        "level": level,
        "markup": markup,
        "capture_warnings": capture_warnings,
        "formatter_fmt": (formatter._fmt if formatter else None),
        "formatter_datefmt": (formatter.datefmt if formatter else None),
        "replace_root": False,  # never replace in workers by default
    }


def uninstall(*, logger: logging.Logger = None, runtime=None) -> None:
    """Remove MQDMHandler from the root logger and stop warning capture."""
    runtime = runtime or M._current_runtime()
    logger = logger or logging.getLogger()
    to_remove = [h for h in logger.handlers if isinstance(h, MQDMHandler) and h.runtime is runtime]
    for h in to_remove:
        logger.removeHandler(h)
        runtime.logging_handlers.discard(h)
    runtime.logging_config = None
    logging.captureWarnings(False)


def _install_from_config(cfg: dict | None) -> None:
    """Internal: install handler in workers using stored runtime logging config."""
    if not cfg:
        return
    formatter = None
    if cfg.get("formatter_fmt"):
        formatter = logging.Formatter(cfg["formatter_fmt"], cfg.get("formatter_datefmt"))
    install(
        level=cfg.get("level"),
        replace_root=cfg.get("replace_root", False),
        capture_warnings=cfg.get("capture_warnings", True),
        markup=cfg.get("markup", True),
        formatter=formatter,
        runtime=M._current_runtime(),
    )
