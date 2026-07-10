# Pools

`mqdm` provides convenient interfaces for parallel processing with progress bars. 

 - `mqdm.pool(func, items)` will run all items in parallel and return a list of results.
 - `mqdm.ipool(func, items)` will do the same, and will yield results as they complete.

It wraps around `concurrent.futures` (builtin library) and provides a progress bar for monitoring the execution of the task queue.

Additionally, worker functions can have their own progress bars, which integrate seamlessly with the main pool progress display.

## Simple sequential

```python
--8<-- "snippets/pools/simple_sequential.py"
```

<div id="cast-pools-simple-seq" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/simple_sequential.cast"></div>

By default, mqdm.pool runs with 0 workers. 

## Simple parallel processes

```python
--8<-- "snippets/pools/simple_parallel.py"
```

<div id="cast-pools-simple-par" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/simple_parallel.cast"></div>

To run tasks in parallel, provide the number of workers via the `n_workers` argument. The default pool_mode is `"process"`.

## Simple parallel threads

```python
--8<-- "snippets/pools/simple_threads.py"
```

<div id="cast-pools-simple-threads" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/simple_threads.cast"></div>

To use a thread pool, just pass `pool_mode="thread"`.

## Passing additional arguments


```python
--8<-- "snippets/pools/extra_args.py"
```

<div id="cast-pools-extra-args" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/extra_args.cast"></div>

Extra keyword arguments can be passed directly to `mqdm.pool`, which will
pass them to each function call.

## Parallel with complex arguments

Use `mqdm.args(...)` to bundle multiple arguments for the worker function.

```python
--8<-- "snippets/pools/complex_args.py"
```

<div id="cast-pools-complex-args" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/complex_args.cast"></div>

Use `mqdm.args(...)` when each item needs its own positional or keyword values.
This is similar in spirit to a `joblib.delayed()(*a, **kw)` payload. 

Note - when an argument is shared across all items, it is more efficient to use 
a regular keyword argument to `mqdm.pool`.

## `ipool` for streaming results

If you want results as they complete instead of collecting a final list:

```python
--8<-- "snippets/pools/ipool_streaming.py"
```

<div id="cast-pools-ipool" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/ipool_streaming.cast"></div>

This is the nearest equivalent to `concurrent.futures.as_completed(...)`, but
with a coordinated progress display built in.

## Worker bars

`mqdm` works seamlessly inside worker functions, allowing each task to have its own progress bar running in parallel.

```python
--8<-- "snippets/pools/worker_bars.py"
```

<div id="cast-pools-worker-bars" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/pools/worker_bars.cast"></div>


## Interactive sessions with `python` / `IPython`

For interactive sessions, you have to switch multiprocessing to use the `fork` start method. This is because the default `spawn` method launches a worker process by calling the current script. But with interactive sessions, there is no script to call.

```python
python <<< '

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

'
```
