# mqdm: progress bars for multiprocessing
Pretty progress bars using `rich`, in your child processes.

## Install

```bash
pip install mqdm
```

## Normal tqdm-style progress bars
```python
import mqdm

items = range(10)

# nested loop progress
for x in mqdm.mqdm(items):
    # your description can change for each item
    for y in mqdm.mqdm(items, desc=lambda y, i: f'item {x} {y}'):
        print(x, y)
```


## Progress of work across worker pools
```python
import mqdm
import time

def my_work(n, sleep, mqdm: mqdm.Bar):
    for i in mqdm(range(n), description=f'counting to {n}'):
        time.sleep(sleep)

# executes my task in a concurrent futures process pool
mqdm.pool(
    my_work,
    range(1, 10),
    sleep=1,
    n_workers=3,
)
```

![alt text](static/image.png)

## Less high level please
Basically, the mechanics are this:
```python
# use context manager to start background listener and message queue
with mqdm.mqdms() as pbars:
    # create progress bars and send them to the remote processes
    pool.submit(my_work, 1, mqdm=pbars.remote())
    pool.submit(my_work, 2, mqdm=pbars.remote())
    pool.submit(my_work, 3, mqdm=pbars.remote())

# your worker function can look like this
def my_work(n, sleep=1, mqdm: mqdm.Remote):
    # It takes a proxy mqdm instance that can create new progress bars
    for i in mqdm(range(n), description=f'counting to {n}'):
        time.sleep(sleep)
        mqdm.print("hi")

# or this
def my_work(n, sleep=1, mqdm: mqdm.Remote):
    import time
    with mqdm(description=f'counting to {n}', total=n) as pbar:
        for i in range(n):
            pbar.update(0.5, description=f'Im counting - {n}  ')
            time.sleep(sleep/2)
            pbar.update(0.5, description=f'Im counting - {n+0.5}')
            time.sleep(sleep/2)
```

And you can use it in a pool like this:

```python
import mqdm
from concurrent.futures import ProcessPoolExecutor, as_completed

items = range(1, 10)

with ProcessPoolExecutor(max_workers=n_workers) as pool, mqdm.Bars() as pbars:
    futures = [
        pool.submit(my_work, i, pbar=pbars.remote())
        for i in items
    ]
    for f in as_completed(futures):
        print(f.result())
```

It works by spawning a background thread with a multiprocessing queue. The Bars instance listens for messages from the progress bar proxies in the child processes.