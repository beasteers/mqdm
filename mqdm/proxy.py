import multiprocessing as mp
from multiprocessing.managers import MakeProxyType, SyncManager
import multiprocessing.managers
import mqdm
import rich
from rich import progress


# import multiprocessing.reduction
# dumps=multiprocessing.reduction.ForkingPickler.dumps
# @classmethod
# def dumps2(cls, obj, *a, **kw):
#     print('dumps', obj, a, kw)
#     return dumps(obj, *a, **kw)
# multiprocessing.reduction.ForkingPickler.dumps = dumps2


import threading
_thread_local_data = threading.local()
def _pbar_initializer(pbar, parent_task_id):
    """Initialize the progress bar for the worker thread/process."""
    mqdm.pbar = pbar
    _thread_local_data.parent_task_id = parent_task_id


class Progress(progress.Progress):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._task_hierarchy = {}

    def print(self, *args, **kw):
        rich.print(*args, **kw)
    print_ = print  # for some reason "print" is proxied weirdly (not calling the actual method)

    def add_task(self, *args, parent_task_id=None, **kw):
        task_id = super().add_task(*args, **kw)
        self._tasks[task_id].is_complete = False
        if parent_task_id is not None:
            self._task_hierarchy[task_id] = parent_task_id
        return task_id

    def remove_task(self, task_id):
        child_tasks = [k for k, v in self._task_hierarchy.items() if v == task_id]
        for child_task in child_tasks:
            self.remove_task(child_task)
        super().remove_task(task_id)
        self._task_hierarchy.pop(task_id, None)

    def update(self, task_id, **data):
        # Normal task update
        if task_id not in self._task_hierarchy:
            return super().update(task_id, **data)

        # Update the task and its parent
        if task_id is not None:
            # -------------------------------- update task ------------------------------- #
            # update the task-specific progress bar
            super().update(task_id, **data, refresh=False)

            # update progress bar visibility
            task = self._tasks[task_id]
            total = task.total
            transient = task.fields.get('transient', True)
            task.is_complete = complete = total is not None and task.completed >= total
            task.visible = bool(total is not None and not complete or not transient)

        # ------------------------------ update overall ------------------------------ #
        parent_task_id = self._task_hierarchy[task_id]
        finished = [bool(self._tasks[i].is_complete) for i, pi in self._task_hierarchy.items() if pi == parent_task_id]
        super().update(parent_task_id, completed=sum(finished), total=len(finished))

#     def make_tasks_table(self, tasks):
#         """Get a table to render the Progress display.

#         Args:
#             tasks (Iterable[Task]): An iterable of Task instances, one per row of the table.

#         Returns:
#             Table: A table instance.
#         """
#         table = Table.grid(*((
#                 Column(no_wrap=True)
#                 if isinstance(_column, str)
#                 else _column.get_table_column().copy()
#             )
#             for _column in self.columns
#         ), padding=(0, 1), expand=self.expand)

#         for task in tasks:
#             if task.visible:
#                 table.add_row(
#                     *(
#                         (
#                             column.format(task=task)
#                             if isinstance(column, str)
#                             else column(task)
#                         )
#                         for column in self.columns
#                     )
#                 )
#         return table
# from rich.progress import Column, Table



ProgressProxy = MakeProxyType("ProgressProxy", exposed=(
    'start_task', 
    'stop_task', 
    'add_task',
    'remove_task',
    'update', 
    'refresh',
    'start',
    'stop',
    'print_',
    'print',
))
multiprocessing.managers.ProgressProxy = ProgressProxy  # Can't pickle - attribute lookup ProgressProxy on multiprocessing.managers failed


class MqdmManager(SyncManager): pass
# MqdmManager = SyncManager
MqdmManager.register('mqdm_Progress', Progress, ProgressProxy)

def get_manager():
    if getattr(mqdm, '_manager', None) is not None:
        return mqdm._manager
    mqdm._manager = manager = MqdmManager()
    manager.start()
    return manager
