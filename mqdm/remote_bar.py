''''''
import sys
import rich
from . import utils
import mqdm





class Remote:
    _console = None
    def __init__(self, queue):
        self.queue = queue

    def _new(self):
        return RemoteBar(self.queue, self.queue.random_id())
    
    def _call(self, task_id, method, *args, **kw):
        self.queue.put((task_id, method, args, kw))

    def __call__(self, **kw):
        bar = self._new()
        self._call(bar.task_id, '__remote_add', (), bar._process_args(**kw))
        return bar

    @property
    def console(self):
        if self._console is None:
            self._console = rich.console.Console(file=utils.QueueFile(self.queue))
        return self._console

    def __getstate__(self):
        state = self.__dict__.copy()
        state['_console'] = None
        return state
    
    def __setstate__(self, state):
        self.__dict__.update(state)
        mqdm._remote = self
    
    # -------------------------- Top Level mqdm Aliases -------------------------- #
    
    def pause(self, paused=True):
        self._call(None, '__pause', paused)

    def print(self, *a, **kw):
        self.console.print(*a, **kw)
        return self
    
    def get(self, i=-1):
        return mqdm.get(i)
    
    def set_description(self, desc, i=-1):
        return mqdm.set_description(desc)


class RemoteBar:
    _entered = False
    _get_desc = None
    total = None
    def __init__(self, remote, task_id):
        self._remote = remote
        self.task_id = task_id

    def _call(self, method, *args, **kw):
        self._remote._call(self.task_id, method, *args, **kw)

    def __setstate__(self, state):
        self.__dict__.update(state)
        mqdm._add_instance(self)

    def __enter__(self, **kw):
        if not self._entered:
            self._call('start_task', **kw)
            mqdm._add_instance(self)
            self._entered = True
        return self

    def __exit__(self, exc_type, exc_value, tb):
        if self._entered:
            self._call('stop_task')
            mqdm._remove_instance(self)
            self._entered = False

    def __del__(self):
        try:
            if sys.meta_path is None:
                return 
            self.__exit__(None, None, None)
        except (AttributeError, ImportError, BrokenPipeError, FileNotFoundError) as e:
            pass

    def __len__(self):
        return self.total or 0

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._iter)
    
    def _get_iter(self, iter, **kw):
        for i, x in enumerate(iter):
            self.update(i>0, arg_=x)
            yield x
        self.update()

    def __call__(self, iter=None, total=None, desc=None, **kw):
        if isinstance(iter, str) and desc is None:  # infer string as description
            iter, kw['description'] = None, iter
        if iter is None:
            return self.update(total=total, **kw)

        total = utils.try_len(iter, self.total) if total is None else total
        self.update(0, total=total, description=desc or ..., **kw)
        def _with_iter():
            if self._entered:
                yield from self._get_iter(iter, **kw)
                return
            with self:
                yield from self._get_iter(iter, **kw)
        self._iter = _with_iter()
        return self

    def print(self, *a, **kw):
        self._remote.print(*a, **kw)
        return self

    def set_description(self, desc):
        return self.update(0, description=desc or "")

    def _process_args(self, *, arg_=..., **kw):
        kw = {k: v for k, v in kw.items() if v is not ...}
        if 'total' in kw:
            self.total = kw['total']

        # get description
        if 'desc' in kw:
            kw['description'] = kw.pop('desc')
        if 'description' in kw and callable(kw['description']):
            self._get_desc = kw.pop('description')
        if 'description' not in kw and self._get_desc is not None and arg_ is not ...:
            kw['description'] = self._get_desc(arg_)
        if 'description' in kw and kw.get('description') is None:
            kw['description'] = ''

        return kw

    def update(self, n=1, *, arg_=..., **kw):
        kw = self._process_args(arg_=arg_, **kw)
        if n or kw:
            self._call('update', advance=n, **kw)
        return self

