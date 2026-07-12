import mqdm
import time

from rich.progress import BarColumn, MofNCompleteColumn, ProgressColumn, TimeRemainingColumn
from rich.text import Text

# Columns live in a runtime's `backend_options`. `mqdm.configure(columns=...)`
# sets them for the default runtime; here we use isolated runtimes to show a few
# layouts side by side in one script.


def run(runtime, desc, **fields):
    for _ in mqdm.mqdm(range(20), desc=desc, runtime=runtime, **fields):
        time.sleep(0.05)


# 1. Compact — just a label, a bar, and a percentage.
compact = mqdm.Runtime(backend_options={"columns": (
    "[progress.description]{task.description}",
    BarColumn(bar_width=None),
    "[progress.percentage]{task.percentage:>3.0f}%",
)})
run(compact, "compact")

# 2. Reordered mix of Rich and mqdm columns: count, then the two-tone bar, then ETA.
detailed = mqdm.Runtime(backend_options={"columns": (
    "[bold]{task.description}",
    MofNCompleteColumn(),
    mqdm.columns.TwoToneColumn(bar_width=30),
    TimeRemainingColumn(),
)})
run(detailed, "detailed")


# 3. Your own column, rendering a per-task field you pass to the bar.
class RateColumn(ProgressColumn):
    def render(self, task):
        return Text(f"{task.fields.get('rate', '?')}/s", style="cyan")


custom = mqdm.Runtime(backend_options={"columns": (
    "{task.description}",
    BarColumn(bar_width=None),
    RateColumn(),
)})
run(custom, "custom field", rate=42)
