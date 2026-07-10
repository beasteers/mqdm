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
import codecs
from pathlib import Path
import mqdm
from mqdm import print


ROOT = Path(__file__).resolve().parents[1]
SNIPPETS_DIR = ROOT / "docs" / "snippets"
CASTS_DIR = ROOT / "docs" / "assets" / "casts"
WIDTH = 100
HEIGHT = 18
CAST_OPTIONS = {
    # Path("home/why_mqdm.py"): {"hold_after_exit": 5.0},
    Path("home/main.py"): {"hold_after_exit": 1.0, "width": 80, "height": 16},
    # `input` drives an interactive snippet: each step waits for `trigger`
    # (a substring of recent output, or a delay in seconds) then types `text`
    # into the process. A per-step timeout guarantees the recording never hangs.
    Path("patterns/pause.py"): {
        "input": [
            ("In [", "i\n"),           # inspect the live loop variable
            ("In [", "data[i]\n"),     # …and the data collected so far
            ("In [", "exit\n"),        # leave the shell -> bars resume
        ],
        "hold_after_exit": 2.0,
    },
}


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
    options = CAST_OPTIONS.get(rel, {})
    width = int(options.get("width", WIDTH))
    height = int(options.get("height", HEIGHT))

    env = os.environ.copy()
    env.pop("NO_COLOR", None)
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "COLUMNS": str(width),
            "LINES": str(height),
            "TERM": "xterm-256color",
            "CLICOLOR_FORCE": "1",
            "FORCE_COLOR": "1",
            "MQDM_DOCS_SLEEP_SCALE": "2.4",
            "PYTHONPATH": str(ROOT) + os.pathsep + env.get("PYTHONPATH", ""),
        }
    )

    master_fd, slave_fd = pty.openpty()
    set_winsize(slave_fd, height, width)
    decoder = codecs.getincrementaldecoder("utf-8")("replace")

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

    # Normalize scripted input steps to (trigger, text, timeout).
    input_steps = [
        (step[0], step[1], step[2] if len(step) > 2 else 15.0)
        for step in options.get("input", [])
    ]
    step_i = 0
    step_started = time.monotonic()
    acc = ""  # recent output, used to match substring triggers

    def drive_input() -> None:
        nonlocal step_i, step_started, acc
        while step_i < len(input_steps):
            trigger, text, timeout = input_steps[step_i]
            now = time.monotonic()
            if isinstance(trigger, (int, float)):
                fire = (now - step_started) >= trigger
            else:
                fire = trigger in acc or (now - step_started) >= timeout
            if not fire:
                break
            os.write(master_fd, text.encode())
            step_i += 1
            step_started = now
            acc = ""

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
                text = decoder.decode(chunk)
                if text:
                    events.append([dt, "o", text])
                    acc = (acc + text)[-4096:]
            elif proc.poll() is not None:
                break
        drive_input()
        if proc.poll() is not None and not ready:
            break

    tail = decoder.decode(b"", final=True)
    if tail:
        dt = round(time.monotonic() - started, 3)
        events.append([dt, "o", tail])

    hold_after_exit = float(options.get("hold_after_exit", 3.0) or 0.0)
    if hold_after_exit > 0 and events:
        last_dt = float(events[-1][0])
        # Preserve a quiet tail in the timeline without changing the final frame.
        events.append([round(last_dt + hold_after_exit, 3), "o", ""])

    os.close(master_fd)
    proc.wait()
    if proc.returncode != 0:
        print(f"❌ {snippet.relative_to(ROOT)} failed with exit code {proc.returncode}")
        return
        # raise SystemExit(f"recording failed for {snippet} with exit code {proc.returncode}")

    header = {
        "version": 2,
        "width": width,
        "height": height,
        "timestamp": int(time.time()),
        "env": {"SHELL": "/bin/zsh", "TERM": "xterm-256color"},
    }
    with cast_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    print(f"✅ {cast_path.relative_to(ROOT)}")
    return cast_path


def main(*snippets, n_workers=20) -> int:
    snippets = iter_snippets() if not snippets else [ROOT / arg for arg in snippets]

    mqdm.pool(
        record,
        snippets,
        desc="Recording snippets",
        pool_mode="thread",
        n_workers=n_workers,
    )


if __name__ == "__main__":
    import fire
    fire.Fire(main)
