import mqdm
import time

for i in range(3):
    # If we can't infer the iterable length (e.g. a generator), 
    # the progress bar will display as indeterminate.
    data_generator = (n for n in range(40))
    for n in mqdm.mqdm(data_generator, desc=f'without total=', leave=False):
        time.sleep(0.1)

    # If you know the length or an approximate length, 
    # you can give it to mqdm via the `total` argument. 
    data_generator = (n for n in range(40))
    for n in mqdm.mqdm(data_generator, total=40, desc=f'with total=', leave=False):
        time.sleep(0.1)
