import mqdm
import time


xs = [["a", "b"], ["c", "d", "e"], ["f", "g"]] * 40

for x in mqdm.mqdm(xs, desc="groups"):
    for xi in mqdm.mqdm(x, desc=f"group {len(x)}", leave=False):
        time.sleep(0.08)
