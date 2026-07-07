# mqdm

<div class="hero">
  <div class="hero-copy">
    <p class="eyebrow">tqdm for parallel work</p>
    <h1>beautiful tqdm-style progress bars for multiprocessing and worker-heavy code</h1>
    <p class="lede">
      <code>mqdm</code> is basically <code>tqdm</code> built for
      <code>multiprocessing</code>, <code>concurrent.futures</code>, and nested
      worker progress, made lovely by <code>rich</code>.
    </p>
  </div>
  <div class="hero-art">
    <img src="assets/image.png" alt="mqdm progress bar illustration" />
  </div>
</div>

## What it is

If you know these shapes:

- `tqdm.tqdm(xs)`
- `multiprocessing.Pool(...).imap(...)`
- `concurrent.futures.ProcessPoolExecutor`
- `joblib`-style deferred arguments

then `mqdm` should feel very familiar:

- `mqdm.mqdm(xs)`
- `mqdm.pool(fn, xs)`
- `mqdm.ipool(fn, xs)`
- `mqdm.args(...)`

The main difference is that `mqdm` is designed so the nice terminal experience
keeps working when you move beyond a single local loop.

## Why people reach for it

- nested progress bars stay readable
- process and thread workers can show progress too
- `mqdm.print(...)` and logging stay above the bars
- the API still feels small and unsurprising

## A tiny example

```python
import time
import mqdm

for x in mqdm.mqdm(xs):
    for xi in mqdm.mqdm(x):
        time.sleep(0.05)
```

## The two things most people type

### A familiar bar

```python
import mqdm

for item in mqdm.mqdm(xs):
    ...
```

### A familiar pool

```python
import mqdm

results = mqdm.pool(process_fn, xs, n_workers=4)
```

That is the center of the package.

## A quick side-by-side

| idea | `tqdm` / stdlib | `mqdm` |
| --- | --- | --- |
| local loop | `tqdm(xs)` | `mqdm(xs)` |
| manual bar | `bar.update()` | `bar.update()` |
| process pool | `Pool(...).imap(...)` | `mqdm.pool(fn, xs)` |
| thread / process futures | `executor.submit(...)` | `mqdm.ipool(fn, xs)` |
| deferred args | manual tuples / wrappers | `mqdm.args(...)` |

## What it feels like

<div class="feature-grid">
  <div class="feature-card">
    <h3>Familiar</h3>
    <p><code>mqdm.mqdm(xs)</code> is meant to feel immediately normal.</p>
  </div>
  <div class="feature-card">
    <h3>Parallel</h3>
    <p><code>mqdm.pool</code> and <code>mqdm.ipool</code> cover the common worker cases.</p>
  </div>
  <div class="feature-card">
    <h3>Nested</h3>
    <p>Inner bars and changing descriptions remain readable instead of chaotic.</p>
  </div>
  <div class="feature-card">
    <h3>Quiet</h3>
    <p>`rich` makes the output soft and clear without changing how you think.</p>
  </div>
</div>

## Start here

- If you want to see the most useful patterns, go to [Examples](examples/index.md).
- If you want the full callable surface, open [API reference](api.md).

## A full script

This is the kind of shape `mqdm` is meant to make feel easy: a small CLI,
parallel outer work, nested inner progress, and clean terminal output.

```python
import os
import glob
import time
import random

import mqdm
from mqdm import print


def process_sensor(sensor_id, csv_dir, sleep=0.04):
    """Process all CSV files for a given sensor ID."""

    # Get all CSV files for this sensor (e.g. dates)
    fs = glob.glob(f"{csv_dir}/{sensor_id}/*.csv")

    # Progress bar description function
    desc = lambda f, i: f"{sensor_id} - {os.path.basename(f)}"
    for f in mqdm.mqdm(fs, desc=desc):
        # Do some work, or take a nap 💤
        time.sleep(sleep)

        # Print out results using `mqdm.print` so that 
        # things look pretty in the terminal
        if random.random() < 0.3:
            print(
              f"Sensor {sensor_id} - {os.path.basename(f)}"
              " - some interesting result or something")

    
    return len(fs)  # Return e.g. the number of files processed


def main(csv_dir="data", n_workers=2, sleep=0.04):
    """Process all sensors in the given CSV directory in parallel."""

    # Get your list of sensor IDs (subdirectories) to process
    sensor_ids = [sensor_id for sensor_id in glob.glob(f"{csv_dir}/*")]

    # Call process_sensor in parallel for each sensor ID, with a progress bar 
    results = mqdm.pool(
        # The processing function and the list of items to run it on
        process_sensor,
        sensor_ids,

        # Progress bar options
        desc="Processing sensor data in parallel...",
        n_workers=n_workers,  # How many parallel workers to use

        # Custom args passed to `process_sensor`
        csv_dir=csv_dir,
        sleep=sleep,
    )


if __name__ == "__main__":
    import fire
    fire.Fire(main)
```

If you have used `tqdm` plus `multiprocessing`, this should feel familiar:
same basic Python, just less terminal glue.
