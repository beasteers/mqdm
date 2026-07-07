# Output

These helpers matter once your work is no longer just a clean local loop.

## Print above the bars

```python
--8<-- "snippets/output/print.py"
```

<div id="cast-output-print" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/output/print.cast"></div>

This is the safe version of printing when progress bars are active.

## Logging without tearing up the terminal

```python
import logging
import time
import mqdm

mqdm.install_logging(level=logging.INFO)
log = logging.getLogger(__name__)

for i in mqdm.mqdm(range(4), desc="logging"):
    log.info("iteration %s / %s", i + 1, 4)
    time.sleep(0.05)
```

<div id="cast-output-logging" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/output/logging_demo.cast"></div>

The point is simple: output keeps landing above the bars instead of shredding
the terminal layout.

## Byte-oriented manual progress

This shape shows up a lot in real upload and download code.

```python
import os
import mqdm

chunk_size = 1024 * 1024
path = "large.csv"

with mqdm.mqdm(desc="uploading", total=os.path.getsize(path), leave=False) as bar:
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            ...
            bar.update(len(chunk))
```

## Reading files with byte progress

```python
--8<-- "snippets/output/fopen.py"
```

<div id="cast-output-fopen" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/output/fopen.cast"></div>

`mqdm.fopen(...)` keeps byte-oriented progress accounting while still feeling
like a normal file iterator.
