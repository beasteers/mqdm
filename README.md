# mqdm — tqdm-style progress bars that work across processes
Pretty progress bars (powered by `rich`) that keep working when you move to threads or processes. Designed for people who already know `tqdm`.

## Install

```bash
pip install mqdm
```

## Quick start
```python
import mqdm
from mqdm import print

items = range(10)

# nested loop progress
for x in mqdm.mqdm(items):
    # your description can change for each item
    for y in mqdm.mqdm(items, desc=lambda y, i: f'item {x} {y}'):
        print(x, y)  # will show above the progress bars (only with mqdm.print or rich.print)
```

## Parallel Processing

Run things effortlessly in parallel, with a top-level progress bar for pool items and any nested progress bars you add in your workers.

```python
from mqdm import pool, ipool
from mqdm import print  # makes sure sub-process prints don't garble the progress bars

# Parallel work with progress from workers

import time
def work(n, sleep=0.05):
    for _ in mqdm(range(n), desc=f"counting to {n}"):
        time.sleep(sleep)
        print("asdfsadf")
    return n

# executes my task in a concurrent futures process pool. ordered results (default)
results = pool(
    work, 
    range(1, 8), 
    n_workers=3
)


# Unordered results, thread pool
for out in ipool(work, range(1, 8), pool_mode='thread'):
    ...
```

## Key concepts
- `mqdm(iterable, ...)` — tqdm-like iterator. Works in the main process and inside worker functions.
- `pool(fn, iterable, ...)` — runs `fn` over `iterable` and returns a list of results (ordered).
- `ipool(fn, iterable, ...)` — generator version of `pool` (yields results as they complete by default).

Both pools support `pool_mode='process'|'thread'|'sequential'`. If given `n_workers=0` or if there is only a single item, they will just use the main process.

## Usage patterns

Dynamic descriptions (per-item)
```python
from mqdm import mqdm

for x in mqdm(range(5), desc=lambda arg, i: f"item {i}"):
    ...
```

Silencing short loops
```python
from mqdm import mqdm

for n in mqdm(range(100)):
    for x in mqdm(range(n), disable=len(xs) < 20):
        ...  # counters still update; nothing is printed
```

Printing from workers
```python
from mqdm import print  # routes to the main process' console
print("hello from anywhere")
```

Processing in pools
```python
from mqdm import pool, ipool

def square(x):
    return x * x

for y in ipool(square, range(10), pool_mode='process', ordered_=False, n_workers=4):
    ...

ys: list[int] = pool(square, range(10), pool_mode='process', n_workers=4)
print(ys)


# Process sequentially, in the main process.
ys: list[int] = pool(square, range(10), n_workers=0)
print(ys)
```

Controlling behavior
- `n_workers`: number of workers for threads/processes.
- `bar_kw`: forwarded to the main bar (e.g., `{'transient': True}` to clear finished bars).
- `on_error`: in `ipool`, choose `'cancel'` (default), `'skip'`, or `'finish'` to control error behavior.

## Pandas example
```python
from mqdm import mqdm
import pandas as pd

df = pd.read_csv('...')

# iterrows is a generator — pass total for accurate progress
for i, row in mqdm(df.iterrows(), total=len(df)):
    pass
```

## Use your own processes/threads

The `pool` and `ipool` methods are offered for convenience (and are wrappers around `concurrent.futures`). 

However, `mqdm` will work across threads/processes using `concurrent.futures`, `multiprocessing`, and `threading`.

Just make sure that you pass an `mqdm.Initializer` when using them across processes.

Using `concurrent.futures.ProcessPoolExecutor`:
```python
from concurrent.futures import ProcessPoolExecutor, as_completed

xs = range(n)
with ProcessPoolExecutor(max_workers=n_workers, initializer=M.Initializer()) as executor:
    with mqdm(desc='[bold blue]Very important work', total=len(xs)) as pbar:
        futures = {executor.submit(example_fn, i, **kw): i for i in xs}
        for future in as_completed(futures):
            result = future.result()
            pbar.update(1)
```

Using `concurrent.futures.ThreadPoolExecutor`:
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

xs = range(n)
with ThreadPoolExecutor(max_workers=n_workers) as executor:
    with mqdm(desc='[bold blue]Very important work', total=len(xs)) as pbar:
        futures = {executor.submit(example_fn, i, **kw): i for i in xs}
        for future in as_completed(futures):
            result = future.result()
            pbar.update(1)
```
Using `multiprocessing.Pool`:
```python
from multiprocessing import Pool

xs = range(n)
with Pool(processes=n_workers, initializer=M.Initializer()) as executor:
    with mqdm(desc='[bold blue]Very important work', total=len(xs)) as pbar:
        for _ in executor.imap_unordered(example_fn, it):
            pbar.update(1)
```
Using `threading.Thread`:
```python
from threading import Thread

it = range(n)
with mqdm(desc='[bold blue]Very important work', total=len(it)) as pbar:
    threads = []
    def worker(i):
        example_fn(i, **kw)
        pbar.update(1)
    for i in it:
        t = Thread(target=worker, args=(i,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
```


## Minimal API reference
- `mqdm(iterable=None, desc=None, total=None, disable=False, **kw)`
  - tqdm-like wrapper. If `iterable` is `int`, it’s treated as `range(iterable)`.
  - Methods: `.update(n=1, **kw)`, `.set(**kw)`, `.set_description(str)`.
  - Common `kw`: `bytes` (switches to transfer metrics), `transient` (clear on finish), `visible`.

-- Pools --
- `pool(fn, iterable, desc='', bar_kw=None, n_workers=8, pool_mode='process', ordered_=True, squeeze_=True, **kw)`
  - Returns list. Preserves order by default.
  - `kw` is forwarded to `fn` for each item.

- `ipool(fn, iterable, desc='', bar_kw=None, n_workers=8, pool_mode='process', ordered_=False, squeeze_=True, on_error='cancel', **kw)`
  - Yields results. Unordered by default (faster for long-running tasks).
  - `on_error`: `'cancel'` (stop and cancel unfinished), `'skip'` (log and continue), `'finish'` (collect and raise combined report).

## Notes
- I haven't given much thought to routing around logging Logger instances. Could be worth handling? 