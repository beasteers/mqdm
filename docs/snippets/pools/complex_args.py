import mqdm
import time


def process_fn(x, arg_a, arg_b, *, some_key=None, arg_c=0):
    for _ in mqdm.mqdm(range(x), desc=f"{some_key} · c={arg_c}"):
        time.sleep(0.04)
    return x + arg_a + arg_b + arg_c


def main():
    xs = [2, 3, 4]
    keys = {2: "oak", 3: "pine", 4: "elm"}
    mqdm.pool(
        process_fn,
        [mqdm.args(x, 5, 6, some_key=keys[x]) for x in xs],
        n_workers=3,
        arg_c=6,
    )
    time.sleep(0.2)


if __name__ == "__main__":
    main()
