import time
import mqdm

import os
import random
import tempfile


kinds = ["apples", "pears", "plums", "figs", "bananas", "kiwis", 
         "mangos", "oranges", "blueberries", "raspberries"]
text = "\n".join(random.choice(kinds) for _ in range(4_000_000))

with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as tmp:
    tmp.write(text)
    path = tmp.name

    # Read the file in chunks

    chunk_size = 1024 * 1024  # 1 MB
    with mqdm.mqdm(desc="uploading", bytes=True, total=os.path.getsize(path)) as bar:
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                time.sleep(0.2)
                bar.advance(len(chunk))
