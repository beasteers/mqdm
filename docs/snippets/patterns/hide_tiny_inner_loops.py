import mqdm
import time
import random
from mqdm import print

min_iters = 10
for x in mqdm.mqdm(range(10), desc=f"Only showing progress bars with {min_iters}+ iterations"):
    n = int(abs(random.gauss(0, 20)) + 1)
    for y in mqdm.mqdm(range(n), desc=f"{n} > {min_iters}? {n>min_iters}", disable=n <= min_iters, leave=False):
        time.sleep(0.05)
    print(f"Finished {'short' if n <= min_iters else 'long'} task with {n} iterations")

time.sleep(0.2)
