import mqdm as M
from mqdm._logging import MQDMHandler


def test_pause_context_manager_sets_event_after_exit():
    with M.pause(True):
        pass
    assert M._current_runtime().pause_event.is_set()


def test_sustain_is_nested():
    runtime = M._current_runtime()
    original_depth = runtime._sustain_depth

    try:
        with M.sustain():
            runtime = M._current_runtime()
            assert runtime._sustain_depth == 1
            with M.sustain():
                runtime = M._current_runtime()
                assert runtime._sustain_depth == 2
            runtime = M._current_runtime()
            assert runtime._sustain_depth == 1
        runtime = M._current_runtime()
        assert runtime._sustain_depth == 0
    finally:
        runtime._sustain_depth = original_depth


def test_runtime_atexit_clears_private_state():
    runtime = M.Runtime()
    bar = M.mqdm(total=1, runtime=runtime)

    assert runtime.pbar is not None
    assert runtime.instances

    runtime.atexit()

    assert runtime.pbar is None
    assert not runtime.instances
    assert runtime.command_dispatch is None


def test_runtime_atexit_uninstalls_logging():
    runtime = M.Runtime()
    runtime.install_logging(capture_warnings=True)

    assert any(isinstance(h, MQDMHandler) and h.runtime is runtime for h in __import__("logging").getLogger().handlers)
    assert runtime.capture_warnings is True

    runtime.atexit()

    assert not any(isinstance(h, MQDMHandler) and h.runtime is runtime for h in __import__("logging").getLogger().handlers)
    assert runtime.capture_warnings is False
    assert runtime.logging_config is None
