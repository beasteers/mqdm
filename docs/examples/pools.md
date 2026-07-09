# Pools

This is the center of the package after `mqdm.mqdm(xs)`.

If `mqdm.mqdm(xs)` is your `tqdm.tqdm(xs)`, then `mqdm.pool(process_fn, xs)` is
your progress-aware `Pool(...).imap(...)` shape.

## Simple sequential

```python
--8<-- "snippets/pools/simple_sequential.py"
```

<div id="cast-pools-simple-seq" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/simple_sequential.cast"></div>

This is useful because the exact same call shape can scale up to worker pools
without changing how you think about the interface.

## Simple parallel

```python
--8<-- "snippets/pools/simple_parallel.py"
```

<div id="cast-pools-simple-par" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/simple_parallel.cast"></div>

That is the main jump: same basic call, now with multiple workers.

## Simple parallel with additional arguments

Shared keyword arguments for every task can be passed directly to `mqdm.pool`.

```python
--8<-- "snippets/pools/extra_args.py"
```

<div id="cast-pools-extra-args" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/extra_args.cast"></div>

That pattern is often enough. You do not need `mqdm.args(...)` unless the
arguments differ item by item.

## Parallel with complex arguments

Use `mqdm.args(...)` when each item needs its own positional or keyword values.

```python
--8<-- "snippets/pools/complex_args.py"
```

<div id="cast-pools-complex-args" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/complex_args.cast"></div>

This is similar in spirit to a small `joblib.delayed(...)` payload, but lighter.
It is powerful, but it is not the first tool most code needs.

## `ipool` for streaming results

If you want results as they complete instead of collecting a final list:

```python
--8<-- "snippets/pools/ipool_streaming.py"
```

<div id="cast-pools-ipool" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/ipool_streaming.cast"></div>

This is the nearest equivalent to `concurrent.futures.as_completed(...)`, but
with a coordinated progress display built in.

## Worker bars

One of the nicest parts of `mqdm.pool(...)` is that worker functions can use
their own bars too.

```python
--8<-- "snippets/pools/worker_bars.py"
```

<div id="cast-pools-worker-bars" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/worker_bars.cast"></div>


## `IPython`

For interactive sessions, you have to switch multiprocessing to use the `fork` start method. This is because the default `spawn` method launches a worker process by calling the current script. But with interactive sessions, there is no script to call.

```python
# Call me!
import multiprocessing as mp    
mp.set_start_method("fork", force=True)

# Okay now we're ok
import mqdm

mqdm.pool(
    example_fn,
    xs,
    desc="Very important work",
    n_workers=4,
)
```
