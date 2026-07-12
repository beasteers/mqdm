import mqdm
import time


xs = ["apples", "pears", "plums", "figs"]

for fruit in xs:
    for n in mqdm.mqdm(range(40), desc=fruit):
        time.sleep(0.1)
