import importlib
import sys
import mqdm
from mqdm import utils
executor_mod = importlib.import_module('mqdm.executor')


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


def test_process_pool_compat_flag_matches_python_version():
    expected_module = 'mqdm._process_pool_compat' if sys.version_info < (3, 11) else 'mqdm._process_pool_keyboard'
    assert executor_mod.process_worker_keyboard_interrupt.__module__ == expected_module
