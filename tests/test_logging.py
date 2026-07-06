import logging
import warnings

import mqdm as M
import mqdm.runtime as runtime_mod
from mqdm import install_logging, uninstall_logging
from mqdm import _logging as logging_mod
from mqdm._logging import MQDMHandler, capture_warnings, release_warnings


def _reset_warning_capture_state():
    warnings.showwarning = warnings._showwarning_orig
    logging_mod._warning_capture_refcount = 0
    logging_mod._warnings_showwarning = None


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


def test_install_logging_defaults_to_process_only_warning_capture():
    runtime = M.Runtime()
    uninstall_logging(runtime=runtime)
    _reset_warning_capture_state()

    original_showwarning = warnings.showwarning
    try:
        runtime.install_logging()
        assert warnings.showwarning is original_showwarning
        assert runtime.capture_warnings is False
        assert runtime.logging_config["capture_warnings"] == "process"
    finally:
        runtime.uninstall_logging()


def test_warning_capture_is_released_only_after_last_runtime_uninstalls():
    rt1 = M.Runtime()
    rt2 = M.Runtime()

    uninstall_logging(runtime=rt1)
    uninstall_logging(runtime=rt2)
    _reset_warning_capture_state()

    original_showwarning = warnings.showwarning
    try:
        rt1.install_logging(capture_warnings=True)
        rt2.install_logging(capture_warnings=True)
        assert warnings.showwarning is logging_mod._showwarning

        rt1.uninstall_logging()
        assert warnings.showwarning is logging_mod._showwarning

        rt2.uninstall_logging()
        assert warnings.showwarning is original_showwarning
    finally:
        rt1.uninstall_logging()
        rt2.uninstall_logging()


def test_process_only_warning_capture_activates_in_worker_install(monkeypatch):
    runtime = M.Runtime()
    uninstall_logging(runtime=runtime)
    _reset_warning_capture_state()

    original_showwarning = warnings.showwarning
    try:
        runtime.install_logging(level=logging.INFO)
        monkeypatch.setattr(runtime_mod.utils, "is_main_process", lambda: False)
        runtime.install_pool_worker()
        assert warnings.showwarning is logging_mod._showwarning
        assert runtime.capture_warnings is True
    finally:
        release_warnings(runtime=runtime)
        uninstall_logging(runtime=runtime)
        assert warnings.showwarning is original_showwarning


def test_worker_install_respects_capture_warnings_false():
    runtime = M.Runtime()
    uninstall_logging(runtime=runtime)
    _reset_warning_capture_state()

    original_showwarning = warnings.showwarning
    try:
        runtime.install_logging(level=logging.INFO, capture_warnings=False)
        runtime.install_pool_worker()
        assert warnings.showwarning is original_showwarning
        assert runtime.capture_warnings is False
    finally:
        uninstall_logging(runtime=runtime)


def test_runtime_pickle_resets_process_local_warning_capture_state():
    runtime = M.Runtime()
    runtime.capture_warnings = True
    runtime.logging_config = {"capture_warnings": True}

    state = runtime.__getstate__()

    assert state["capture_warnings"] is False
    assert state["logging_config"]["capture_warnings"] is True


def test_capture_warning_helpers_toggle_runtime_state():
    runtime = M.Runtime()
    uninstall_logging(runtime=runtime)
    _reset_warning_capture_state()

    original_showwarning = warnings.showwarning
    try:
        capture_warnings(runtime=runtime)
        assert runtime.capture_warnings is True
        assert warnings.showwarning is logging_mod._showwarning

        release_warnings(runtime=runtime)
        assert runtime.capture_warnings is False
        assert warnings.showwarning is original_showwarning
    finally:
        release_warnings(runtime=runtime)
        uninstall_logging(runtime=runtime)


def test_warning_helpers_are_not_part_of_top_level_api():
    assert not hasattr(M, "capture_warnings")
    assert not hasattr(M, "release_warnings")


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
