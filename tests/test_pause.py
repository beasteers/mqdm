import mqdm as M


def test_pause_context_manager_sets_event_after_exit():
    # Event should be set after leaving the pause context
    with M.pause(True):
        pass
    assert getattr(M, '_pause_event', None) is not None
    assert M._pause_event.is_set()
