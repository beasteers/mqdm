import mqdm
import time
from mqdm import print


number_of_tasks = [22, 4, 9, 8, 21]
min_iters = 10

for x in mqdm.mqdm(number_of_tasks, desc=f"Only showing progress bars with {min_iters}+ iterations" ):
    
    for y in mqdm.mqdm(range(x), disable=x <= min_iters, leave=False):
        time.sleep(0.1)

    if x <= min_iters:
        print(f"You didn't see me, I had only {x} iterations")
