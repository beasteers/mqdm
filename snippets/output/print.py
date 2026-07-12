import time
import mqdm
from mqdm import print


for i in mqdm.mqdm(range(10), desc="announcing"):
    time.sleep(0.2)
    print(f"finished step {i + 1}")
