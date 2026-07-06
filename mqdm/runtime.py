import atexit
import threading
import weakref
from collections import OrderedDict
from time import monotonic

import rich
from rich import progress

from . import progress_columns
from . import utils


_all_runtimes = weakref.WeakSet()
_LOCAL_EVENT_TYPE = type(threading.Event())


class Runtime:
    def __init__(self):
        self.pbar = None
        self.manager = None
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.shutdown_event = threading.Event()
        self.shutdown_event.set()
        self.instances = OrderedDict()
        self.logging_handlers = weakref.WeakSet()
        self.keep = False
        self.keep_depth = 0
        self.capture_warnings = False
        self.logging_config = None
        self.next_pause_check_time = 0
        self.pause_wait_ttl_seconds = 0.5
        _all_runtimes.add(self)

    def __getstate__(self):
        state = self.__dict__.copy()
        state['manager'] = None
        state['instances'] = OrderedDict()
        state['logging_handlers'] = None
        for key in ('pause_event', 'shutdown_event'):
            event = state.get(key)
            if isinstance(event, _LOCAL_EVENT_TYPE):
                state[f'{key}_is_set'] = event.is_set()
                state[key] = None
        return state

    def __setstate__(self, state):
        pause_event_is_set = state.pop('pause_event_is_set', True)
        shutdown_event_is_set = state.pop('shutdown_event_is_set', True)
        self.__dict__.update(state)
        if self.pause_event is None:
            self.pause_event = threading.Event()
            (self.pause_event.set if pause_event_is_set else self.pause_event.clear)()
        if self.shutdown_event is None:
            self.shutdown_event = threading.Event()
            (self.shutdown_event.set if shutdown_event_is_set else self.shutdown_event.clear)()
        self.instances = OrderedDict()
        self.logging_handlers = weakref.WeakSet()
        _all_runtimes.add(self)

    def prepare_pool_worker(self, pool_mode=None):
        self.get_pbar(pool_mode=pool_mode)
        self.pause_event.set()
        self.shutdown_event.set()

    def install_pool_worker(self):
        try:
            from ._logging import _install_from_config

            _install_from_config(self.logging_config)
        except Exception:
            pass

    def new_pbar(self, pool_mode=None, bytes=False, **kw):
        from . import proxy

        kw.setdefault('refresh_per_second', 8)
        columns = (
            "[progress.description]{task.description}",
            progress.BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.0f}%",
            progress_columns.MofNColumn(bytes=bytes),
            progress_columns.SpeedColumn(bytes=bytes),
            progress_columns.TimeElapsedColumn(compact=True),
            progress.TimeRemainingColumn(compact=True),
            progress.SpinnerColumn(),
        )
        if pool_mode == 'process':
            return self.get_manager().mqdm_Progress(*columns, **kw)
        return proxy.Progress(*columns, **kw)

    def get_pbar(self, pool_mode=None, start=True, **kw):
        pbar = self.pbar
        if pbar is None:
            pbar = self.pbar = self.new_pbar(pool_mode=pool_mode, **kw)
        elif pool_mode == 'process' and not pbar.multiprocess:
            pbar = self.pbar = pbar.convert_proxy(runtime=self)
        if start:
            pbar.start()
        return pbar

    def clear_pbar(self, strict=True, force=False, soft=False):
        if force:
            for bar_ref in reversed(list(self.instances.values())):
                bar = bar_ref()
                if bar is not None:
                    bar.close(remove=False)
                    bar.disable = True
            if self.pbar is not None:
                self.pbar.stop()
            self.pbar = None
        if self.instances:
            if strict:
                raise RuntimeError("Cannot clear progress bar while instances are still active.")
        elif not utils.is_main_process():
            if strict:
                raise RuntimeError("Cannot clear progress bar in a subprocess.")
        elif soft or self.keep:
            if self.pbar is not None:
                self.pbar.refresh()
        else:
            if self.pbar is not None:
                self.pbar.start()
                self.pbar.refresh()
                self.pbar.stop()
            self.pbar = None

    def add_instance(self, bar):
        self.instances.setdefault(hash(bar), weakref.ref(bar))
        return bar

    def remove_instance(self, bar):
        self.instances.pop(hash(bar), None)

    def get_instance(self, i=-1):
        try:
            return list(self.instances.values())[i]()
        except IndexError:
            raise IndexError(f'No progress bar found at index {i} in list of length {len(self.instances)}')

    def close_instances(self):
        for bar_ref in list(self.instances.values()):
            bar = bar_ref()
            if bar is not None:
                bar.close()
        self.instances.clear()

    def pause_wait(self):
        self.pause_event.wait()

    def ttl_pause_wait(self):
        now = monotonic()
        if now >= self.next_pause_check_time:
            self.next_pause_check_time = now + self.pause_wait_ttl_seconds
            self.pause_event.wait()

    def pause(self, paused=True):
        pbar = self.pbar
        prev_paused = getattr(pbar, 'paused', False)
        if pbar is not None:
            pbar.paused = paused
            if paused:
                pbar.stop()
                self.pause_event.clear()
            else:
                pbar.start()
                self.pause_event.set()
        return _pause_exit(prev_paused)

    def print(self, *args, **kw):
        if self.pbar is not None:
            return self.pbar.print(*args, **kw)
        return rich.print(*args, **kw)

    def install_worker_context(self, *, pbar, pause_event, shutdown_event, logging_config):
        self.pbar = pbar
        self.pause_event = pause_event
        self.shutdown_event = shutdown_event
        self.logging_config = logging_config

    def install_logging(self, logger=None, *, level=None, capture_warnings=False, markup=True, formatter=None):
        import logging as _logging
        from ._logging import MQDMHandler, capture_warnings as _capture_warnings, release_warnings as _release_warnings

        logger = logger or _logging.getLogger()
        handler = MQDMHandler.ensure_on_logger(logger, self, formatter=formatter, markup=markup)
        if level is not None:
            handler.setLevel(level)

        if capture_warnings:
            _capture_warnings(runtime=self)
        else:
            _release_warnings(runtime=self)

        self.logging_config = {
            "level": level,
            "markup": markup,
            "capture_warnings": capture_warnings,
            "formatter_fmt": (formatter._fmt if formatter else None),
            "formatter_datefmt": (formatter.datefmt if formatter else None),
        }
        return handler

    def uninstall_logging(self, logger=None):
        import logging as _logging
        from ._logging import MQDMHandler, release_warnings as _release_warnings

        logger = logger or _logging.getLogger()
        MQDMHandler.remove_from_logger(logger, self)
        if self.capture_warnings:
            _release_warnings(runtime=self)
        self.logging_config = None

    def get_manager(self):
        if self.manager is not None:
            return self.manager
        from .proxy import MqdmManager

        manager = MqdmManager()
        manager.start()
        self.manager = manager
        self.pause_event = manager.Event()
        self.pause_event.set()
        self.shutdown_event = manager.Event()
        self.shutdown_event.set()
        return manager

    def shutdown_manager(self):
        manager = self.manager
        if manager is None:
            return
        try:
            shutdown = getattr(manager, 'shutdown', None)
            if shutdown is not None:
                shutdown()
        finally:
            self.manager = None

    def atexit(self):
        self.close_instances()
        self.shutdown_manager()


_runtime = Runtime()


def _current_runtime():
    try:
        from .executor import _get_local

        return _get_local('runtime', _runtime)
    except Exception:
        return _runtime


class _pause_exit:
    def __init__(self, prev_paused):
        self.prev_paused = prev_paused
        _pause_exit.last = self

    def __enter__(self):
        pass

    def __exit__(self, c, exc, t):
        if not exc and not self.prev_paused and self is _pause_exit.last:
            _current_runtime().pause(False)


def _atexit_runtimes():
    for runtime in list(_all_runtimes):
        try:
            runtime.atexit()
        except Exception:
            pass


atexit.register(_atexit_runtimes)
