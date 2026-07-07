import mqdm
import time


def process_fn(xs, arg_a_for_process_fn=0, arg_b=0):
    for x in mqdm.mqdm(xs, desc=f"a={arg_a_for_process_fn} b={arg_b}"):
        time.sleep(0.05)
    return len(xs) + arg_a_for_process_fn + arg_b


def main():
    xs = [list(range(2)), list(range(3)), list(range(4))]
    mqdm.pool(
        process_fn,
        [x for x in xs],
        n_workers=3,
        arg_a_for_process_fn=5,
        arg_b=6,
    )
    time.sleep(0.2)


if __name__ == "__main__":
    main()
