import mqdm
import time


def process_fn(n):
    for _ in mqdm.mqdm(range(n), desc=f"worker {n}", leave=False):
        time.sleep(0.1)
    return n


def main():
    mqdm.pool(
        process_fn,
        [16, 22, 28, 34, 20, 26, 
         16, 22, 28, 34, 20, 26],
        desc="process pool",
        n_workers=3,
    )


if __name__ == "__main__":
    main()
