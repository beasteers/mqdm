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

from . import utils
from .utils import args
from .bar import Bar
from .bars import Bars, RemoteBar
pool = Bars.pool
mqdm = Bar.mqdm
mqdms = Bars.mqdms
