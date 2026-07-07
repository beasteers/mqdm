#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pty
import select
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SNIPPETS_DIR = ROOT / "docs" / "snippets"
CASTS_DIR = ROOT / "docs" / "assets" / "casts"
WIDTH = 120
HEIGHT = 18


def iter_snippets() -> list[Path]:
    return sorted(
        path
        for path in SNIPPETS_DIR.rglob("*.py")
        if "__pycache__" not in path.parts and not path.name.startswith("_")
    )


def set_winsize(fd: int, rows: int, cols: int) -> None:
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    termios.TIOCSWINSZ
    import fcntl
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def record(snippet: Path) -> Path:
    rel = snippet.relative_to(SNIPPETS_DIR)
    cast_path = CASTS_DIR / rel.with_suffix(".cast")
    cast_path.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.pop("NO_COLOR", None)
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "COLUMNS": str(WIDTH),
            "LINES": str(HEIGHT),
            "TERM": "xterm-256color",
            "CLICOLOR_FORCE": "1",
            "FORCE_COLOR": "1",
            "MQDM_DOCS_SLEEP_SCALE": "2.4",
            "PYTHONPATH": str(ROOT) + os.pathsep + env.get("PYTHONPATH", ""),
        }
    )

    master_fd, slave_fd = pty.openpty()
    set_winsize(slave_fd, HEIGHT, WIDTH)

    cmd = [sys.executable, str(snippet)]
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        env=env,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)

    events: list[list[object]] = []
    started = time.monotonic()
    while True:
        ready, _, _ = select.select([master_fd], [], [], 0.05)
        if master_fd in ready:
            try:
                chunk = os.read(master_fd, 65536)
            except OSError:
                chunk = b""
            if chunk:
                dt = round(time.monotonic() - started, 3)
                events.append([dt, "o", chunk.decode("utf-8", errors="replace")])
            elif proc.poll() is not None:
                break
        if proc.poll() is not None and not ready:
            break

    os.close(master_fd)
    proc.wait()
    if proc.returncode != 0:
        raise SystemExit(f"recording failed for {snippet} with exit code {proc.returncode}")

    header = {
        "version": 2,
        "width": WIDTH,
        "height": HEIGHT,
        "timestamp": int(time.time()),
        "env": {"SHELL": "/bin/zsh", "TERM": "xterm-256color"},
    }
    with cast_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return cast_path


def main(*snippets) -> int:
    snippets = iter_snippets() if not snippets else [ROOT / arg for arg in snippets]
    for snippet in snippets:
        cast_path = record(snippet)
        print(f"recorded {snippet.relative_to(ROOT)} -> {cast_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    import fire
    fire.Fire(main)
