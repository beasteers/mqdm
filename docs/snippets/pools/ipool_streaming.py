import mqdm
import time


def process_fn(x):
    time.sleep(0.22 / x)
    return x * 2


def main():
    for result in mqdm.ipool(process_fn, [1, 2, 3, 4], n_workers=3, ordered_=False):
        mqdm.print(f"result -> {result}")
    time.sleep(0.2)


if __name__ == "__main__":
    main()
