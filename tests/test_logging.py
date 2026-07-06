import logging
import warnings

import mqdm as M
from mqdm import install_logging, uninstall_logging
from mqdm._logging import MQDMHandler


def _count_mqdm_handlers(logger=None):
    logger = logger or logging.getLogger()
    return sum(isinstance(h, MQDMHandler) for h in logger.handlers)


def test_install_uninstall_logging_handler_idempotent():
    uninstall_logging()
    root = logging.getLogger()
    n0 = _count_mqdm_handlers(root)
    install_logging(level=logging.INFO)
    install_logging(level=logging.INFO)
    n1 = _count_mqdm_handlers(root)
    assert n1 == n0 + 1
    uninstall_logging()
    n2 = _count_mqdm_handlers(root)
    assert n2 == n0


def test_install_logging_binds_handler_to_runtime():
    root = logging.getLogger()
    runtime = M.Runtime()
    uninstall_logging()

    install_logging(level=logging.INFO, runtime=runtime)

    handlers = [h for h in root.handlers if isinstance(h, MQDMHandler) and h.runtime is runtime]
    assert len(handlers) == 1
    assert handlers[0] in runtime.logging_handlers
    assert runtime.logging_config["level"] == logging.INFO

    uninstall_logging(runtime=runtime)
    assert handlers[0] not in root.handlers
    assert runtime.logging_config is None


def test_warning_capture_is_released_only_after_last_runtime_uninstalls():
    rt1 = M.Runtime()
    rt2 = M.Runtime()

    uninstall_logging(runtime=rt1)
    uninstall_logging(runtime=rt2)

    original_showwarning = warnings.showwarning
    try:
        install_logging(runtime=rt1)
        install_logging(runtime=rt2)
        assert warnings.showwarning.__module__ == "logging"

        uninstall_logging(runtime=rt1)
        assert warnings.showwarning.__module__ == "logging"

        uninstall_logging(runtime=rt2)
        assert warnings.showwarning is original_showwarning
    finally:
        uninstall_logging(runtime=rt1)
        uninstall_logging(runtime=rt2)
