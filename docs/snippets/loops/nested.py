import mqdm
import time


xs = ["apples", "pears", "plums", "figs"]

for fruit in mqdm.mqdm(xs, desc="fruits"):
    for n in mqdm.mqdm(range(40), desc=fruit, leave=False):
        time.sleep(0.1)
