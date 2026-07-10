import mqdm
import time

# `update()` does a full update on every call — flexible but slower.
t0 = time.time()
with mqdm.mqdm("update (generic, slow)") as pbar:
    while time.time() - t0 < 6:
        pbar.update(1)

# `advance()` is tuned specifically for fast increments and is 
# >10-15x faster than `update()` in tight loops.
# The trade-off is that state updates are throttled (default 8 fps)
# so the update is not strictly atomic.
t0 = time.time()
with mqdm.mqdm("advance (fast)") as pbar:
    while time.time() - t0 < 6:
        pbar.advance(1)

# Iterating with `for _ in mqdm.mqdm()` already uses the fast path internally.
t0 = time.time()
with mqdm.mqdm("for _ in mqdm.mqdm()") as pbar:
    for i in pbar((i for i in range(int(6e12)))):
        if time.time() - t0 >= 6:
            break
