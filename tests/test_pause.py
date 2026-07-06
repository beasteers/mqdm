import mqdm as M


def test_pause_context_manager_sets_event_after_exit():
    # Event should be set after leaving the pause context
    with M.pause(True):
        pass
    assert M._runtime.pause_event.is_set()


def test_runtime_holds_private_state():
    assert M._runtime.pause_event is not None
    assert M._runtime.shutdown_event is not None
    assert M._runtime.instances is not None
