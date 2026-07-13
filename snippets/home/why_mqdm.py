import time
import mqdm


def doing_something(thing):
    """Process a given thing."""
    items = range(len(thing) * 14)
    for _ in mqdm.mqdm(items, desc=lambda _, i: f"{thing} · #{i + 1}"):
        time.sleep(0.01 * len(thing))
    return thing


things = [
    "cats",
    "clouds",
    "notes",
    "pigeons",
    "rock",
    "shoelaces",
    "moss",
    "sparrows",
]

def main():
    # An outer progress bar shows the pool progress.
    # Each worker has its own inner progress bar for the work inside that item.
    mqdm.pool(
        doing_something, 
        things, 
        desc="looking at", 
        n_workers=3)


if __name__ == "__main__":
    main()
