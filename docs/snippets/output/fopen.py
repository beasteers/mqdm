from pathlib import Path

import mqdm


path = Path("docs/assets/demo-text.txt")
path.write_text("alpha\nbeta\ngamma\ndelta\nepsilon\n", encoding="utf-8")

with mqdm.fopen(path, "r") as f:
    for line in f:
        _ = line.strip()
