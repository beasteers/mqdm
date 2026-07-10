import time
import mqdm

import random
import tempfile


kinds = ["apples", "pears", "plums", "figs", "bananas", "kiwis", 
         "mangos", "oranges", "blueberries", "raspberries"]
text = "\n".join(random.choice(kinds) for _ in range(2_000_000))


with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as tmp:
    tmp.write(text)

    with mqdm.fopen(tmp.name, "r") as f:
        for line in f:
            _ = line.strip()
            time.sleep(0.000005)
