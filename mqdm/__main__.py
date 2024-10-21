import time
# import multiprocessing as mp
# mp.set_start_method('spawn')
# mp.set_start_method('fork')
# mp.set_start_method('forkserver')
import mqdm
from mqdm import examples

@mqdm.iex
def main():
    _rich_traceback_omit = True
    import fire
    fire.Fire({
        # 'bars': bar.example_pool,
        # 'bar': bar.example_bar,
        # 'fn': bar.example_fn,
        # 'messy': bar.example_messy,
        k.removeprefix('example_'): v for k, v in examples.__dict__.items() if k.startswith('example_')
    })
main()