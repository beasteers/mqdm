import mqdm
import time


def process_fn(n):
    for _ in mqdm.mqdm(range(n), desc=f"worker {n}", leave=False):
        time.sleep(0.1)
    return n


def main():
    mqdm.pool(process_fn, [2, 3, 4, 5] * 40, desc='process pool', n_workers=3)
    time.sleep(0.2)


if __name__ == "__main__":
    main()
