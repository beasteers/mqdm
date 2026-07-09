import mqdm
import time


def process_fn(xs):
    for _ in mqdm.mqdm(xs, desc="batch"):
        time.sleep(0.03)
    return len(xs)


def main():
    batches = [
        list(range(18)),
        list(range(24)),
        list(range(30)),
        list(range(36)),
        list(range(24)),
        list(range(18)),
    ]
    mqdm.pool(process_fn, batches, n_workers=3)


if __name__ == "__main__":
    main()
