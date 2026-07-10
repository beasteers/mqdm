import mqdm
import time


def process_fn(x, arg_a, arg_b, *, some_key=None, arg_c=0):
    """A function with multiple arguments."""
    for _ in mqdm.mqdm(range(x), desc=f"{some_key} · c={arg_c}"):
        time.sleep(0.1)


def main():
    # List of items to process
    xs = [18, 24, 30, 36]

    # Some lookup table for additional information
    keys = {18: "oak", 24: "pine", 30: "elm", 36: "cedar"}

    mqdm.pool(
        process_fn,
        # mqdm.args wraps function arguments so they can be 
        # applied to process_fn. 
        [mqdm.args(x, 5, 6, some_key=keys[x]) for x in xs],
        n_workers=3,

        # Additional keyword arguments for process_fn can be passed here.
        # These will be passed to all tasks.
        arg_c=6,
    )


if __name__ == "__main__":
    main()
