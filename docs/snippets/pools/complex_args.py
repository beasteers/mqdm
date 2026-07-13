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
        [
            mqdm.args(
                # Positional arguments for process_fn: x, arg_a=5, arg_b=6
                x, 5, 6, 
                # Keyword arguments for process_fn: some_key=keys[x]
                some_key=keys[x]) 
            for x in xs
        ],
        n_workers=3,

        # Additional keyword args passed to all tasks
        arg_c=6,
    )


if __name__ == "__main__":
    main()
