# Other multiprocessing tools

While `mqdm` provides helpers to run items in parallel (`pool(...)`), it is also
designed in a modular way so that if you need to use a different scheduler, 
you can still use `mqdm` for progress bars.

This page shows how to use `mqdm` with various multiprocessing libraries. 

The pattern is:

- create a normal `mqdm` bar in the parent
- update it from the parent as work completes
- in order for worker processes to have their own `mqdm` output or nested bars, you need to provide an initializer e.g. `mqdm.executor.Initializer`

## How process cross-talk works

In process mode, `mqdm` does not try to render a separate live display in every
worker.

Instead, it keeps one canonical `Progress` object in a `multiprocessing`
parent process and lets workers talk to it through a queue-backed proxy.

The important pieces are:

- the parent `Runtime` owns the shared progress state
- the first process-mode bar installs a command dispatch in the parent
- that parent-owned dispatch hosts the real `Progress` instance
- workers receive a pickled `Runtime` plus an `Initializer`
- worker calls like `mqdm.print(...)`, `pbar.update(...)`, and nested
  `mqdm.mqdm(...)` calls go through proxy methods back to the parent-owned
  `Progress`
- only one live display is rendered, so worker output lands in a single
  coordinated terminal region

That is why `mqdm.pool(...)` and local process pools can show nested worker bars
cleanly: all workers are writing into one shared progress owner.

This is also the boundary to keep in mind when integrating with other
schedulers. If the library gives you:

- a way to run setup code inside each worker process
- a way to keep the parent process in control of the terminal

then `mqdm` can usually fit into it.

If worker output is captured and replayed later, or if each worker tries to own
its own terminal rendering, you may still get progress updates, but not one
clean shared live display.

## Example worker function (`example_fn`)

```python
import time
import mqdm
import random
from mqdm import print  # Important for cross-process printing

def example_fn(i, steps=256, delay=0.01):
    for _ in mqdm.mqdm(range(random.randint(1, steps)), desc=f"worker {i}", transient=True):
        time.sleep(delay)
        if random.random() < 0.01:
            print(f"Worker {i} is doing something important!")
```

## `mqdm.pool` (baseline)

```python
import mqdm

def run_with_mqdm_pool(xs, n_workers=4):
    mqdm.pool(
        example_fn,
        xs,
        desc="Very important work",
        n_workers=n_workers,
    )
```


## `concurrent.futures.ProcessPoolExecutor`

```python
import mqdm
from mqdm.executor import Initializer

from concurrent.futures import ProcessPoolExecutor, as_completed

def run_with_process_pool(xs, n_workers=4):
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
```

## `concurrent.futures.ThreadPoolExecutor`

```python
import mqdm

from concurrent.futures import ThreadPoolExecutor, as_completed

def run_with_thread_pool(xs, n_workers=8):
    with (
        ThreadPoolExecutor(max_workers=n_workers) as executor,
        mqdm.mqdm(total=len(xs), desc="Very important work") as pbar,
    ):
        futures = {executor.submit(example_fn, x): x for x in xs}
        for future in as_completed(futures):
            future.result()
            pbar.update(1)
```

## `multiprocessing.Pool`

```python
import mqdm
from mqdm.executor import Initializer

from multiprocessing import Pool

def run_with_mp_pool(xs, n_workers=4):
    with (
        Pool(
            processes=n_workers,
            initializer=Initializer(pool_mode="process"),
        ) as pool,
        mqdm.mqdm(total=len(xs), desc="Very important work") as pbar,
    ):
        for _ in pool.imap_unordered(example_fn, xs):
            pbar.update(1)
```

## `joblib.Parallel`

```python
import mqdm
from mqdm.executor import Initializer

from joblib import Parallel, delayed

def run_with_joblib(xs, n_workers=4):
    with (
        Parallel(n_jobs=n_workers, initializer=Initializer(), return_as="generator_unordered") as executor,
        mqdm.mqdm(total=len(xs), desc="Very important work") as pbar
    ):
        for _ in executor(delayed(example_fn)(x) for x in xs):
            pbar.update(1)
```

## Raw `threading.Thread`

```python
import mqdm

from threading import Thread

def run_with_threads(xs):
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
```
