import dataclasses
from typing import Type
from functools import wraps
import multiprocessing as mp
from multiprocessing.managers import BaseProxy, SyncManager
import multiprocessing.managers
import mqdm
import rich
from rich import progress
from .utils import T_POOL_MODE, _RedirectIO


def get_progress_cls(pool_mode: T_POOL_MODE=None):
    if pool_mode == 'process':
        return get_manager().mqdm_Progress
    return Progress

class Progress(progress.Progress):
    multiprocess = False

    def __init__(self, *columns, _tasks=None, _task_index=None, **kw):
        super().__init__(*columns, **kw)

        # save init options in case we need to recreate the object in a different process
        self._init_options = kw
        # load serialized tasks from another progress object
        if _tasks is not None:
            self._tasks = {task_id: self._load_task(**task) for task_id, task in _tasks.items()}
        self._task_index = progress.TaskID(_task_index or 0)

    def print(self, *args, **kw):
        """Print to the console."""
        rich.print(*args, **kw)

    @wraps(progress.Progress.update)
    def update(self, task_id, **kw):
        if 'description' in kw and kw['description'] is None:  # ignore None descriptions
            kw.pop('description')
        return super().update(task_id, **kw)
    
    # def stop(self):
    #     if self.live.is_started:                    
    #         self.refresh()
    #         super().stop()

    def pop_task(self, task_id, remove=None):
        """Close a task and return its serialized data."""
        try:
            data = self.dump_task(task_id)
            self.stop_task(task_id)
            if remove is None:
                remove = self._tasks[task_id].fields.get('transient', False)
            if remove:
                self.remove_task(task_id)
            return data
        except KeyError as e:
            pass

    # convert to multiprocessing proxy

    def convert_proxy(self) -> 'ProgressProxy':
        """Convert to a multiprocessing proxy object so methods can be called in another process."""
        # get current state and cleanup
        started = self.live.is_started
        tasks = self.dump_tasks()
        for task_id in tasks:
            self.remove_task(task_id)
        started or self.start()
        self.refresh()
        self.stop()

        # create proxy
        proxy = get_manager().mqdm_Progress(
            *self.columns,
            _tasks=tasks,
            _task_index=self._task_index,
            **self._init_options,
        )
        proxy.multiprocess = True
        if started:
            proxy.start()
        return proxy
    
    # def get_task_attr(self, task_id, attr, default=None):
    #     task = self._tasks[task_id]
    #     try:
    #         return getattr(task, attr)
    #     except AttributeError:
    #         return task.fields.get(attr, default)

    def dump_tasks(self):
        with self._lock:
            return {task_id: self._dump_task(task_id) for task_id in self._tasks}

    def dump_task(self, task_id):
        with self._lock:
            return self._dump_task(task_id)

    def _dump_task(self, task_id):
        task = self._tasks[task_id]
        task = {k.name: getattr(task, k.name) for k in dataclasses.fields(task) if not k.name.startswith('_')}
        return task
    
    def _load_task(self, *, start_time=None, stop_time=None, **data):
        task = progress.Task(_get_time=self.get_time, _lock=self._lock, **data)
        task.start_time = start_time
        task.stop_time = stop_time
        return task

    def load_task(self, task: dict, start=True):
        with self._lock:
            task = self._load_task(**task)
            self._tasks[task.id] = task
            if task.id >= self._task_index:
                self._task_index = progress.TaskID(task.id+1)
        if start:
            self.start_task(task.id)




def proxymethod(func):
    name = func.__name__
    @wraps(func)
    def _call(self, *a, **kw):
        return self._callmethod(name, a, kw)
    _call._is_exposed_ = True
    return _call


class ProgressProxy(BaseProxy):
    multiprocess = True
    # def __init__(self, *args, **kw):
    #     console = rich.get_console()
    #     self._redirect_io = _RedirectIO(console)
    #     self._redirect_io.enable()
    #     super().__init__(*args, **kw)

    start_task = proxymethod(Progress.start_task)
    stop_task = proxymethod(Progress.stop_task)
    add_task = proxymethod(Progress.add_task)
    remove_task = proxymethod(Progress.remove_task)
    update = proxymethod(Progress.update)
    refresh = proxymethod(Progress.refresh)
    start = proxymethod(Progress.start)
    stop = proxymethod(Progress.stop)
    print = proxymethod(Progress.print)
    # get_task_attr = proxymethod(Progress.get_task_attr)
    dump_task = proxymethod(Progress.dump_task)
    dump_tasks = proxymethod(Progress.dump_tasks)
    load_task = proxymethod(Progress.load_task)
    pop_task = proxymethod(Progress.pop_task)

ProgressProxy._exposed_ = tuple(k for k, v in ProgressProxy.__dict__.items() if getattr(v, '_is_exposed_', False))

multiprocessing.managers.ProgressProxy = ProgressProxy  # Can't pickle - attribute lookup ProgressProxy on multiprocessing.managers failed


class MqdmManager(SyncManager):
    mqdm_Progress: Type[ProgressProxy]
MqdmManager.register('mqdm_Progress', Progress, ProgressProxy)

def get_manager() -> MqdmManager:
    if getattr(mqdm, '_manager', None) is not None:
        return mqdm._manager
    mqdm._manager = manager = MqdmManager()
    manager.start()
    return manager
