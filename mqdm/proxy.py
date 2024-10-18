import contextlib
import multiprocessing as mp
from multiprocessing.managers import BaseManager, BaseProxy, MakeProxyType, SyncManager
import multiprocessing.managers
import time
import types
import mqdm
import rich
from rich import progress


# import queue
# import concurrent.futures.process
# import multiprocessing.reduction
# dumps=multiprocessing.reduction.ForkingPickler.dumps
# @classmethod
# def dumps2(cls, obj, *a, **kw):
#     print('dumps', obj, a, kw)
#     print(obj.__class__, getattr(obj, '__dict__', None))
#     if isinstance(obj, concurrent.futures.process._CallItem):
#         print('dumps2', obj.__dict__, a, kw)
#         # obj.__dict__['kwargs']['mqdm'] = None
#     if isinstance(obj, tuple):
#         print('dumps3', obj[1].__class__, getattr(obj[1], '__dict__', None), a, kw)
#     return dumps(obj, *a, **kw)
# multiprocessing.reduction.ForkingPickler.dumps = dumps2



class Progress(progress.Progress):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._task_hierarchy = {}

    def get_task(self, task_id):
        return {
            'completed': self._tasks[task_id].completed,
            'total': self._tasks[task_id].total,
            'fields': self._tasks[task_id].fields,
        }
    # def get_task_attrs(self, task_id, attrs):
    #     t = self.tasks[task_id]
    #     return {k: getattr(t, k) for k in attrs}
    
    def set_task_attrs(self, task_id, attrs):
        t = self.tasks[task_id]
        for k, v in attrs.items():
            setattr(t, k, v)

    def print(self, *args, **kw):
        rich.print(*args, **kw)

    def add_task(self, *args, parent_task_id=None, **kw):
        task_id = super().add_task(*args, **kw)
        self._tasks[task_id].is_complete = False
        if parent_task_id is not None:
            self._task_hierarchy[task_id] = parent_task_id
        return task_id

    def update(self, task_id, **data):
        if task_id not in self._task_hierarchy:
            return super().update(task_id, **data)

        if task_id is not None:
            # -------------------------------- update task ------------------------------- #
            # update the task-specific progress bar
            super().update(task_id, **data, refresh=False)

            # update progress bar visibility
            task = self._tasks[task_id]
            current = task.completed
            total = task.total
            transient = task.fields.get('transient', True)
            task.is_complete = complete = total is not None and current >= total
            task.visible = bool(total is not None and not complete or not transient)

        # ------------------------------ update overall ------------------------------ #
        parent_task_id = self._task_hierarchy[task_id]
        finished = [bool(self._tasks[i].is_complete) for i, pi in self._task_hierarchy.items() if pi == parent_task_id]
        super().update(parent_task_id, completed=sum(finished), total=len(finished))


ProgressProxy = MakeProxyType("ProgressProxy", exposed=(
    'start_task', 
    'stop_task', 
    'add_task',
    'remove_task',
    'update', 
    'refresh',
    '__exit__',
    'get_task',
    'set_task_attrs',
    'start',
    'stop',
    'print',
))
multiprocessing.managers.ProgressProxy = ProgressProxy

# class MqdmManager(SyncManager): pass
MqdmManager = SyncManager
MqdmManager.register('mqdm_Progress', Progress, ProgressProxy)


# @contextlib.contextmanager
# def replace_attr(obj, attr, value, default=None):
#     old = getattr(obj, attr, default)
#     setattr(obj, attr, value)
#     try:
#         yield obj
#     finally:
#         setattr(obj, attr, old)


def get_manager():
    if getattr(mqdm, '_manager', None) is not None:
        return mqdm._manager
    mqdm._manager = manager = MqdmManager()
    manager.start()
    return manager


class RemoteProgressFunction:
    def __init__(self, pbar, func):
        self.pbar = pbar
        self.func = func

    def __setstate__(self, state):
        self.__dict__.update(state)
        mqdm.pbar = self.pbar

    def __call__(self, *args, **kwds):
        # with replace_attr(mqdm, 'pbar', self.pbar):
        return self.func(*args, **kwds)