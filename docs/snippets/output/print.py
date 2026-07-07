import mqdm
import time


for i in mqdm.mqdm(range(4), desc="announcing"):
    time.sleep(0.06)
    mqdm.print(f"finished step {i + 1}")

time.sleep(0.2)
