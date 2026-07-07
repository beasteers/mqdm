import logging

import mqdm
import time


mqdm.install_logging(level=logging.INFO)
log = logging.getLogger(__name__)


for i in mqdm.mqdm(range(4), desc="logging"):
    log.info("iteration %s / %s", i + 1, 4)
    time.sleep(0.05)

time.sleep(0.2)
