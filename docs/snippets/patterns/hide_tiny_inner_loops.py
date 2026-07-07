import mqdm
import time


for x in mqdm.mqdm(range(6), desc="folders"):
    for y in mqdm.mqdm(range(x), disable=x < 3):
        time.sleep(0.03)

time.sleep(0.2)
