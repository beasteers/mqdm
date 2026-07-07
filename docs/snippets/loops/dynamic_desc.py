import mqdm
import time


xs = ["alpha", "beta", "gamma", "delta"] * 40

for x in mqdm.mqdm(xs, desc=lambda x, i: f"Processing item {i}: {x}"):
    time.sleep(0.12)

time.sleep(0.2)
