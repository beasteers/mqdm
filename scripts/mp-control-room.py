#!/usr/bin/env python3
from __future__ import annotations

import io
import logging
import os
import queue
import random
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fire
import mqdm
from rich.console import Console, Group
from rich.pretty import Pretty
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, Footer, Header, Log, Static, TabPane, TabbedContent


STATUS_ICON = {
    "pending": "☐",
    "running": "◉",
    "complete": "☑",
    "failed": "✖",
}

STATUS_RANK = {
    "running": 0,
    "pending": 1,
    "failed": 2,
    "complete": 3,
}

QUEUE_WORKER_KEY = "queue"

LOG_TAIL = 20
TITLE_STYLE = "bold #b8dff2"
MUTED_STYLE = "#95a6b3"
ERROR_STYLE = "bold #ff7a90"


def _preview(value: Any, limit: int = 96) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _worker_dom_id(worker_key: Any) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in str(worker_key))


def _pane_id(worker_key: str) -> str:
    return f"worker-pane-{_worker_dom_id(worker_key)}"


def _detail_id(worker_key: str) -> str:
    return f"worker-detail-{_worker_dom_id(worker_key)}"


def _render_print_message(*args: Any, **kw: Any) -> str:
    console = Console(file=io.StringIO(), force_terminal=False, color_system=None, width=120)
    console.print(*args, **kw)
    return console.file.getvalue().rstrip()


@dataclass
class WorkItem:
    item_id: int
    label: str
    job_repr: str
    status: str = "pending"
    worker_key: str | None = None
    result_value: Any = None
    error_summary: str | None = None
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=128))


@dataclass
class WorkerView:
    worker_key: str
    label: str
    index: int = 0
    current_item_id: int | None = None
    recent_item_ids: deque[int] = field(default_factory=lambda: deque(maxlen=8))


class ControlRoomModel:
    """UI-agnostic control-room state: the work-item / worker model plus the
    event reducer. Holds no Textual references, so it can be driven and inspected
    independently of the app."""

    def __init__(self, specs: list[dict[str, Any]]) -> None:
        self.work_items: dict[int, WorkItem] = {
            spec["item_id"]: WorkItem(item_id=spec["item_id"], label=spec["label"], job_repr=spec["job_repr"])
            for spec in specs
        }
        self.worker_views: dict[str, WorkerView] = {}
        self.pool_done: bool = False
        self.pool_traceback: str | None = None

    def ordered_items(self) -> list[WorkItem]:
        return sorted(self.work_items.values(), key=lambda item: (STATUS_RANK[item.status], item.item_id))

    def ensure_queue_worker(self) -> None:
        if QUEUE_WORKER_KEY not in self.worker_views:
            self.worker_views[QUEUE_WORKER_KEY] = WorkerView(worker_key=QUEUE_WORKER_KEY, label=QUEUE_WORKER_KEY)

    def real_worker_keys(self) -> list[str]:
        return [key for key in self.worker_views if key != QUEUE_WORKER_KEY]

    def _ensure_worker(self, worker_key: str) -> WorkerView:
        worker = self.worker_views.get(worker_key)
        if worker is None:
            index = len(self.real_worker_keys()) + 1
            worker = self.worker_views[worker_key] = WorkerView(worker_key=worker_key, label=f"worker {index}", index=index)
        return worker

    def apply_event(self, event: dict[str, Any]) -> bool:
        """Fold one event into the model. Returns whether anything changed."""
        event_type = event["type"]
        if event_type == "pool_results":
            for r in event["results"]:      # mqdm Result records, correlated by index
                item = self.work_items.get(r.index)
                if item is None:
                    continue
                if r.ok:
                    item.result_value = r.value
                else:
                    item.error_summary = _preview(r.error)
            self.pool_done = True
            return True
        if event_type == "pool_error":
            self.pool_done = True
            self.pool_traceback = event.get("traceback")
            return True

        # mqdm stamps every event with a context carrying worker identity and the
        # task index (see Runtime.set_base_context / the pool's _task_call).
        context = event.get("context", {})
        item = self.work_items.get(context.get("task_index"))
        worker_key = context.get("worker")
        worker = self._ensure_worker(worker_key) if worker_key is not None else None
        if item is None or worker is None:
            return False

        if event_type == "task_started":
            item.status = "running"
            item.worker_key = worker_key
            item.result_value = None
            item.error_summary = None
            worker.current_item_id = item.item_id
            return True
        if event_type in ("log", "print"):
            item.logs.append(self._event_message(event))
            return True
        if event_type == "task_finished":
            item.status = "complete"
            worker.recent_item_ids.append(item.item_id)
            worker.current_item_id = None
            return True
        if event_type == "task_failed":
            item.status = "failed"
            item.error_summary = _preview(event.get("error", ""))
            worker.recent_item_ids.append(item.item_id)
            worker.current_item_id = None
            return True
        return False

    @staticmethod
    def _event_message(event: dict[str, Any]) -> str:
        # log events arrive pre-rendered; print events carry raw args/kw (rendered
        # here, on the consumer side, so nothing extra rides the event stream).
        if "message" in event:
            return event["message"]
        return _render_print_message(*event.get("args", ()), **event.get("kw", {}))

    def detail_item_for_worker(self, worker_key: str, selected_item_id: int) -> WorkItem | None:
        selected = self.work_items.get(selected_item_id)
        if worker_key == QUEUE_WORKER_KEY:
            if selected is not None and selected.status == "pending":
                return selected
            return next((item for item in self.ordered_items() if item.status == "pending"), None)
        if selected is not None and selected.worker_key == worker_key:
            return selected
        worker = self.worker_views.get(worker_key)
        if worker is None:
            return None
        if worker.current_item_id is not None:
            return self.work_items.get(worker.current_item_id)
        if worker.recent_item_ids:
            return self.work_items.get(worker.recent_item_ids[-1])
        return None

    def logs_for_worker(self, worker_key: str, worker: WorkerView, item: WorkItem | None) -> tuple[str, list[str]]:
        if worker_key == QUEUE_WORKER_KEY or item is not None:
            header = item.label if item is not None else "idle"
        elif worker.current_item_id is not None:
            current_item = self.work_items.get(worker.current_item_id)
            header = current_item.label if current_item is not None else "idle"
        else:
            header = "idle"
        lines = list(item.logs)[-LOG_TAIL:] if item is not None and item.logs else []
        return header, lines


class WorkerDetailTabs(Widget):
    DEFAULT_CSS = """
    WorkerDetailTabs {
        height: 1fr;
        width: 1fr;
        layout: vertical;
    }

    WorkerDetailTabs > TabbedContent {
        height: 1fr;
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        with TabbedContent():
            with TabPane("logs"):
                yield Log(id="worker-log", classes="worker-log", auto_scroll=False, highlight=True)
            with TabPane("input"):
                with VerticalScroll(classes="worker-detail-scroll"):
                    yield Static("", id="worker-input", classes="worker-detail-body")
            with TabPane("result"):
                with VerticalScroll(classes="worker-detail-scroll"):
                    yield Static("", id="worker-result", classes="worker-detail-body")


def _make_job_specs(
    jobs: list[Any],
    *,
    label: Callable[[Any, int], str] | None = None,
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for item_id, job in enumerate(jobs):
        item_label = label(job, item_id) if label is not None else _preview(job, limit=72)
        specs.append({"item_id": item_id, "label": item_label, "item": job, "job_repr": repr(job)})
    return specs


def _pool_thread(
    *,
    fn: Callable[..., Any],
    jobs: list[Any],
    runtime: mqdm.Runtime,
    event_queue: Any,
    desc: str,
    n_workers: int,
    pool_mode: str,
    fn_kw: dict[str, Any] | None,
) -> None:
    # No wrapper: mqdm emits task_started/finished/failed and tags every event
    # with worker + task_index context (because runtime.on_event is set).
    # as_result_=True returns Result records so values correlate to items by
    # index — no dependence on completion order.
    try:
        results = list(mqdm.pool(
            fn,
            jobs,
            runtime=runtime,
            desc=desc,
            n_workers=n_workers,
            pool_mode=pool_mode,
            as_result_=True,
            squeeze_=False,
            bar_kw={
                "start": False,
                "progress_kw": {
                    "auto_refresh": False,
                    "redirect_stdout": False,
                    "redirect_stderr": False,
                    "expand": True,
                    "silent": True,
                },
            },
            **(fn_kw or {}),
        ))
        event_queue.put({"type": "pool_results", "results": results})
    except BaseException:
        event_queue.put({
            "type": "pool_error",
            "traceback": traceback.format_exc(),
        })


def _detail_panel(title: str, body: Any, *, title_style: str = TITLE_STYLE) -> Group:
    if isinstance(body, str):
        body = Text(body, style=MUTED_STYLE)
    return Group(Text(title, style=title_style), body)


class ControlRoomApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
        background: #0b0d12;
        color: #e8edf2;
    }

    #main {
        height: 1fr;
        layout: horizontal;
    }

    #queue-pane {
        width: 38;
        min-width: 32;
        border: round #3a5a6a;
        margin: 1 0 1 1;
    }

    #right-pane {
        width: 1fr;
        margin: 1 1 1 1;
        layout: vertical;
    }

    #workers-pane {
        height: 1fr;
        border: round #4d7386;
    }

    #worker-tabs {
        height: 1fr;
        width: 1fr;
    }

    #progress-pane {
        height: 12;
        border: round #8e7a35;
        margin: 0 1 1 1;
        padding: 0 1;
    }

    #progress-render {
        height: 1fr;
    }

    #queue {
        height: 1fr;
    }

    .worker-log {
        height: 1fr;
        background: #0d1017;
    }

    .worker-detail-scroll {
        height: 1fr;
        background: #0d1017;
    }

    .worker-detail-body {
        padding: 0 1;
    }

    .section-title {
        text-style: bold;
        color: #b8dff2;
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("up", "queue_up", "Up"),
        ("down", "queue_down", "Down"),
        ("k", "queue_up", "Up"),
        ("j", "queue_down", "Down"),
    ]

    selected_item_id = reactive(0)
    active_worker_key = reactive("")

    def __init__(
        self,
        *,
        fn: Callable[..., Any],
        jobs: list[Any],
        desc: str,
        n_workers: int,
        pool_mode: str,
        refresh_hz: int,
        refresh_per_second: float = 20.0,
        label: Callable[[Any, int], str] | None = None,
        install_logging: bool = True,
        logger: logging.Logger | None = None,
        log_level: int = logging.INFO,
        **fn_kw: Any,
    ) -> None:
        super().__init__()
        self.specs = _make_job_specs(jobs, label=label)
        self.model = ControlRoomModel(self.specs)
        self.refresh_hz = refresh_hz
        self.refresh_per_second = refresh_per_second
        self.queue_row_map: list[int] = []

        self.local_events: queue.Queue = queue.Queue()
        self.stream = mqdm.events.EventStream(self.local_events.put)
        self.runtime = self.stream.runtime
        if install_logging:
            self.runtime.install_logging(logger=logger, level=log_level, capture_warnings="process")

        self.pool_thread = threading.Thread(
            target=_pool_thread,
            kwargs={
                "fn": fn,
                "jobs": [spec["item"] for spec in self.specs],
                "runtime": self.runtime,
                "event_queue": self.local_events,
                "desc": desc,
                "n_workers": n_workers,
                "pool_mode": pool_mode,
                "fn_kw": fn_kw,
            },
            daemon=True,
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="queue-pane"):
                yield Static("Task Queue", classes="section-title")
                queue_table = DataTable(id="queue", cursor_type="row", show_header=False, show_row_labels=False, zebra_stripes=True)
                queue_table.add_columns("", "", "task")
                yield queue_table
            with Vertical(id="right-pane"):
                with Vertical(id="workers-pane"):
                    yield TabbedContent(id="worker-tabs")
        with Vertical(id="progress-pane"):
            yield Static("Progress", classes="section-title")
            yield Static("", id="progress-render")
        yield Footer()

    def on_mount(self) -> None:
        if self.specs:
            self.selected_item_id = self.specs[0]["item_id"]
        self.stream.start()
        self.pool_thread.start()
        self.set_interval(1 / max(self.refresh_hz, 1), self._poll_events)
        # Paint the progress pane on a clock (like Progress's own Live refresh
        # thread), decoupled from event arrival, so time-based columns animate
        # smoothly instead of only ticking when an event lands.
        self.set_interval(1 / max(self.refresh_per_second, 1), self._refresh_progress)
        self.call_after_refresh(self._refresh_all)

    def on_unmount(self) -> None:
        if self.pool_thread.is_alive():
            self.pool_thread.join(timeout=1)
        self.stream.stop()
        self.runtime.uninstall_logging()
        self.runtime.atexit()

    def action_queue_up(self) -> None:
        self._move_queue_selection(-1)

    def action_queue_down(self) -> None:
        self._move_queue_selection(1)

    @on(DataTable.RowHighlighted, "#queue")
    @on(DataTable.RowSelected, "#queue")
    def _on_queue_row(self, event: DataTable.RowHighlighted | DataTable.RowSelected) -> None:
        try:
            self.selected_item_id = self.queue_row_map[event.cursor_row]
        except Exception:
            return

    @on(TabbedContent.TabActivated, "#worker-tabs")
    def _on_worker_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        pane_id = getattr(event.pane, "id", "") or ""
        for worker_key in self.model.worker_views:
            if _pane_id(worker_key) == pane_id:
                self.active_worker_key = worker_key
                break

    def watch_selected_item_id(self, item_id: int) -> None:
        if not self.is_mounted:
            return
        self._refresh_worker_tabs()
        self._activate_tab_for_selection()

    def _move_queue_selection(self, delta: int) -> None:
        ids = [item.item_id for item in self.model.ordered_items()]
        if not ids:
            return
        try:
            index = ids.index(self.selected_item_id)
        except ValueError:
            index = 0
        next_index = max(0, min(index + delta, len(ids) - 1))
        self.selected_item_id = ids[next_index]
        self.query_one("#queue", DataTable).move_cursor(row=next_index, animate=False)

    def _activate_tab_for_selection(self) -> None:
        # Switch to the selected item's worker tab (the queue->worker link). Only
        # called from user-driven selection changes, never the periodic refresh,
        # so the app never steals the active tab on its own.
        item = self.model.work_items.get(self.selected_item_id)
        if item is None:
            return
        worker_key = QUEUE_WORKER_KEY if item.status == "pending" else item.worker_key
        if not worker_key or worker_key not in self.model.worker_views:
            return
        self.active_worker_key = worker_key
        try:
            self.query_one("#worker-tabs", TabbedContent).active = _pane_id(worker_key)
        except Exception:
            pass

    def _render_input_detail(self, item: WorkItem | None) -> Any:
        if item is None:
            return _detail_panel("input", "No task selected for this worker.")
        return _detail_panel("input", Text(item.job_repr))

    def _render_result_detail(self, item: WorkItem | None) -> Any:
        if item is None:
            return _detail_panel("result", "No task selected for this worker.")
        if item.status == "complete" and item.result_value is not None:
            return _detail_panel("result", Pretty(item.result_value, expand_all=False))
        if item.error_summary:
            return _detail_panel("error", Text(item.error_summary), title_style=ERROR_STYLE)
        if item.status == "pending":
            return _detail_panel("result", "Pending. Waiting for a worker to claim this task.")
        if item.status == "running":
            return _detail_panel("result", "Task is still running.")
        return _detail_panel("result", "Task completed with no return value.")

    def _refresh_worker_tab(self, worker_key: str, worker: WorkerView) -> None:
        try:
            detail = self.query_one(f"#{_detail_id(worker_key)}", WorkerDetailTabs)
        except NoMatches:
            self._ensure_worker_tab(worker_key)
            return
        log = detail.query_one("#worker-log", Log)
        input_body = detail.query_one("#worker-input", Static)
        result_body = detail.query_one("#worker-result", Static)
        item = self.model.detail_item_for_worker(worker_key, self.selected_item_id)
        header, lines = self.model.logs_for_worker(worker_key, worker, item)
        log.clear()
        log.write_line(f"{worker.label} · {header}")
        log.write_line("")
        if lines:
            for line in lines:
                log.write_line(line)
        else:
            log.write_line("No queue logs yet." if worker_key == QUEUE_WORKER_KEY else "No worker logs yet.")
        input_body.update(self._render_input_detail(item))
        result_body.update(self._render_result_detail(item))

    def _poll_events(self) -> None:
        dirty = False
        while True:
            try:
                event = self.local_events.get_nowait()
            except queue.Empty:
                break
            dirty = self.model.apply_event(event) or dirty

        if dirty:
            self._refresh_all()
        if self.model.pool_done and not self.pool_thread.is_alive() and self.local_events.empty():
            self.exit()

    def _ensure_worker_tab(self, worker_key: str) -> None:
        worker = self.model.worker_views[worker_key]
        tabs = self.query_one("#worker-tabs", TabbedContent)
        pane_id = _pane_id(worker_key)
        if any(getattr(pane, "id", None) == pane_id for pane in tabs.query(TabPane)):
            return
        detail = WorkerDetailTabs(id=_detail_id(worker_key))
        tab = TabPane(worker.label, detail, id=pane_id)
        tabs.add_pane(tab)
        if self.active_worker_key == worker_key:
            tabs.active = pane_id

    def _refresh_all(self) -> None:
        self._refresh_queue()
        self._refresh_worker_tabs()
        # progress pane is painted on its own timer (see on_mount)

    def _refresh_queue(self) -> None:
        table = self.query_one("#queue", DataTable)
        ordered = self.model.ordered_items()
        self.queue_row_map = [item.item_id for item in ordered]
        table.clear(columns=False)
        for item in ordered:
            icon = STATUS_ICON[item.status]
            worker = self.model.worker_views.get(item.worker_key or "")
            badge = ""
            if item.status != "pending" and worker is not None:
                badge = str(worker.index)
            table.add_row(icon, badge, item.label)
        if self.queue_row_map:
            try:
                row_index = self.queue_row_map.index(self.selected_item_id)
            except ValueError:
                row_index = 0
                self.selected_item_id = self.queue_row_map[0]
            table.move_cursor(row=row_index, animate=False)

    def _refresh_worker_tabs(self) -> None:
        for worker_key in self.model.real_worker_keys():
            self._refresh_worker_tab(worker_key, self.model.worker_views[worker_key])
        self.model.ensure_queue_worker()
        self._refresh_worker_tab(QUEUE_WORKER_KEY, self.model.worker_views[QUEUE_WORKER_KEY])

    def _refresh_progress(self) -> None:
        self.query_one("#progress-render", Static).update(self.runtime.pbar or "")


def run_control_room(
    fn: Callable[..., Any],
    jobs: list[Any],
    *,
    desc: str | None = None,
    n_workers: int = 4,
    pool_mode: str = "process",
    refresh_hz: int = 12,
    refresh_per_second: float = 20.0,
    label: Callable[[Any, int], str] | None = None,
    install_logging: bool = True,
    logger: logging.Logger | None = None,
    log_level: int = logging.INFO,
    **fn_kw: Any,
) -> None:
    app = ControlRoomApp(
        fn=fn,
        jobs=list(jobs),
        desc=desc or getattr(fn, "__name__", "jobs"),
        n_workers=n_workers,
        pool_mode=pool_mode,
        refresh_hz=refresh_hz,
        refresh_per_second=refresh_per_second,
        label=label,
        install_logging=install_logging,
        logger=logger,
        log_level=log_level,
        **fn_kw,
    )
    app.run()
    if app.model.pool_traceback:
        raise RuntimeError(app.model.pool_traceback)


def _demo_job(sensor_id: str, *, csv_dir: str, seed: int = 0) -> int:
    logger = logging.getLogger("mp-control-room.demo")
    rng = random.Random(seed + sum(ord(ch) for ch in sensor_id))
    paths = [f"{csv_dir}/{sensor_id}/chunk-{i:02d}.csv" for i in range(rng.randint(13, 40))]
    desc = lambda path, i: f"{sensor_id} - {os.path.basename(path)}"
    total = 0
    for path in mqdm.mqdm(paths, desc=desc, leave=False):
        time.sleep(0.05)
        # time.sleep(rng.uniform(0.15, 0.35))
        # batches = rng.randint(8, 48)
        # for _ in mqdm.mqdm(range(batches), desc=f"parse {os.path.basename(path)}", leave=False):
        #     time.sleep(rng.uniform(0.0002, 0.0006))
        #     total += 1
        if rng.random() < 0.35:
            mqdm.print("remarkable file", path)
        logger.info("processed %s", path)
    return total


def main(
    n_items: int = 8,
    n_workers: int = 3,
    seed: int = 7,
    refresh_hz: int = 12,
    refresh_per_second: float = 20.0,
    csv_dir: str = "data/csv",
) -> None:
    sensor_ids = [f"sensor-{i:02d}" for i in range(n_items)]
    jobs = [mqdm.args(sensor_id, csv_dir=csv_dir, seed=seed + i * 11) for i, sensor_id in enumerate(sensor_ids)]
    run_control_room(
        _demo_job,
        jobs,
        desc="process sensors",
        n_workers=n_workers,
        pool_mode="process",
        refresh_hz=refresh_hz,
        refresh_per_second=refresh_per_second,
        label=lambda job, _i: mqdm.args.from_item(job).a[0],
        install_logging=True,
    )


if __name__ == "__main__":
    fire.Fire(main)
