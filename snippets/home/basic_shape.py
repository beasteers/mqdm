import time

import mqdm


things = [
    "cats",
    "clouds",
    "notes",
    "pigeons",
    "rock",
    "shoelaces",
]

for thing in mqdm.mqdm(things, desc="looking at"):
    for _ in mqdm.mqdm(range(60), desc=lambda _, i: f"{thing} · #{i + 1}"):
        time.sleep(0.02)
