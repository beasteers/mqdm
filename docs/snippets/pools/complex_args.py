import mqdm
import time


def process_fn(x, arg_a, arg_b, *, some_key=None, arg_c=0):
    for _ in mqdm.mqdm(range(x), desc=f"{some_key} · c={arg_c}"):
        time.sleep(0.03)
    return x + arg_a + arg_b + arg_c


def main():
    xs = [18, 24, 30, 36]
    keys = {18: "oak", 24: "pine", 30: "elm", 36: "cedar"}
    mqdm.pool(
        process_fn,
        [mqdm.args(x, 5, 6, some_key=keys[x]) for x in xs],
        n_workers=3,
        arg_c=6,
    )


if __name__ == "__main__":
    main()
