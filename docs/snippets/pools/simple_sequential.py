import mqdm
import time


def process_fn(xs):
    for x in mqdm.mqdm(xs, desc="batch"):
        time.sleep(0.1)
    return len(xs)


def main():
    xs = [list(range(20)), list(range(30)), list(range(40))]
    mqdm.pool(process_fn, [x for x in xs], n_workers=0)
    time.sleep(0.2)


if __name__ == "__main__":
    main()
