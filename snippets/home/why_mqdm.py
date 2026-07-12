import time
import mqdm


def doing_something(item):
    thing, total = item
    for _ in mqdm.mqdm(range(total), desc=lambda _, i: f"{thing} · #{i + 1}"):
        time.sleep(0.03)
    return thing


things = [
    ("cats", 36),
    ("clouds", 44),
    ("notes", 52),
    ("pigeons", 60),
    ("rock", 68),
    ("shoelaces", 76),
    ("moss", 84),
    ("sparrows", 92),
]

def main():
    # An outer progress bar shows the pool progress.
    # Each worker has its own inner progress bar for the work inside that item.
    mqdm.pool(doing_something, things, desc="looking at", n_workers=3)


if __name__ == "__main__":
    main()
