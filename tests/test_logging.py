import logging
from types import SimpleNamespace
import warnings

import mqdm as M
import mqdm.runtime as runtime_mod
from mqdm import install_logging, uninstall_logging
from mqdm.utils import _logging as logging_mod
from mqdm.utils._logging import MQDMHandler, capture_warnings, release_warnings


class _RecordingRuntime(M.Runtime):
    def __init__(self):
        super().__init__()
        self.events = []

    def emit(self, event_type: str, **data):
        self.events.append((event_type, data))
        return super().emit(event_type, **data)


def _reset_warning_capture_state():
    logging.captureWarnings(False)
    logging_mod._warning_capture_refcount = 0


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
    assert runtime.logging_config["logger_name"] == root.name
    assert runtime.logging_config["level"] == logging.INFO

    runtime.uninstall_logging(logger=root)
    assert handler not in root.handlers
    assert runtime.logging_config is None


def test_install_logging_level_updates_logger_effective_level():
    runtime = M.Runtime()
    root = logging.getLogger()
    old_level = root.level
    runtime.uninstall_logging()

    try:
        root.setLevel(logging.WARNING)
        runtime.install_logging(logger=root, level=logging.INFO)
        assert root.level == logging.INFO
        assert logging.getLogger("mqdm.test").isEnabledFor(logging.INFO)
    finally:
        runtime.uninstall_logging(logger=root)
        root.setLevel(old_level)


def test_install_logging_defaults_to_process_only_warning_capture():
    runtime = M.Runtime()
    runtime.uninstall_logging()
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

    rt1.uninstall_logging()
    rt2.uninstall_logging()
    _reset_warning_capture_state()

    original_showwarning = warnings.showwarning
    try:
        rt1.install_logging(capture_warnings=True)
        rt2.install_logging(capture_warnings=True)
        assert warnings.showwarning is not original_showwarning

        rt1.uninstall_logging()
        assert warnings.showwarning is not original_showwarning

        rt2.uninstall_logging()
        assert warnings.showwarning is original_showwarning
    finally:
        rt1.uninstall_logging()
        rt2.uninstall_logging()


def test_process_only_warning_capture_activates_in_worker_install(monkeypatch):
    runtime = M.Runtime()
    runtime.uninstall_logging()
    _reset_warning_capture_state()

    original_showwarning = warnings.showwarning
    try:
        runtime.install_logging(level=logging.INFO)
        monkeypatch.setattr(runtime_mod.utils, "is_main_process", lambda: False)
        runtime.install_pool_worker()
        assert warnings.showwarning is not original_showwarning
        assert runtime.capture_warnings is True
    finally:
        release_warnings(runtime=runtime)
        runtime.uninstall_logging()
        assert warnings.showwarning is original_showwarning


def test_process_worker_replays_named_logger(monkeypatch):
    runtime = M.Runtime()
    logger = logging.getLogger("mqdm.worker.target")
    runtime.uninstall_logging()

    try:
        runtime.install_logging(logger=logger, level=logging.INFO)
        monkeypatch.setattr(runtime_mod.utils, "is_main_process", lambda: False)
        runtime.install_pool_worker()
        handlers = [h for h in logger.handlers if isinstance(h, MQDMHandler) and h.runtime is runtime]
        assert len(handlers) == 1
        assert runtime.logging_config["logger_name"] == logger.name
    finally:
        runtime.uninstall_logging()


def test_worker_install_respects_capture_warnings_false():
    runtime = M.Runtime()
    runtime.uninstall_logging()
    _reset_warning_capture_state()

    original_showwarning = warnings.showwarning
    try:
        runtime.install_logging(level=logging.INFO, capture_warnings=False)
        runtime.install_pool_worker()
        assert warnings.showwarning is original_showwarning
        assert runtime.capture_warnings is False
    finally:
        runtime.uninstall_logging()


def test_runtime_pickle_resets_process_local_warning_capture_state():
    runtime = M.Runtime()
    runtime.capture_warnings = True
    runtime.logging_config = {"capture_warnings": True}

    state = runtime.__getstate__()

    assert state["capture_warnings"] is False
    assert state["logging_config"]["capture_warnings"] is True


def test_capture_warning_helpers_toggle_runtime_state():
    runtime = M.Runtime()
    runtime.uninstall_logging()
    _reset_warning_capture_state()

    original_showwarning = warnings.showwarning
    try:
        capture_warnings(runtime=runtime)
        assert runtime.capture_warnings is True
        assert warnings.showwarning is not original_showwarning

        release_warnings(runtime=runtime)
        assert runtime.capture_warnings is False
        assert warnings.showwarning is original_showwarning
    finally:
        release_warnings(runtime=runtime)
        runtime.uninstall_logging()


def test_warning_helpers_are_not_part_of_top_level_api():
    assert not hasattr(M, "capture_warnings")
    assert not hasattr(M, "release_warnings")


def test_ensure_on_logger_is_idempotent_and_updates_markup():
    root = logging.getLogger()
    runtime = M.Runtime()
    runtime.uninstall_logging()

    try:
        first = MQDMHandler.ensure_on_logger(root, runtime, markup=True)
        second = MQDMHandler.ensure_on_logger(root, runtime, markup=False)

        assert first is second
        assert second.markup is False
        assert sum(isinstance(h, MQDMHandler) and h.runtime is runtime for h in root.handlers) == 1
    finally:
        runtime.uninstall_logging()


def test_uninstall_logging_without_logger_removes_named_logger_handlers():
    runtime = M.Runtime()
    logger = logging.getLogger("mqdm.named.cleanup")
    runtime.uninstall_logging()

    runtime.install_logging(logger=logger, level=logging.INFO)
    assert any(isinstance(h, MQDMHandler) and h.runtime is runtime for h in logger.handlers)

    runtime.uninstall_logging()

    assert not any(isinstance(h, MQDMHandler) and h.runtime is runtime for h in logger.handlers)
    assert not list(runtime.logging_handlers)


def test_runtime_context_scopes_and_restores():
    runtime = M.Runtime()

    assert runtime.get_context() == {}

    with runtime.context(task="outer"):
        assert runtime.get_context() == {"task": "outer"}
        with runtime.context(worker=2):
            assert runtime.get_context() == {"task": "outer", "worker": 2}
        assert runtime.get_context() == {"task": "outer"}

    assert runtime.get_context() == {}


def test_logging_handler_routes_context_through_runtime_emit():
    runtime = _RecordingRuntime()
    logger = logging.getLogger("mqdm.test.context")
    runtime.uninstall_logging()

    try:
        runtime.install_logging(logger=logger, level=logging.INFO)
        with runtime.context(item_id=7, worker="w2"):
            logger.info("hello")
    finally:
        runtime.uninstall_logging()

    log_events = [event for event in runtime.events if event[0] == "log"]
    assert len(log_events) == 1
    _, payload = log_events[0]
    assert payload["context"] == {"item_id": 7, "worker": "w2"}
    assert "hello" in payload["message"]


def test_runtime_handle_event_print_accepts_rich_markup_kwargs(capsys):
    runtime = M.Runtime()

    runtime.handle_event("print", args=("[bold]hello[/bold]",), kw={"markup": True})

    assert "hello" in capsys.readouterr().out


def test_runtime_emit_routes_through_pbar():
    runtime = M.Runtime()
    calls = []
    runtime.pbar = SimpleNamespace(write=lambda *a, **kw: calls.append((a, kw)))

    runtime.emit("print", args=("hello",), kw={})

    assert calls == [(("hello",), {})]


def test_runtime_emit_falls_back_to_console_without_pbar(capsys):
    runtime = M.Runtime()
    runtime.pbar = None

    runtime.emit("print", args=("hello",), kw={})

    assert "hello" in capsys.readouterr().out
