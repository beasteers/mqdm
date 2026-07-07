import mqdm
import time


with mqdm.group():
    for i in range(3):
        for _ in mqdm.mqdm(range(4), desc=f"section {i}"):
            time.sleep(0.05)

time.sleep(0.2)
