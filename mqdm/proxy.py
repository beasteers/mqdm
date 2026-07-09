import io
from collections import deque
import dataclasses
from dataclasses import dataclass
from typing import Type
from functools import wraps
import multiprocessing as mp
from multiprocessing.managers import BaseProxy, SyncManager
import multiprocessing.managers
import rich
from rich.console import Console
from rich import progress
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


@dataclass
class TaskSnapshot:
    id: int
    description: str
    total: float | None
    completed: int
    visible: bool
    fields: dict
    start_time: float | None = None
    stop_time: float | None = None
    finished_time: float | None = None
    finished_speed: float | None = None
    _progress: list[tuple[float, float]] | None = None

    @classmethod
    def from_task(cls, task: progress.Task) -> 'TaskSnapshot':
        data = {k.name: getattr(task, k.name) for k in dataclasses.fields(task) if not k.name.startswith('_')}
        progress_samples = []
        if task._progress:
            progress_samples.append((task._progress[-1].timestamp, sum(s.completed for s in task._progress)))
        return cls(**data, _progress=progress_samples)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'TaskSnapshot':
        return cls(**data)


class Progress(progress.Progress):
    multiprocess = False
    paused = False

    def __init__(self, *columns, _tasks=None, _task_index=None, _pause_event=None, silent=False, **kw):
        # Record init options before injecting the silent console so convert_proxy
        # round-trips `silent` (and re-creates the sink console on the other side)
        # rather than pickling the local StringIO console.
        self._init_options = dict(kw)
        if silent:
            self._init_options['silent'] = True
            kw.setdefault('console', Console(file=io.StringIO(), force_terminal=True))
        super().__init__(*columns, **kw)

        if _tasks is not None:
            self._tasks = {task_id: self._load_task(TaskSnapshot.from_dict(task)) for task_id, task in _tasks.items()}
        self._task_index = progress.TaskID(_task_index or 0)

    def write(self, *args, **kw):
        """Print above the live progress display.

        Uses this Progress's own console so the output interleaves with the
        live region. When called through a ``ProgressProxy`` the write is
        routed into the process that owns the real ``Progress`` (and its Live).
        """
        self.console.print(*args, **kw)

    @wraps(progress.Progress.update)
    def update(self, task_id, **kw):
        if 'description' in kw and kw['description'] is None:  # ignore None descriptions
            kw.pop('description')
        return super().update(task_id, **kw)
    
    @wraps(progress.Progress.update)
    def try_update(self, task_id, **kw):
        try:
            return self.update(task_id, **kw)
        except KeyError as e:
            pass

    update_ = try_update

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

    def clear(self):
        """Clear the progress bar."""
        with self._lock:
            self._tasks.clear()

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

    def convert_proxy(self, runtime=None) -> 'ProgressProxy':
        """Convert to a multiprocessing proxy object so methods can be called in another process."""
        runtime = runtime or M._current_runtime()
        started = self.live.is_started
        tasks = self.dump_tasks()
        for task_id in tasks:
            self.remove_task(task_id)
        started or self.start()
        self.refresh()
        self.stop()

        try:
            proxy = runtime.get_manager().mqdm_Progress(
                *self.columns,
                _tasks=tasks,
                _task_index=self._task_index,
                **self._init_options,
            )
        except Exception:
            for task_id in sorted(tasks):
                self.load_task(tasks[task_id], start=False)
            if started:
                self.start()
            raise
        proxy.multiprocess = True
        if started:
            proxy.start()
        return proxy

    def dump_tasks(self):
        with self._lock:
            return {task_id: self._dump_task(self._tasks[task_id]).to_dict() for task_id in self._tasks}

    def dump_render_state(self):
        # Static parts (columns/init_options) plus the current task state and the
        # source clock, for building a mirror in another process. Pulled once.
        return {
            'columns': self.columns,
            'tasks': self.dump_tasks(),
            'init_options': self._init_options,
            'now': self.get_time(),
        }

    def dump_live_state(self):
        # Just the frequently-changing parts: task snapshots + source clock. This
        # is the per-frame pull once a mirror already exists.
        with self._lock:
            return {
                'now': self.get_time(),
                'tasks': {task_id: self._dump_task(self._tasks[task_id]).to_dict() for task_id in self._tasks},
            }

    def dump_task(self, task_id):
        with self._lock:
            return self._dump_task(self._tasks[task_id]).to_dict()

    def _dump_task(self, task):
        return TaskSnapshot.from_task(task)
    
    def _load_task(self, snapshot: TaskSnapshot, start=True):
        data = snapshot.to_dict()
        _progress = data.pop('_progress') or []
        start_time = data.pop('start_time', None)
        stop_time = data.pop('stop_time', None)
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

    def load_task(self, task: dict, start=True):
        with self._lock:
            task = self._load_task(TaskSnapshot.from_dict(task), start=start)
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
            return self._dump_task(self._new_task(description or '', start, total, completed, visible, **fields)).to_dict()



# ---------------------------------------------------------------------------- #
#                   Multiprocessing Proxy for Progress class                   #
# to allow sharing progress bar state across processes.
# ---------------------------------------------------------------------------- #




def proxymethod(func):
    name = func.__name__
    @wraps(func)
    def _call(self, *a, **kw):
        return self._callmethod(name, a, kw)
    _call._is_exposed_ = True
    return _call


class ProgressProxy(BaseProxy):
    multiprocess = True
    paused = False

    start_task = proxymethod(Progress.start_task)
    stop_task = proxymethod(Progress.stop_task)
    add_task = proxymethod(Progress.add_task)
    remove_task = proxymethod(Progress.remove_task)
    update = proxymethod(Progress.update)
    try_update = proxymethod(Progress.try_update)
    update_ = try_update
    refresh = proxymethod(Progress.refresh)
    start = proxymethod(Progress.start)
    stop = proxymethod(Progress.stop)
    write = proxymethod(Progress.write)
    dump_task = proxymethod(Progress.dump_task)
    dump_tasks = proxymethod(Progress.dump_tasks)
    dump_render_state = proxymethod(Progress.dump_render_state)
    dump_live_state = proxymethod(Progress.dump_live_state)
    load_task = proxymethod(Progress.load_task)
    new_task = proxymethod(Progress.new_task)
    pop_task = proxymethod(Progress.pop_task)
    clear = proxymethod(Progress.clear)

    # Local mirror Progress reused across renders (see _render_progress).
    _mirror = None

    def _render_progress(self):
        # Build the mirror once — columns/init_options are static — then on each
        # render pull only task state + the source clock and rebuild the (cheap)
        # Task objects into the cached mirror. This avoids re-pickling static state
        # and rebuilding the whole Progress/Live every frame.
        mirror = self._mirror
        if mirror is None:
            state = self.dump_render_state()
            init_options = {'expand': True, **state['init_options'], 'auto_refresh': False}
            mirror = self._mirror = Progress(*state['columns'], **init_options)
            # Freeze the mirror's clock to the source's `now` so elapsed/speed use
            # the same monotonic origin as the task timestamps (the local
            # monotonic() would be a different, meaningless origin).
            mirror.get_time = lambda: mirror._source_now
        else:
            state = self.dump_live_state()
        mirror._source_now = state['now']
        mirror._tasks = {
            progress.TaskID(int(task_id)): mirror._load_task(TaskSnapshot.from_dict(task), start=False)
            for task_id, task in sorted(state['tasks'].items(), key=lambda kv: int(kv[0]))
        }
        return mirror

    def __rich_console__(self, console, options):
        yield self._render_progress().get_renderable()

ProgressProxy._exposed_ = tuple(k for k, v in ProgressProxy.__dict__.items() if getattr(v, '_is_exposed_', False))

multiprocessing.managers.ProgressProxy = ProgressProxy  # Can't pickle - attribute lookup ProgressProxy on multiprocessing.managers failed


class MqdmManager(SyncManager):
    mqdm_Progress: Type[ProgressProxy]
MqdmManager.register('mqdm_Progress', Progress, ProgressProxy)
