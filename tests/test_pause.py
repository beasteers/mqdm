import mqdm as M


def test_pause_context_manager_sets_event_after_exit():
    with M.pause(True):
        pass
    assert M._runtime.pause_event.is_set()

def test_runtime_atexit_clears_private_state():
    runtime = M.Runtime()
    bar = M.mqdm(total=1, runtime=runtime)

    assert runtime.pbar is not None
    assert runtime.instances

    runtime.atexit()

    assert runtime.pbar is None
    assert not runtime.instances
    assert runtime.manager is None
