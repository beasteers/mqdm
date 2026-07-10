import mqdm
import time


with mqdm.mqdm(desc="compressing", total=4) as bar:
    for name in ["a.zip", "b.zip", "c.zip", "d.zip"]:
        time.sleep(1)
        bar.set_description(f"compressing {name}")
        bar.advance()

