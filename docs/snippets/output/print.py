import time
import mqdm
from mqdm import print


for i in mqdm.mqdm(range(4), desc="announcing"):
    time.sleep(0.06)
    print(f"finished step {i + 1}")
