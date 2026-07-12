import io
from collections import deque
import dataclasses
from dataclasses import dataclass
from typing import Any
from functools import wraps
from rich.console import Console
from rich import progress
import mqdm as M

from .backend import RichTaskState, TaskState
from .command_proxy import TransportCommandProxy, proxymethod


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

    def to_dict(self) -> RichTaskState:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: TaskState) -> 'TaskSnapshot':
        return cls(**data)


class Progress(progress.Progress):
    multiprocess = False

    # ---------------------------------------------------------------------------- #
    #                           Construction / Bootstrap                           #
    #  these hooks preserve enough init state to restore detached tasks and keep   #
    #  process-safe proxy promotion independent of Rich's in-process-only state.   #
    # ---------------------------------------------------------------------------- #

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

    @classmethod
    def default_progress_columns(cls) -> tuple[object, ...]:
        """Return the default Rich column layout for mqdm progress displays.

        Per-task fields such as ``bytes`` are resolved by the individual column
        implementations, so the shared layout does not vary by runtime options.
        """
        from . import progress_columns

        return (
            "[progress.description]{task.description}",
            progress_columns.TwoToneColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.0f}%",
            progress_columns.MofNColumn(),
            progress_columns.SpeedColumn(),
            progress_columns.TimeElapsedColumn(compact=True),
            progress.TimeRemainingColumn(compact=True),
            progress.SpinnerColumn(),
        )

    # -------------------------------- Rich API --------------------------------- #

    def write(self, *args, **kw):
        """Print above the live progress display.

        Uses this Progress's own console so the output interleaves with the
        live region. When called through a process-safe proxy, the write is
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

    # ---------------------------------------------------------------------------- #
    #                           Task Lifecycle / Mutation                          #
    #  these overrides funnel task creation and lifecycle through mqdm-owned       #
    #  helpers so local and proxied bars can share the same task state model.      #
    # ---------------------------------------------------------------------------- #

    def _start_task(self, task):
        if task.start_time is None:
            task.start_time = self.get_time()

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
    #                        Task Snapshot / Serialization                         #
    #  these helpers reduce Rich tasks to transportable snapshots so state can be  #
    #  exported, restored, and forwarded across process boundaries.                #
    # ---------------------------------------------------------------------------- #

    def dump_tasks(self) -> dict[int, RichTaskState]:
        with self._lock:
            return {task_id: self._dump_task(self._tasks[task_id]).to_dict() for task_id in self._tasks}

    def dump_task(self, task_id) -> RichTaskState:
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

    def load_task(self, task: TaskState, start=True):
        with self._lock:
            task = self._load_task(TaskSnapshot.from_dict(task), start=start)
            self._tasks[task.id] = task
            if task.id >= self._task_index:
                self._task_index = progress.TaskID(task.id+1)
        self.refresh()

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

    # ---------------------------------------------------------------------------- #
    #                        Multiprocessing Backend Upgrade                       #
    #  this section upgrades a local Rich-backed Progress into a queue-backed      #
    #  owner-rendered proxy for process workers.                                   #
    # ---------------------------------------------------------------------------- #

    def convert_proxy(self, command_bridge=None) -> 'QueueProgressProxy':
        """Convert to a multiprocessing-safe proxy object."""
        return QueueProgressProxy.from_ref(self, command_bridge=command_bridge)


class QueueProgressProxy(TransportCommandProxy[Progress]):
    multiprocess = True

    start = proxymethod(Progress.start, expect_reply=False, owner_only=True)
    stop = proxymethod(Progress.stop, expect_reply=False, owner_only=True)
    refresh = proxymethod(Progress.refresh, expect_reply=False, owner_only=True)

    write = proxymethod(Progress.write, expect_reply=False)

    add_task = proxymethod(Progress.add_task)
    try_update = proxymethod(Progress.try_update, expect_reply=False)
    dump_task = proxymethod(Progress.dump_task)
    load_task = proxymethod(Progress.load_task, expect_reply=False)
    pop_task = proxymethod(Progress.pop_task)
    
    # Unused methods (to deprecate) - not defined on ProgressBackend
    
    new_task = proxymethod(Progress.new_task)
    update = proxymethod(Progress.update, expect_reply=False)
    update_ = try_update
    start_task = proxymethod(Progress.start_task, expect_reply=False)
    stop_task = proxymethod(Progress.stop_task, expect_reply=False)
    remove_task = proxymethod(Progress.remove_task, expect_reply=False)
    dump_tasks = proxymethod(Progress.dump_tasks)

    def __rich_console__(self, console, options):
        ref = self.ref
        if ref is None:
            raise RuntimeError("QueueProgressProxy can only render in the owner process.")
        yield ref.get_renderable()
