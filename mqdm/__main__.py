import time
# import multiprocessing as mp
# mp.set_start_method('spawn')
# mp.set_start_method('fork')
# mp.set_start_method('forkserver')
import mqdm
from mqdm.bar import example as example_bar
from mqdm.bars import example as example_bars

@mqdm.iex
def main():
    _rich_traceback_omit = True
    import fire
    fire.Fire({
        'bars': example_bars,
        'bar': example_bar,
    })
main()