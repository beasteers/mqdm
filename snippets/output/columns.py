import time
import mqdm
import rich.progress

# ------------------------- The Default Column Layout ------------------------ #

# Default layout
default = mqdm.Runtime(backend_options={"columns": (
    "[progress.description]{task.description}",
    mqdm.columns.TwoToneColumn(bar_width=None),
    "[progress.percentage]{task.percentage:>3.0f}%",
    mqdm.columns.MofNColumn(),
    mqdm.columns.SpeedColumn(),
    mqdm.columns.TimeElapsedColumn(compact=True),
    rich.progress.TimeRemainingColumn(compact=True),
    rich.progress.SpinnerColumn(),
)})

# Run mqdm with the runtime
for _ in mqdm.mqdm(range(100), desc="default", runtime=default):
    time.sleep(0.05)

# ----------------------------- A Compact Layout ----------------------------- #

# Compact — just a label, a bar, and a percentage.
compact = mqdm.Runtime(backend_options={"columns": (
    "[progress.description]{task.description}",
    rich.progress.BarColumn(bar_width=None),
    "[progress.percentage]{task.percentage:>3.0f}%",
)})

# Run mqdm with the runtime
for _ in mqdm.mqdm(range(100), desc="compact", runtime=compact):
    time.sleep(0.05)

# ----------------------------- Whatever you like ---------------------------- #

# Reordered mix of Rich and mqdm columns: count, then the two-tone bar, then ETA.
moons = mqdm.Runtime(backend_options={"columns": (
    rich.progress.SpinnerColumn('moon'),
    rich.progress.SpinnerColumn('moon'),
    rich.progress.SpinnerColumn('moon'),
    rich.progress.SpinnerColumn('dots'),
    "[bold]{task.description}",
    rich.progress.BarColumn(bar_width=None),
    "[bold]{task.description}",
    rich.progress.SpinnerColumn('dots'),
    rich.progress.SpinnerColumn('moon'),
    rich.progress.SpinnerColumn('moon'),
    rich.progress.SpinnerColumn('moon'),
)})

# Run mqdm with the runtime
for _ in mqdm.mqdm(range(100), desc="moons", runtime=moons):
    time.sleep(0.05)
