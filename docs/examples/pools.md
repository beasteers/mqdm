# Pools

This is the center of the package after `mqdm.mqdm(xs)`.

If `mqdm.mqdm(xs)` is your `tqdm.tqdm(xs)`, then `mqdm.pool(process_fn, xs)` is
your progress-aware `Pool(...).imap(...)` shape.

## Simple sequential

```python
import time
import mqdm

def process_fn(xs):
    for x in mqdm.mqdm(xs):
        time.sleep(0.05)

mqdm.pool(process_fn, [x for x in xs], n_workers=0)
```

<div id="cast-pools-simple-seq" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/simple_sequential.cast"></div>

This is useful because the exact same call shape can scale up to worker pools
without changing how you think about the interface.

## Simple parallel

```python
import time
import mqdm

def process_fn(xs):
    for x in mqdm.mqdm(xs):
        time.sleep(0.05)

mqdm.pool(process_fn, [x for x in xs], n_workers=3)
```

<div id="cast-pools-simple-par" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/simple_parallel.cast"></div>

That is the main jump: same basic call, now with multiple workers.

## Simple parallel with additional arguments

Shared keyword arguments for every task can be passed directly to `mqdm.pool`.

```python
import time
import mqdm

def process_fn(xs, arg_a_for_process_fn=0, arg_b=0):
    for x in mqdm.mqdm(xs):
        time.sleep(0.05)

mqdm.pool(
    process_fn,
    [x for x in xs],
    n_workers=3,
    arg_a_for_process_fn=5,
    arg_b=6,
)
```

<div id="cast-pools-extra-args" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/extra_args.cast"></div>

That pattern is often enough. You do not need `mqdm.args(...)` unless the
arguments differ item by item.

## Parallel with complex arguments

Use `mqdm.args(...)` when each item needs its own positional or keyword values.

```python
import time
import mqdm

def process_fn(x, arg_a, arg_b, *, some_key=None, arg_c=0):
    for _ in mqdm.mqdm(range(x), desc=some_key):
        time.sleep(0.04)

mqdm.pool(
    process_fn,
    [mqdm.args(x, 5, 6, some_key=keys[x]) for x in xs],
    n_workers=3,
    arg_c=6,
)
```

<div id="cast-pools-complex-args" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/complex_args.cast"></div>

This is similar in spirit to a small `joblib.delayed(...)` payload, but lighter.
It is powerful, but it is not the first tool most code needs.

## `ipool` for streaming results

If you want results as they complete instead of collecting a final list:

```python
import time
import mqdm

def process_fn(x):
    time.sleep(0.22 / x)
    return x * 2

for result in mqdm.ipool(process_fn, xs, n_workers=3, ordered_=False):
    mqdm.print(result)
```

<div id="cast-pools-ipool" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/ipool_streaming.cast"></div>

This is the nearest equivalent to `concurrent.futures.as_completed(...)`, but
with a coordinated progress display built in.

## Worker bars

One of the nicest parts of `mqdm.pool(...)` is that worker functions can use
their own bars too.

```python
import time
import mqdm

def process_fn(n):
    for _ in mqdm.mqdm(range(n), desc=f"worker {n}"):
        time.sleep(0.04)
    return n

mqdm.pool(process_fn, [2, 3, 4, 5], n_workers=3)
```

<div id="cast-pools-worker-bars" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/worker_bars.cast"></div>
