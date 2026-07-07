from __future__ import annotations

import os
import time


SLEEP_SCALE = float(os.environ.get("MQDM_DOCS_SLEEP_SCALE", "1.0"))


def time.sleep(seconds: float) -> None:
    time.sleep(seconds * SLEEP_SCALE)
