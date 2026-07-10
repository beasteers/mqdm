import mqdm
import time
import random
from mqdm import print


number_of_tasks = [22, 14, 4, 4, 5, 30, 24, 27, 5, 3, 21]


min_iters = 10
for x in mqdm.mqdm(number_of_tasks, desc=f"Only showing progress bars with {min_iters}+ iterations"):
    for y in mqdm.mqdm(range(x), desc=f"{x} > {min_iters}? {x>min_iters}", disable=x <= min_iters, leave=False):
        time.sleep(0.05)
    print(f"Finished {'short' if x <= min_iters else 'long'} task with {x} iterations ({x} > {min_iters} == {x > min_iters})")
