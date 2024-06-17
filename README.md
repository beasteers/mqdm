# mqdm: progress bars for multiprocessing
Pretty progress bars with `rich`, in your child processes.

## Install

```bash
pip install mqdm
```

## Worker progress
```python
import mqdm
import time

def my_work(n, sleep, pbar):
    for i in pbar(range(n), description=f'counting to {n}'):
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
with mqdm.Bars() as pbars:
    # create progress bars and send them to the remote processes
    pool.submit(my_work, 1, pbar=pbars.add())
    pool.submit(my_work, 2, pbar=pbars.add())
    pool.submit(my_work, 3, pbar=pbars.add())

# your worker function can look like this
def my_work(n, sleep, pbar):
    for i in pbar(range(n), description=f'counting to {n}'):
        time.sleep(sleep)

# or this
def my_work(n, pbar, sleep=0.2):
    import time
    with pbar(description=f'counting to {n}', total=n):
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
        pool.submit(my_work, i, pbar=pbars.add())
        for i in items
    ]
    for f in as_completed(futures):
        print(f.result())
```

It works by spawning a background thread with a multiprocessing queue. The Bars instance listens for messages from the progress bar proxies in the child processes.