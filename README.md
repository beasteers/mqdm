# mqdm

Pretty, worker-aware progress bars for Python.

`mqdm` keeps a `tqdm`-like feel, but is designed to stay pleasant when you add:

- nested progress bars
- threads or processes
- progress-safe printing
- logging and warnings above the bars

## Install

```bash
pip install mqdm
```

## Quick look

```python
import time
import mqdm as M

for folder in M.mqdm(["cats", "clouds", "notes"], desc="indexing"):
    for _ in M.mqdm(range(5), desc=lambda _, i: f"{folder} · file {i + 1}"):
        time.sleep(0.05)
```

## Docs

The main documentation now lives in the MkDocs site under [docs](docs/index.md).

Local preview:

```bash
pip install -e ".[docs]"
mkdocs serve
```

## Tests

```bash
pip install -e ".[test]"
pytest
```
Test across multiple Python versions:
```bash
for py in 3.10 3.11 3.12 3.13 3.14 3.15; do
  echo "=== Python $py ==="
  uv run --python $py pytest tests/ -q 2>&1 || break
done
```