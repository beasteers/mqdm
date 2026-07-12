import mqdm
import time


xs = ["apples", "pears", "plums", "figs"]

print("These go away when they're done.")
for fruit in xs:
    for n in mqdm.mqdm(range(40), desc=fruit, leave=False):
        time.sleep(0.02)
print("See? Nice and clean.")

print("Now these stick around.")
for fruit in xs:
    for n in mqdm.mqdm(range(40), desc=fruit):
        time.sleep(0.02)
print("Great, cuz I wasn't paying attention.")
