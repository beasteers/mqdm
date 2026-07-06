import mqdm as M


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
    runtime = M.Runtime()
    bar = M.mqdm(total=5, runtime=runtime, refresh_per_second=0.1)

    try:
        bar.fast_advance(n=1, flush=True)
        bar.fast_advance(n=2)

        assert runtime.pbar.dump_task(bar.task_id)["completed"] == 1

        bar.close()

        assert bar._task_dict["completed"] == 3

        bar.open()

        restored = runtime.pbar.dump_task(bar.task_id)
        assert restored["completed"] == 3
    finally:
        bar.close()


def test_bar_close_flush_does_not_wait_on_pause():
    runtime = M.Runtime()
    bar = M.mqdm(total=5, runtime=runtime, refresh_per_second=0.1)

    try:
        bar.fast_advance(n=2)

        def fail():
            raise AssertionError("close flush should not wait on pause state")

        runtime.ttl_pause_wait = fail
        bar.close()

        assert bar._task_dict["completed"] == 2
    finally:
        bar.close()
