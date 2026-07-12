import mqdm as M
import pytest


def test_bar_close_open_preserves_task_state():
    runtime = M.Runtime()
    bar = M.mqdm(total=5, desc="work", runtime=runtime)

    try:
        bar.update(advance=2)
        bar.close()

        assert runtime.pbar is None
        assert not runtime.instances
        assert bar._task_dict["completed"] == 2
        assert bar._task_dict["total"] == 5
        assert bar._task_dict["description"] == "work"

        bar.open()

        assert runtime.pbar is not None
        assert runtime.get_instance() is bar
        restored = runtime.pbar.dump_task(bar.task_id)
        assert restored["completed"] == 2
        assert restored["total"] == 5
        assert restored["description"] == "work"
    finally:
        bar.close()


def test_bar_close_remove_true_still_allows_restore():
    runtime = M.Runtime()
    bar = M.mqdm(total=3, runtime=runtime, leave=False)

    try:
        bar.update(advance=1)
        task_id = bar.task_id
        bar.close(remove=True)

        assert runtime.pbar is None
        assert bar._task_dict["id"] == task_id
        assert bar._task_dict["completed"] == 1

        bar.open()

        restored = runtime.pbar.dump_task(task_id)
        assert restored["completed"] == 1
        assert restored["fields"]["transient"] is True
    finally:
        bar.close()


def test_bar_open_close_tracks_runtime_instances():
    runtime = M.Runtime()
    bar = M.mqdm(total=1, runtime=runtime)

    try:
        assert len(runtime.instances) == 1

        bar.close()
        assert not runtime.instances

        bar.open()
        assert len(runtime.instances) == 1
        assert runtime.get_instance() is bar
    finally:
        bar.close()


def test_bar_close_flushes_buffered_fast_advance():
    runtime = M.Runtime(backend_options={'refresh_per_second': 0.1})
    bar = M.mqdm(total=5, runtime=runtime)

    try:
        bar._fast_advance(n=1, flush=True)
        bar._fast_advance(n=2)

        assert runtime.pbar.dump_task(bar.task_id)["completed"] == 1

        bar.close()

        assert bar._task_dict["completed"] == 3

        bar.open()

        restored = runtime.pbar.dump_task(bar.task_id)
        assert restored["completed"] == 3
    finally:
        bar.close()


def test_bar_close_flush_does_not_wait_on_pause():
    runtime = M.Runtime(backend_options={'refresh_per_second': 0.1})
    bar = M.mqdm(total=5, runtime=runtime)

    try:
        bar._fast_advance(n=2)

        def fail(*a, **kw):
            raise AssertionError("close flush should not wait on pause state")

        runtime.pause_event.wait = fail
        bar.close()

        assert bar._task_dict["completed"] == 2
    finally:
        bar.close()


def test_bar_detached_updates_restore_on_reopen():
    runtime = M.Runtime()
    bar = M.mqdm(total=5, desc="work", runtime=runtime)

    try:
        bar.update(advance=2)
        bar.close()

        bar.set(advance=1, description="later", visible=False, transient=True)

        assert bar._task_dict["completed"] == 3
        assert bar._task_dict["description"] == "later"
        assert bar._task_dict["visible"] is False
        assert bar._task_dict["fields"]["transient"] is True

        bar.open()

        restored = runtime.pbar.dump_task(bar.task_id)
        assert restored["completed"] == 3
        assert restored["description"] == "later"
        assert restored["visible"] is False
        assert restored["fields"]["transient"] is True
    finally:
        bar.close()


def test_bar_detached_fast_advance_updates_snapshot_description():
    runtime = M.Runtime()
    bar = M.mqdm(total=5, runtime=runtime)

    try:
        bar.set(description=lambda x, i: f"{x}:{i}")
        bar.close()

        bar._fast_advance(n=2, arg="alpha", flush=True, wait=False)

        assert bar._task_dict["completed"] == 2
        assert bar._task_dict["description"] == "alpha:1"

        bar.open()

        restored = runtime.pbar.dump_task(bar.task_id)
        assert restored["completed"] == 2
        assert restored["description"] == "alpha:1"
    finally:
        bar.close()


def test_bar_live_fast_advance_updates_description():
    runtime = M.Runtime()
    bar = M.mqdm(total=5, runtime=runtime)

    try:
        bar.set(description=lambda x, i: f"{x}:{i}")
        bar._fast_advance(n=2, arg="alpha", flush=True, wait=False)

        restored = runtime.pbar.dump_task(bar.task_id)
        assert restored["completed"] == 2
        assert restored["description"] == "alpha:1"
    finally:
        bar.close()


def test_public_advance_increments_and_resolves_dynamic_description():
    # Exercises the public fast path: advance(n, arg) increments and, when an
    # `arg` is given, refreshes a dynamic description via the same callback the
    # iteration path uses. A long throttle means only forced flushes land, so
    # the assertions depend on the flushed state, not on timing.
    runtime = M.Runtime(backend_options={'refresh_per_second': 0.1})
    bar = M.mqdm(total=5, runtime=runtime)

    try:
        bar.set(description=lambda x, i: f"{x}:{i}")

        assert bar.advance(2, arg="alpha") is bar  # returns self for chaining
        bar.advance(1)                             # increment only, stays buffered

        bar.close()  # flushes the buffered remainder

        assert bar._task_dict["completed"] == 3
        assert bar._task_dict["description"] == "alpha:1"
    finally:
        bar.close()


def test_constructor_task_kw_supports_custom_task_fields():
    runtime = M.Runtime()
    bar = M.mqdm(total=2, runtime=runtime, task_kw={"flavor": "mint"})

    try:
        restored = runtime.pbar.dump_task(bar.task_id)
        assert restored["fields"]["flavor"] == "mint"
    finally:
        bar.close()


def test_constructor_explicit_aliases_override_task_kw():
    runtime = M.Runtime()
    bar = M.mqdm(total=2, runtime=runtime, leave=True, bytes=True, task_kw={"transient": True, "bytes": False})

    try:
        restored = runtime.pbar.dump_task(bar.task_id)
        assert restored["fields"]["transient"] is False
        assert restored["fields"]["bytes"] is True
    finally:
        bar.close()


def test_constructor_leave_overrides_conflicting_transient():
    bar = M.mqdm(total=1, disable=True, leave=False, transient=False)

    assert bar._process_args(leave=False, transient=False)["transient"] is True


def test_bar_del_swallows_late_close_errors():
    bar = M.mqdm(disable=True)

    def fail_close(remove=None):
        raise KeyError(1)

    bar.close = fail_close

    bar.__del__()
