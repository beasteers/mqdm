import mqdm
import mqdm.parallel.pool as pool_mod
import pytest
from mqdm import utils


def test_args_basic_call_and_from_item():
    calls = []

    def fn(a, b=0, **kw):
        calls.append((a, b, kw))
        print(a, b, kw)
        return a + b + kw.get('c', 0)

    a0 = utils.args(1, b=2)
    assert a0(fn, c=3) == 6
    assert calls[-1] == (1, 2, {'c': 3})

    a1 = utils.args.from_item(a0, b=4, d=5)  # extends parent
    assert a1(fn, c=1) == 1 + 4 + 1
    assert calls[-1] == (1, 4, {'d': 5, 'c': 1})


def test_try_len_handles_various_iterables():
    assert utils.try_len(5) == 5
    assert utils.try_len([1, 2, 3]) == 3
    assert utils.try_len(None, default=7) == 7

    class HasLengthHint:
        def __iter__(self):
            yield from range(2)

        def __length_hint__(self):
            return 2

    assert utils.try_len(HasLengthHint()) == 2


def test_fopen_iterates_lines(tmp_path):
    p = tmp_path / 'data.txt'
    p.write_text('a\nbb\nccc\n')

    # Use a disabled mqdm to avoid console interaction in tests
    bar = mqdm.mqdm(disable=True)
    lines = []
    with utils.fopen(p, 'r', pbar=bar) as f:
        for line in f:
            lines.append(line)

    assert ''.join(lines) == 'a\nbb\nccc\n'


def test_fopen_flushes_final_buffer_with_external_bar(tmp_path):
    p = tmp_path / 'data.txt'
    p.write_text('abc\n')

    runtime = mqdm.Runtime(backend_options={'refresh_per_second': 0.1})
    bar = mqdm.mqdm(total=0, runtime=runtime, task_kw={'bytes': True})

    try:
        bar.open()
        with utils.fopen(p, 'r', pbar=bar) as f:
            assert next(f) == 'abc\n'
            with pytest.raises(StopIteration):
                next(f)

        assert runtime.pbar.dump_task(bar.task_id)['completed'] == p.stat().st_size
    finally:
        bar.close()


def test_fopen_text_mode_tracks_utf8_bytes(tmp_path):
    p = tmp_path / 'data.txt'
    p.write_text('a\né\n', encoding='utf-8')

    runtime = mqdm.Runtime(backend_options={'refresh_per_second': 0.1})
    bar = mqdm.mqdm(total=0, runtime=runtime, task_kw={'bytes': True})

    try:
        bar.open()
        with utils.fopen(p, 'r', pbar=bar) as f:
            assert list(f) == ['a\n', 'é\n']

        assert runtime.pbar.dump_task(bar.task_id)['completed'] == p.stat().st_size
    finally:
        bar.close()


class _FakeProc:
    def __init__(self, alive_after_join):
        self._alive = True
        self._alive_after_join = alive_after_join
        self.joined_timeout = None
        self.signalled = None

    def join(self, timeout=None):
        self.joined_timeout = timeout
        self._alive = self._alive_after_join

    def is_alive(self):
        return self._alive

    def terminate(self):
        self.signalled = 'terminate'

    def kill(self):
        self.signalled = 'kill'


class _FakeExecutor:
    def __init__(self, procs=()):
        self._processes = {i: p for i, p in enumerate(procs)}
        self.shutdown_calls = []

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdown_calls.append((wait, cancel_futures))


def test_shutdown_for_interrupt_signals_only_stragglers():
    exited = _FakeProc(alive_after_join=False)  # unwinds during grace
    stuck = _FakeProc(alive_after_join=True)    # still running after grace
    ex = _FakeExecutor([exited, stuck])

    pool_mod._shutdown_for_interrupt(
        ex, 'process', mqdm._current_runtime(), op='terminate', grace=0.01,
    )

    assert ex.shutdown_calls == [(False, True)]  # non-blocking, drops queued
    assert exited.signalled is None              # exited on its own
    assert stuck.signalled == 'terminate'        # only the straggler is signalled
    assert stuck.joined_timeout is not None       # grace join was attempted


def test_shutdown_for_interrupt_kill_op():
    stuck = _FakeProc(alive_after_join=True)
    ex = _FakeExecutor([stuck])
    pool_mod._shutdown_for_interrupt(
        ex, 'process', mqdm._current_runtime(), op='kill', grace=0.01,
    )
    assert stuck.signalled == 'kill'


def test_shutdown_for_interrupt_non_process_leaves_procs_alone():
    proc = _FakeProc(alive_after_join=True)
    ex = _FakeExecutor([proc])
    pool_mod._shutdown_for_interrupt(ex, 'thread', mqdm._current_runtime())
    assert ex.shutdown_calls == [(False, True)]
    assert proc.signalled is None  # threads can't be force-stopped
