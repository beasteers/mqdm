import time
import mqdm
from mqdm.bar import example as example_bar
from mqdm.bars import example as example_bars


import fire
fire.Fire({
    'bars': example_bars,
    'bar': example_bar,
})
