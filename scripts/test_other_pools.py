import time
import mqdm
from mqdm import print
import random

def example_fn(i, steps=256, delay=0.01):
    for _ in mqdm.mqdm(range(random.randint(1, steps)), desc=f"worker {i}", transient=True):
        time.sleep(delay)
        if random.random() < 0.01:
            print(f"Worker {i} is doing something important!")

xs = range(10)

import mqdm

def run_with_mqdm_pool(n_workers=4):
    mqdm.pool(
        example_fn,
        xs,
        desc="Very important work",
        n_workers=n_workers,
    )

import mqdm
from mqdm.parallel.executor import Initializer

from concurrent.futures import ProcessPoolExecutor, as_completed

def run_with_process_pool(n_workers=4):
    with (
        ProcessPoolExecutor(
            max_workers=n_workers,
            initializer=Initializer(pool_mode="process"),
        ) as executor,
        mqdm.mqdm(total=len(xs), desc="Very important work") as pbar,
    ):
        futures = {executor.submit(example_fn, x): x for x in xs}
        for future in as_completed(futures):
            future.result()
            pbar.update(1)


import mqdm

from concurrent.futures import ThreadPoolExecutor, as_completed

def run_with_thread_pool(n_workers=8):
    with (
        ThreadPoolExecutor(max_workers=n_workers) as executor,
        mqdm.mqdm(total=len(xs), desc="Very important work") as pbar,
    ):
        futures = {executor.submit(example_fn, x): x for x in xs}
        for future in as_completed(futures):
            future.result()
            pbar.update(1)


import mqdm
from mqdm.parallel.executor import Initializer

from multiprocessing import Pool

def run_with_mp_pool(n_workers=4):
    with (
        Pool(
            processes=n_workers,
            initializer=Initializer(pool_mode="process"),
        ) as pool,
        mqdm.mqdm(total=len(xs), desc="Very important work") as pbar,
    ):
        for _ in pool.imap_unordered(example_fn, xs):
            pbar.update(1)



import mqdm
from mqdm.parallel.executor import Initializer

from joblib import Parallel, delayed

def run_with_joblib(n_workers=4):
    with (
        Parallel(n_jobs=n_workers, initializer=Initializer(), return_as="generator_unordered") as executor,
        mqdm.mqdm(total=len(xs), desc="Very important work") as pbar
    ):
        for _ in executor(delayed(example_fn)(x) for x in xs):
            pbar.update(1)


import mqdm

from threading import Thread

def run_with_threads(n_workers=8):
    with mqdm.mqdm(total=len(xs), desc="Very important work") as pbar:
        threads = []

        def worker(x):
            example_fn(x)
            pbar.update(1)

        for x in xs:
            thread = Thread(target=worker, args=(x,))
            thread.start()
            threads.append(thread)

        for thread in threads:
            thread.join()


def run_with_dask(n_workers=4):
    from dask.distributed import Client, LocalCluster, as_completed
    from mqdm.parallel.executor import Initializer
    import mqdm

    cluster = LocalCluster(n_workers=n_workers, threads_per_worker=1)
    try:
        with (
            Client(cluster) as client,
            mqdm.mqdm(total=len(xs), desc="Very important work") as pbar,
        ):
            client.register_worker_callbacks(setup=Initializer())
            futures = [client.submit(example_fn, x) for x in xs]
            for future in as_completed(futures):
                future.result()
                pbar.update(1)
    finally:
        cluster.close()


if __name__ == "__main__":
    import fire
    fire.Fire()
