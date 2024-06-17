'''First draft implementation using manager dict.


'''

import random
from time import sleep
import threading
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from rich import progress


class Bars:
    def __init__(self, desc="[green]All jobs progress:") -> None:
        self.desc = desc
        self.pbar = progress.Progress(
            "[progress.description]{task.description}",
            progress.BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            progress.TimeRemainingColumn(),
            progress.TimeElapsedColumn(),
            refresh_per_second=8,
        )
        # Create and start a thread for reading from the queue
        reader_thread = threading.Thread(target=queue_reader, args=(queue,))
        reader_thread.start()
        self.manager = multiprocessing.Manager()

    def __enter__(self):
        self.pbar.__enter__()
        self.manager.__enter__()
        self.tasks = self.manager.dict()
        self.overall_task = self.pbar.add_task(self.desc)
        return self
   
    def __exit__(self, c,v,t):
        self.pbar.__exit__(c,v,t)
        self.manager.__exit__(c,v,t)

    def add(self, title, visible=False, **kw):
        task_id = self.pbar.add_task(title, visible=visible, start=False, **kw)
        return Bar(self.tasks, task_id)

    def update(self):
        n_finished = 0
        for task_id, data in self.tasks.items():
            data = dict(data)
            complete = data['total'] and data['completed'] >= data['total']
            visible = bool(data['total'] and not complete)
            data.setdefault('visible', visible)
            n_finished += complete
            # update the progress bar for this task:
            self.pbar.update(task_id, **data)
        self.pbar.update(self.overall_task, completed=n_finished, total=len(self.tasks))

    def as_completed(self, futures, cycle=0.1):
        while futures:
            done = [futures.pop(i) for i, f in enumerate(futures) if f.done()]
            for f in done:
                yield f
            self.update()
            sleep(cycle)

    @classmethod
    def map(cls, fn, xs, n_workers=8, desc=None, **kw):
        futures = []
        with cls() as pbars, ProcessPoolExecutor(max_workers=n_workers) as executor:
            for i, x in enumerate(xs):
                desc_i = desc(*x, **kw) if callable(desc) else desc or f'task {i}'
                futures.append(executor.submit(fn, *x, pbar=pbars.add(desc_i), **kw))
            for f in pbars.as_completed(futures):
                result = f.result()


class Bar:
    def __init__(self, tasks, task_id):
        self.tasks = tasks
        self.task_id = task_id
        self.current = 0
        self.total = 0
        self.update(0)

    def __call__(self, iter, total=None):
        try:
            self.total = len(iter)
        except TypeError:
            self.total = total
        def _iter():
            
            for x in iter:
                yield x
                self.update()
        return _iter()

    def set(self, value):
        self.current = value
        self.update(0)
        return self

    def update(self, n=1):
        self.current += n
        total = self.total if self.current or not self.total else (self.current+1)
        self.tasks[self.task_id] = {"completed": self.current, "total": total}
        return self



def example_fn(i, pbar):
    import random
    for i in pbar(range(i + 1)):
        sleep(random.random())

def pbar_test():
    Bars.map(example_fn, [[i] for i in range(10)], n_workers=5)
if __name__ == '__main__':

    import fire
    fire.Fire(pbar_test)
