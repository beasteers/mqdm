import mqdm
import time


def process_fn(xs, arg_a_for_process_fn=0, arg_b=0):
    desc = f"a={arg_a_for_process_fn} b={arg_b}"
    for _ in mqdm.mqdm(xs, desc=desc):
        time.sleep(0.03)
    return len(xs) + arg_a_for_process_fn + arg_b


def main():
    batches = [
        list(range(18)),
        list(range(24)),
        list(range(30)),
        list(range(36)),
    ]
    mqdm.pool(
        process_fn,
        batches,
        n_workers=3,
        arg_a_for_process_fn=5,
        arg_b=6,
    )


if __name__ == "__main__":
    main()
