import mqdm
import time
import random


kinds = ["apples", "pears", "plums", "figs", "bananas", "kiwis", 
         "mangos", "oranges", "blueberries", "raspberries"]
xs = [random.choice(kinds) for _ in range(40)]

for fruit in mqdm.mqdm(xs, desc=lambda n, i: f"Processing item {i}: {fruit}"):
    time.sleep(0.4)
