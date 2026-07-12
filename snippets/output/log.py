import time
import mqdm


import logging

mqdm.install_logging()
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


for i in mqdm.mqdm(range(100), desc="logging"):
    if i % 10 == 0:
        log.info("hi how's it going? %s / %s", i + 1, 400)
    time.sleep(0.05)
