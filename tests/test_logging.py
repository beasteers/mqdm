import logging
import warnings

import mqdm as M
from mqdm import capture_warnings, install_logging, release_warnings, uninstall_logging
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
    handler = next(h for h in root.handlers if isinstance(h, MQDMHandler) and h.runtime is M._current_runtime())
    assert handler.level == logging.INFO
    uninstall_logging()
    n2 = _count_mqdm_handlers(root)
    assert n2 == n0


def test_install_logging_binds_handler_to_runtime():
    root = logging.getLogger()
    runtime = M.Runtime()
    uninstall_logging()

    handler = runtime.install_logging(logger=root, level=logging.INFO)

    assert isinstance(handler, MQDMHandler)
    handlers = [h for h in root.handlers if isinstance(h, MQDMHandler) and h.runtime is runtime]
    assert handlers == [handler]
    assert handler in runtime.logging_handlers
    assert runtime.logging_config["level"] == logging.INFO

    runtime.uninstall_logging(logger=root)
    assert handler not in root.handlers
    assert runtime.logging_config is None


def test_install_logging_does_not_capture_warnings_by_default():
    runtime = M.Runtime()
    uninstall_logging(runtime=runtime)

    original_showwarning = warnings.showwarning
    try:
        runtime.install_logging()
        assert warnings.showwarning is original_showwarning
        assert runtime.capture_warnings is False
        assert runtime.logging_config["capture_warnings"] is False
    finally:
        runtime.uninstall_logging()


def test_warning_capture_is_released_only_after_last_runtime_uninstalls():
    rt1 = M.Runtime()
    rt2 = M.Runtime()

    uninstall_logging(runtime=rt1)
    uninstall_logging(runtime=rt2)

    original_showwarning = warnings.showwarning
    try:
        rt1.install_logging(capture_warnings=True)
        rt2.install_logging(capture_warnings=True)
        assert warnings.showwarning.__module__ == "logging"

        rt1.uninstall_logging()
        assert warnings.showwarning.__module__ == "logging"

        rt2.uninstall_logging()
        assert warnings.showwarning is original_showwarning
    finally:
        rt1.uninstall_logging()
        rt2.uninstall_logging()


def test_capture_warning_helpers_toggle_runtime_state():
    runtime = M.Runtime()
    uninstall_logging(runtime=runtime)

    original_showwarning = warnings.showwarning
    try:
        capture_warnings(runtime=runtime)
        assert runtime.capture_warnings is True
        assert warnings.showwarning.__module__ == "logging"

        release_warnings(runtime=runtime)
        assert runtime.capture_warnings is False
        assert warnings.showwarning is original_showwarning
    finally:
        release_warnings(runtime=runtime)
        uninstall_logging(runtime=runtime)


def test_ensure_on_logger_is_idempotent_and_updates_markup():
    root = logging.getLogger()
    runtime = M.Runtime()
    uninstall_logging(runtime=runtime)

    try:
        first = MQDMHandler.ensure_on_logger(root, runtime, markup=True)
        second = MQDMHandler.ensure_on_logger(root, runtime, markup=False)

        assert first is second
        assert second.markup is False
        assert sum(isinstance(h, MQDMHandler) and h.runtime is runtime for h in root.handlers) == 1
    finally:
        uninstall_logging(runtime=runtime)
