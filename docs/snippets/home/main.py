import time
import mqdm
from mqdm import args

mqdm.configure(
    refresh_per_second=20,
)

def doing_something(thing, n, delay, interval=0.1, mult=1):
    time.sleep(delay * interval)
    for _ in mqdm.mqdm(range(n*mult), desc=thing):
        time.sleep(interval)
    return thing


things = [
    args("gives",                  24,              0),
    args("you",                    24,              3),
    args("nested",                 48,              6),
    args("parallel",               64,              9),
    args("cross-process",          36,              12),
    args("progress bars",          110,             16),
    args("made",                   64,              48),
    args("easy",                   72,              64),
]

def main():
    # An outer progress bar shows the pool progress.
    # Each worker has its own inner progress bar for the work inside that item.
    mqdm.pool(doing_something, things, desc="mqdm", n_workers=10)
    print("Done :)")


if __name__ == "__main__":
    main()
