import mqdm
import time


def process_fn(x):
    time.sleep(x)
    return x * 2


def main():
    delays = [0.9, 0.5, 1.2, 0.7, 0.4, 1.0]
    for result in mqdm.ipool(process_fn, delays, n_workers=3, ordered_=False):
        mqdm.print(f"result -> {result}")


if __name__ == "__main__":
    main()
