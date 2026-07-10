import mqdm
import time


items = ["apples", "pears", "plums", "figs", "bananas", "kiwis", 
         "mangos", "oranges", "blueberries", "raspberries"] * 10

for fruit in mqdm.mqdm(items, desc=lambda x, i: f"Processing item {i}: {x}"):
    time.sleep(0.4)
