import time
import mqdm
import rich.progress
from itertools import zip_longest

runtime1 = mqdm.Runtime()
runtime2 = mqdm.Runtime(backend_options={"columns": (
    rich.progress.SpinnerColumn('moon'),
    rich.progress.SpinnerColumn('moon'),
    rich.progress.SpinnerColumn('moon'),
    rich.progress.SpinnerColumn('moon'),
    rich.progress.SpinnerColumn('moon'),
    "[bold]{task.description}",
    rich.progress.BarColumn(bar_width=None),
    rich.progress.SpinnerColumn('moon'),
)})
# Reordered mix of Rich and mqdm columns: count, then the two-tone bar, then ETA.
runtime3 = mqdm.Runtime(backend_options={"columns": (
    rich.progress.SpinnerColumn('moon'),
    mqdm.columns.MofNColumn(),
    rich.progress.SpinnerColumn('moon'),
)})

for i in zip_longest(
    mqdm.mqdm(range(10), desc="runtime 1", runtime=runtime1),
    mqdm.mqdm(range(10), desc="runtime 2", runtime=runtime2),
    mqdm.mqdm(range(10), desc="runtime 3", runtime=runtime3),
):
    time.sleep(0.2)
    print("Hellooo")