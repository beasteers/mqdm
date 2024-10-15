from rich import print

_instances = []
pbar = None

def get(i=-1):
    try:
        return _instances[i]
    except IndexError:
        raise IndexError(f'No progress bar found at index {i} in list of length {len(instances)}')

def set_description(desc, i=-1):
    return get(i).set_description(desc)

def _add_instance(bar):
    _instances.append(bar)
    return bar

def _remove_instance(bar):
    while bar in _instances:
        _instances.remove(bar)

# _visibility = {}
# def hide_instances(hide=True):
#     if hide:
#         for bar in _instances:
#             _visibility[bar] = bar.visible
#             bar.update(visible=False)
#     else:
#         for bar in _instances:
#             if bar in _visibility:
#                 bar.update(visible=_visibility[bar])

# def embed():
#     hide_instances(True)
#     from IPython import embed
#     embed()
#     hide_instances(False)


from . import utils
from .utils import args
from .bar import Bar
from .bars import Bars, RemoteBar
pool = Bars.pool
mqdm = Bar.mqdm
mqdms = Bars.mqdms
