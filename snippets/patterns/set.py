import mqdm
import time

# `set()` changes any facet of a live bar. A few useful moves, methodically:
with mqdm.mqdm(total=100, desc="downloading") as bar:

    # 1. jump the counter to an absolute value (not +1) and relabel, in one call
    for pct in range(20, 81, 10):
        time.sleep(0.25)
        bar.set(completed=pct, description=f"downloading · {pct}%")

    # 2. the download was bigger than expected — grow the total mid-run
    print("Rechecking download size...")
    time.sleep(1)
    bar.set(total=160)
    print(f"New size: {bar.total}")
    time.sleep(0.5)
    for pct in range(100, 161, 10):
        time.sleep(0.25)
        bar.set(completed=pct, description=f"downloading · {pct}%")
    print("Download complete.")

    # 3. re-scope the same bar for a new phase: new label, reset count and total
    bar.set(description="verifying", completed=0, total=3)
    for step in ("checksum", "signature", "unpack"):
        time.sleep(0.8)
        bar.set(advance=1, description=f"verifying · {step}")
    print("Done :)")
