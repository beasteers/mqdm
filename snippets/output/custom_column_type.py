import mqdm
import time

import rich.progress
from rich.text import Text

# ----------------------------- Custom Column Type ---------------------------- #

# Your own column, rendering a per-task field you pass to the bar.
class RateColumn(rich.progress.ProgressColumn):
    def render(self, task):
        return Text(f"{task.fields.get('rate', '?')}/s", style="cyan")


custom = mqdm.Runtime(backend_options={"columns": (
    "{task.description}",
    rich.progress.BarColumn(bar_width=None),
    RateColumn(),
)})

# Run mqdm with the runtime
for _ in mqdm.mqdm(range(100), desc="custom field", runtime=custom, rate=42):
    time.sleep(0.05)
