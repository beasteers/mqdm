import mqdm
import time


with mqdm.mqdm(desc="before pause", total=2) as bar:
    time.sleep(0.08)
    bar.update()

with mqdm.pause():
    print("continue? yes")

with mqdm.mqdm(desc="after pause", total=2) as bar:
    time.sleep(0.08)
    bar.update(2)

time.sleep(0.2)
