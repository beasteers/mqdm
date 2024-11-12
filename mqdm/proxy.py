from collections import deque
import dataclasses
import threading
from typing import Type
from functools import wraps
import multiprocessing as mp
from multiprocessing.managers import BaseProxy, SyncManager
import multiprocessing.managers
import rich
from rich import progress
from rich.progress import TaskID
from .executor import T_POOL_MODE
import mqdm as M


class Task(progress.Task):
    @property
    def speed(self):
        """Optional[float]: Get the estimated speed in steps per second."""
        if self.start_time is None:
            return None
        with self._lock:
            progress = self._progress
            if progress:
                total_time = progress[-1].timestamp - self.start_time
            elif self.finished:
                total_time = self.finished_time
            else:
                total_time = self.elapsed
            return self.completed / total_time if total_time else total_time

            # total_time = progress[-1].timestamp - progress[0].timestamp
            # if total_time == 0:
            #     return None
            # iter_progress = iter(progress)
            # next(iter_progress)
            # total_completed = sum(sample.completed for sample in iter_progress)
            # speed = total_completed / total_time
            # # if self.id == 0:
            # #     print(progress)
            # #     print("speed p", speed, total_completed, total_time)
            # return speed

    # def reset(self):
    #     super().reset()
    #     self._progress.append(progress.ProgressSample(self.start_time, self.completed))
    #     # self._progress.append(progress.ProgressSample(self.get_time(), self.completed))


class Progress(progress.Progress):
    multiprocess = False

    def __init__(self, *columns, _tasks=None, _task_index=None, _pause_event=None, **kw):
        super().__init__(*columns, **kw)

        # save init options in case we need to recreate the object in a different process
        self._init_options = kw
        # load serialized tasks from another progress object
        if _tasks is not None:
            self._tasks = {task_id: self._load_task(**task) for task_id, task in _tasks.items()}
        self._task_index = progress.TaskID(_task_index or 0)
        # self._pause_event = _pause_event
        # if self._pause_event is not None:  # is this necessary if start exists?
        #     self._pause_event.set()

    def print(self, *args, **kw):
        """Print to the console."""
        rich.print(*args, **kw)

    @wraps(progress.Progress.update)
    def update(self, task_id, **kw):
        if 'description' in kw and kw['description'] is None:  # ignore None descriptions
            kw.pop('description')
        return super().update(task_id, **kw)
    
    @wraps(progress.Progress.update)
    def update_(self, task_id, **kw):
        try:
            return self.update(task_id, **kw)
        except KeyError as e:
            pass

    def add_task(
        self,
        description: str='',
        start: bool = True,
        total: float|None = 100.0,
        completed: int = 0,
        visible: bool = True,
        **fields,
    ) -> progress.TaskID:
        with self._lock:
            task = self._new_task(description or '', start, total, completed, visible, **fields)
            self._tasks[task.id] = task
        self.refresh()
        return task.id

    def start_task(self, task_id: progress.TaskID) -> None:
        with self._lock:
            self._start_task(self._tasks[task_id])

    # def stop_task(self, task_id):
    #     return super().stop_task(task_id)

    def clear(self):
        """Clear the progress bar."""
        with self._lock:
            self._tasks.clear()
    
    # def start(self):
    #     if self._pause_event is not None:
    #         self._pause_event.set()
    #     super().start()
    
    # def stop(self):
    #     if self._pause_event is not None:
    #         self._pause_event.clear()
    #     super().stop()

    def pop_task(self, task_id, remove=None):
        """Close a task and return its serialized data."""
        try:
            self.stop_task(task_id)
            data = self.dump_task(task_id)
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
            return {task_id: self._dump_task(self._tasks[task_id]) for task_id in self._tasks}

    def dump_task(self, task_id):
        with self._lock:
            return self._dump_task(self._tasks[task_id])

    def _dump_task(self, task):
        d = {k.name: getattr(task, k.name) for k in dataclasses.fields(task) if not k.name.startswith('_')}
        d['_progress'] = []
        if task._progress:
            d['_progress'].append((task._progress[-1].timestamp, sum(s.completed for s in task._progress)))
        return d
    
    def _load_task(self, *, start_time=None, stop_time=None, start=True, _progress=None, **data):
        task = Task(_get_time=self.get_time, _lock=self._lock, **data)
        task.start_time = start_time
        task.stop_time = stop_time
        start and self._start_task(task)
        if _progress:
            task._progress = deque([progress.ProgressSample(*s) for s in _progress], maxlen=1000)
        return task
    
    def _start_task(self, task):
        if task.start_time is None:
            task.start_time = self.get_time()
        # if task.start_time is not None and not task._progress:
        #     task._progress.append(progress.ProgressSample(task.start_time, task.completed))

    def load_task(self, task: dict, start=True):
        with self._lock:
            task = self._load_task(start=start, **task)
            self._tasks[task.id] = task
            if task.id >= self._task_index:
                self._task_index = progress.TaskID(task.id+1)
        self.refresh()

    def _new_task(self, 
                  description: str='',
                  start: bool = True,
                  total: float|None = None,
                  completed: int = 0,
                  visible: bool = True,
                  **fields):
        task = Task(
            self._task_index,
            description,
            total,
            completed,
            visible=visible,
            fields=fields,
            _get_time=self.get_time,
            _lock=self._lock,
        )
        start and self._start_task(task)
        # task._progress.append(progress.ProgressSample(task.start_time or self.get_time(), task.completed))
        self._task_index = progress.TaskID(int(self._task_index) + 1)
        return task

    def new_task(self,
                  description: str='',
                  start: bool = True,
                  total: float|None = None,
                  completed: int = 0,
                  visible: bool = True,
                  **fields):
        with self._lock:
            return self._dump_task(self._new_task(description or '', start, total, completed, visible, **fields))



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
    update_ = proxymethod(Progress.update_)
    refresh = proxymethod(Progress.refresh)
    start = proxymethod(Progress.start)
    stop = proxymethod(Progress.stop)
    print = proxymethod(Progress.print)
    # get_task_attr = proxymethod(Progress.get_task_attr)
    dump_task = proxymethod(Progress.dump_task)
    dump_tasks = proxymethod(Progress.dump_tasks)
    load_task = proxymethod(Progress.load_task)
    new_task = proxymethod(Progress.new_task)
    pop_task = proxymethod(Progress.pop_task)
    clear = proxymethod(Progress.clear)

ProgressProxy._exposed_ = tuple(k for k, v in ProgressProxy.__dict__.items() if getattr(v, '_is_exposed_', False))

multiprocessing.managers.ProgressProxy = ProgressProxy  # Can't pickle - attribute lookup ProgressProxy on multiprocessing.managers failed


class MqdmManager(SyncManager):
    mqdm_Progress: Type[ProgressProxy]
MqdmManager.register('mqdm_Progress', Progress, ProgressProxy)

M._manager = None
M._pause_event = threading.Event()
M._pause_event.set()
M._shutdown_event = threading.Event()
M._shutdown_event.set()
def get_manager() -> MqdmManager:
    if M._manager is not None:
        return M._manager
    M._manager = manager = MqdmManager()
    manager.start()
    M._pause_event = manager.Event()
    M._pause_event.set()
    M._shutdown_event = manager.Event()
    M._shutdown_event.set()
    return manager


def get_progress_instance(pool_mode: T_POOL_MODE=None, *columns, **kw):
    if pool_mode == 'process':
        manager = get_manager()
        return manager.mqdm_Progress(*columns, **kw)
    return Progress(*columns, **kw)



# import sys
# import rich
# from typing import cast, TextIO, IO, Optional
# from rich.file_proxy import FileProxy
# class _RedirectIO:
#     def __init__(self, console: rich.console.Console, redirect_stdout: bool = True, redirect_stderr: bool = True):
#         self.console_compatible = console.is_terminal or console.is_jupyter
#         self._redirect_stdout = redirect_stdout
#         self._redirect_stderr = redirect_stderr
#         self._restore_stdout: Optional[IO[str]] = None
#         self._restore_stderr: Optional[IO[str]] = None

#     def __enter__(self):
#         self.enable()
#         return self
    
#     def __exit__(self, *exc):
#         self.disable()

#     def __del__(self):
#         self.disable()

#     def enable(self) -> None:
#         """Enable redirecting of stdout / stderr."""
#         if self.console_compatible:
#             if self._redirect_stdout and not isinstance(sys.stdout, FileProxy):
#                 self._restore_stdout = sys.stdout
#                 sys.stdout = cast("TextIO", FileProxy(self.console, sys.stdout))
#             if self._redirect_stderr and not isinstance(sys.stderr, FileProxy):
#                 self._restore_stderr = sys.stderr
#                 sys.stderr = cast("TextIO", FileProxy(self.console, sys.stderr))

#     def disable(self) -> None:
#         """Disable redirecting of stdout / stderr."""
#         if self._restore_stdout:
#             sys.stdout = cast("TextIO", self._restore_stdout)
#             self._restore_stdout = None
#         if self._restore_stderr:
#             sys.stderr = cast("TextIO", self._restore_stderr)
#             self._restore_stderr = None