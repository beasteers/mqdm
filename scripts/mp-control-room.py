#!/usr/bin/env python3
from __future__ import annotations

import io
import logging
import multiprocessing as mp
import os
import queue
import random
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fire
import mqdm
from mqdm import progress_columns
from mqdm.executor import _clear_local, _get_local, _set_local
from mqdm.proxy import Progress as MQDMProgress
from rich import progress as rich_progress
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
QUEUE_WORKER_LABEL = "queue"


def _progress_columns() -> tuple[Any, ...]:
    return (
        "[progress.description]{task.description}",
        rich_progress.BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.0f}%",
        progress_columns.MofNColumn(),
        progress_columns.SpeedColumn(),
        progress_columns.TimeElapsedColumn(compact=True),
        rich_progress.TimeRemainingColumn(compact=True),
        rich_progress.SpinnerColumn(),
    )


def _preview(value: Any, limit: int = 96) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _worker_key() -> str:
    process = mp.current_process()
    return f"{process.name}:{os.getpid()}"


def _worker_dom_id(worker_key: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in worker_key)


def _worker_badge(worker_label: str | None) -> str:
    if not worker_label:
        return ""
    parts = worker_label.split()
    if parts and parts[-1].isdigit():
        return parts[-1]
    return worker_label


def _render_print_message(*args: Any, **kw: Any) -> str:
    console = Console(file=io.StringIO(), force_terminal=False, color_system=None, width=120)
    console.print(*args, **kw)
    return console.file.getvalue().rstrip()


class ControlRoomRuntime(mqdm.Runtime):
    def __init__(self, event_queue: Any) -> None:
        super().__init__()
        self.event_queue = event_queue

    def new_pbar(self, pool_mode: str | None = None, bytes: bool = False, **kw: Any):
        kw.setdefault("auto_refresh", False)
        kw.setdefault("redirect_stdout", False)
        kw.setdefault("redirect_stderr", False)
        kw.setdefault("expand", True)
        if pool_mode == "process":
            return self.get_manager().mqdm_Progress(*_progress_columns(), **kw)
        return MQDMProgress(*_progress_columns(), **kw)

    def get_pbar(self, pool_mode: str | None = None, start: bool = True, **kw: Any):
        pbar = self.pbar
        if pbar is None:
            pbar = self.pbar = self.new_pbar(pool_mode=pool_mode, **kw)
        elif pool_mode == "process" and not pbar.multiprocess:
            pbar = self.pbar = pbar.convert_proxy(runtime=self)
        return pbar

    def emit(self, event_type: str, **data: Any) -> None:
        event = {"type": event_type, "timestamp": time.time(), **data}
        try:
            self.event_queue.put(event)
        except Exception:
            pass

    def print(self, *args: Any, **kw: Any) -> None:
        context = dict(_get_local("control_room_context", {}) or {})
        message = _render_print_message(*args, **kw)
        self.emit("log", message=message, **context)


@dataclass
class WorkItem:
    item_id: int
    label: str
    job_repr: str
    status: str = "pending"
    worker_key: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    result_value: Any = None
    error_summary: str | None = None
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=128))


@dataclass
class WorkerView:
    worker_key: str
    label: str
    current_item_id: int | None = None
    current_item_label: str = ""
    recent_item_ids: deque[int] = field(default_factory=lambda: deque(maxlen=8))
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=128))


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

    def __init__(self, dom_id: str, worker_label: str) -> None:
        super().__init__(id=f"worker-detail-{dom_id}")
        self.dom_id = dom_id
        self.worker_label = worker_label

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


def _run_control_room_job(spec: dict[str, Any], *, target: Callable[..., Any], fn_kw: dict[str, Any] | None = None) -> Any:
    runtime = mqdm._current_runtime()
    worker_key = _worker_key()
    context = {
        "item_id": spec["item_id"],
        "item_label": spec["label"],
        "worker_key": worker_key,
    }
    _set_local(control_room_context=context)
    runtime.emit("started", **context)
    try:
        call_arg = mqdm.args.from_item(spec["item"])
        result = target(*call_arg.a, **{**(fn_kw or {}), **call_arg.kw})
    except BaseException as exc:
        runtime.emit("failed", error_summary=_preview(exc), **context)
        raise
    else:
        runtime.emit("finished", result_summary=_preview(result), **context)
        return {"item_id": spec["item_id"], "value": result}
    finally:
        _clear_local("control_room_context")


def _pool_thread(
    *,
    fn: Callable[..., Any],
    specs: list[dict[str, Any]],
    runtime: ControlRoomRuntime,
    result_queue: queue.Queue,
    desc: str,
    n_workers: int,
    pool_mode: str,
    ordered: bool,
    fn_kw: dict[str, Any] | None,
) -> None:
    try:
        results = mqdm.pool(
            _run_control_room_job,
            specs,
            runtime=runtime,
            desc=desc,
            n_workers=n_workers,
            pool_mode=pool_mode,
            ordered_=ordered,
            squeeze_=False,
            target=fn,
            fn_kw=fn_kw or {},
        )
        result_queue.put({"type": "pool_results", "results": results})
    except BaseException as exc:
        result_queue.put({"type": "pool_error", "error": repr(exc)})


def _bridge_events(event_queue: Any, result_queue: queue.Queue, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            result_queue.put(event_queue.get(timeout=0.1))
        except queue.Empty:
            continue
        except Exception:
            if stop.is_set():
                break


def _snapshot_progress_renderable(runtime: ControlRoomRuntime):
    pbar = runtime.pbar
    if pbar is None:
        return None
    try:
        if getattr(pbar, "multiprocess", False):
            mirror = MQDMProgress(*_progress_columns(), auto_refresh=False, expand=True)
            tasks = pbar.dump_tasks()
            for task_id in sorted(tasks):
                mirror.load_task(tasks[task_id], start=False)
            return mirror.get_renderable()
        return pbar.get_renderable()
    except Exception:
        return None


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

    #progress-meta {
        color: #95a6b3;
        margin: 0 1;
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

    .meta {
        color: #95a6b3;
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
        ordered: bool,
        refresh_hz: int,
        label: Callable[[Any, int], str] | None = None,
        install_logging: bool = True,
        logger: logging.Logger | None = None,
        log_level: int = logging.INFO,
        **fn_kw: Any,
    ) -> None:
        super().__init__()
        self.specs = _make_job_specs(jobs, label=label)
        self.work_items = {
            spec["item_id"]: WorkItem(item_id=spec["item_id"], label=spec["label"], job_repr=spec["job_repr"])
            for spec in self.specs
        }
        self.desc = desc
        self.n_workers = n_workers
        self.pool_mode = pool_mode
        self.ordered = ordered
        self.refresh_hz = refresh_hz
        self.worker_views: dict[str, WorkerView] = {}
        self.pool_results: list[dict[str, Any]] | None = None
        self.pool_done = False
        self.errors = 0
        self.queue_row_map: list[int] = []

        self.mp_manager = mp.Manager()
        self.event_queue = self.mp_manager.Queue()
        self.runtime = ControlRoomRuntime(self.event_queue)
        if install_logging:
            self.runtime.install_logging(logger=logger, level=log_level, capture_warnings="process")

        self.local_events: queue.Queue = queue.Queue()
        self.stop_bridge = threading.Event()
        self.pool_thread = threading.Thread(
            target=_pool_thread,
            kwargs={
                "fn": fn,
                "specs": self.specs,
                "runtime": self.runtime,
                "result_queue": self.local_events,
                "desc": desc,
                "n_workers": n_workers,
                "pool_mode": pool_mode,
                "ordered": ordered,
                "fn_kw": fn_kw,
            },
            daemon=True,
        )
        self.bridge_thread = threading.Thread(
            target=_bridge_events,
            args=(self.event_queue, self.local_events, self.stop_bridge),
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
            yield Static("", id="progress-meta")
            yield Static("", id="progress-render")
        yield Footer()

    def on_mount(self) -> None:
        if self.specs:
            self.selected_item_id = self.specs[0]["item_id"]
        self.pool_thread.start()
        self.bridge_thread.start()
        self.set_interval(1 / max(self.refresh_hz, 1), self._poll_events)
        self.call_after_refresh(self._refresh_all)

    def on_unmount(self) -> None:
        self.stop_bridge.set()
        if self.pool_thread.is_alive():
            self.pool_thread.join(timeout=1)
        if self.bridge_thread.is_alive():
            self.bridge_thread.join(timeout=1)
        self.runtime.uninstall_logging()
        self.runtime.atexit()
        self.mp_manager.shutdown()

    def action_queue_up(self) -> None:
        self._move_queue_selection(-1)

    def action_queue_down(self) -> None:
        self._move_queue_selection(1)

    @on(DataTable.RowHighlighted, "#queue")
    def _on_queue_highlighted(self, event: DataTable.RowHighlighted) -> None:
        try:
            self.selected_item_id = self.queue_row_map[event.cursor_row]
        except Exception:
            return

    @on(DataTable.RowSelected, "#queue")
    def _on_queue_selected(self, event: DataTable.RowSelected) -> None:
        try:
            self.selected_item_id = self.queue_row_map[event.cursor_row]
        except Exception:
            return

    @on(TabbedContent.TabActivated, "#worker-tabs")
    def _on_worker_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        pane_id = getattr(event.pane, "id", "") or ""
        if pane_id.startswith("worker-pane-"):
            dom_id = pane_id.removeprefix("worker-pane-")
            for worker_key in self.worker_views:
                if _worker_dom_id(worker_key) == dom_id:
                    self.active_worker_key = worker_key
                    break

    def watch_selected_item_id(self, item_id: int) -> None:
        if not self.is_mounted:
            return
        self._sync_active_worker_to_selection()
        self._refresh_worker_tabs()

    def _ordered_items(self) -> list[WorkItem]:
        return sorted(self.work_items.values(), key=lambda item: (STATUS_RANK[item.status], item.item_id))

    def _move_queue_selection(self, delta: int) -> None:
        ids = [item.item_id for item in self._ordered_items()]
        if not ids:
            return
        try:
            index = ids.index(self.selected_item_id)
        except ValueError:
            index = 0
        next_index = max(0, min(index + delta, len(ids) - 1))
        self.selected_item_id = ids[next_index]
        self.query_one("#queue", DataTable).move_cursor(row=next_index, animate=False)

    def _sync_active_worker_to_selection(self) -> None:
        item = self.work_items.get(self.selected_item_id)
        if item is None:
            return
        if item.status == "pending":
            self.active_worker_key = QUEUE_WORKER_KEY
        elif item.worker_key and item.worker_key in self.worker_views:
            self.active_worker_key = item.worker_key

    def _detail_item_for_worker(self, worker_key: str) -> WorkItem | None:
        selected = self.work_items.get(self.selected_item_id)
        if worker_key == QUEUE_WORKER_KEY:
            if selected is not None and selected.status == "pending":
                return selected
            for item in self._ordered_items():
                if item.status == "pending":
                    return item
            return None
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

    def _render_input_detail(self, item: WorkItem | None) -> Any:
        if item is None:
            return Group(
                Text("input", style="bold #b8dff2"),
                Text("No task selected for this worker.", style="#95a6b3"),
            )
        return Group(
            Text("input", style="bold #b8dff2"),
            Text(item.job_repr),
        )

    def _render_result_detail(self, item: WorkItem | None) -> Any:
        if item is None:
            return Group(
                Text("result", style="bold #b8dff2"),
                Text("No task selected for this worker.", style="#95a6b3"),
            )
        if item.status == "complete" and item.result_value is not None:
            return Group(
                Text("result", style="bold #b8dff2"),
                Pretty(item.result_value, expand_all=False),
            )
        if item.error_summary:
            return Group(
                Text("error", style="bold #ff7a90"),
                Text(item.error_summary),
            )
        if item.status == "pending":
            return Group(
                Text("result", style="bold #b8dff2"),
                Text("Pending. Waiting for a worker to claim this task.", style="#95a6b3"),
            )
        if item.status == "running":
            return Group(
                Text("result", style="bold #b8dff2"),
                Text("Task is still running.", style="#95a6b3"),
            )
        return Group(
            Text("result", style="bold #b8dff2"),
            Text("Task completed with no return value.", style="#95a6b3"),
        )

    def _poll_events(self) -> None:
        dirty = False
        while True:
            try:
                event = self.local_events.get_nowait()
            except queue.Empty:
                break
            dirty = self._apply_event(event) or dirty

        if dirty:
            self._refresh_all()
        if self.pool_done and not self.pool_thread.is_alive() and self.local_events.empty():
            self.exit()

    def _apply_event(self, event: dict[str, Any]) -> bool:
        event_type = event["type"]
        if event_type == "pool_results":
            self.pool_results = event["results"]
            for result in self.pool_results:
                item = self.work_items.get(result["item_id"])
                if item is not None:
                    item.result_value = result["value"]
            self.pool_done = True
            return True
        if event_type == "pool_error":
            self.pool_done = True
            self.errors += 1
            return True

        item = self.work_items.get(event.get("item_id"))
        worker_key = event.get("worker_key")
        worker = None
        if worker_key:
            worker = self.worker_views.get(worker_key)
            if worker is None:
                n_real_workers = sum(1 for key in self.worker_views if key != QUEUE_WORKER_KEY)
                worker = WorkerView(worker_key=worker_key, label=f"worker {n_real_workers + 1}")
                self.worker_views[worker_key] = worker
                self.call_after_refresh(self._ensure_worker_tab, worker_key)

        if event_type == "started" and item is not None and worker is not None:
            item.status = "running"
            item.worker_key = worker_key
            item.started_at = event["timestamp"]
            item.finished_at = None
            item.result_value = None
            item.error_summary = None
            worker.current_item_id = item.item_id
            worker.current_item_label = item.label
            worker.logs.clear()
            if not self.active_worker_key:
                self.active_worker_key = worker_key
            return True

        if event_type == "log" and item is not None and worker is not None:
            line = event["message"]
            item.logs.append(line)
            worker.logs.append(line)
            return True

        if event_type == "finished" and item is not None and worker is not None:
            item.status = "complete"
            item.finished_at = event["timestamp"]
            worker.recent_item_ids.append(item.item_id)
            worker.current_item_id = None
            worker.current_item_label = ""
            return True

        if event_type == "failed" and item is not None and worker is not None:
            item.status = "failed"
            item.finished_at = event["timestamp"]
            item.error_summary = event.get("error_summary")
            worker.recent_item_ids.append(item.item_id)
            worker.current_item_id = None
            worker.current_item_label = ""
            self.errors += 1
            return True

        return False

    def _ensure_queue_worker(self) -> None:
        if QUEUE_WORKER_KEY not in self.worker_views:
            self.worker_views[QUEUE_WORKER_KEY] = WorkerView(worker_key=QUEUE_WORKER_KEY, label=QUEUE_WORKER_LABEL)

    def _ensure_worker_tab(self, worker_key: str) -> None:
        worker = self.worker_views[worker_key]
        tabs = self.query_one("#worker-tabs", TabbedContent)
        pane_id = f"worker-pane-{_worker_dom_id(worker_key)}"
        if any(getattr(pane, "id", None) == pane_id for pane in tabs.query(TabPane)):
            return
        dom_id = _worker_dom_id(worker_key)
        detail = WorkerDetailTabs(dom_id, worker.label)
        tab = TabPane(worker.label, detail, id=pane_id)
        tabs.add_pane(tab)
        if self.active_worker_key == worker_key:
            tabs.active = pane_id

    def _refresh_all(self) -> None:
        self._refresh_queue()
        self._sync_active_worker_to_selection()
        self._refresh_worker_tabs()
        self._refresh_progress()

    def _refresh_queue(self) -> None:
        table = self.query_one("#queue", DataTable)
        ordered = self._ordered_items()
        self.queue_row_map = [item.item_id for item in ordered]
        table.clear(columns=False)
        for item in ordered:
            icon = STATUS_ICON[item.status]
            worker = self.worker_views.get(item.worker_key or "")
            badge = ""
            if item.status != "pending" and worker is not None:
                badge = _worker_badge(worker.label)
            table.add_row(icon, badge, item.label)
        if self.queue_row_map:
            try:
                row_index = self.queue_row_map.index(self.selected_item_id)
            except ValueError:
                row_index = 0
                self.selected_item_id = self.queue_row_map[0]
            table.move_cursor(row=row_index, animate=False)

    def _refresh_worker_tabs(self) -> None:
        real_worker_keys = [worker_key for worker_key in self.worker_views if worker_key != QUEUE_WORKER_KEY]
        for worker_key in real_worker_keys:
            worker = self.worker_views[worker_key]
            dom_id = _worker_dom_id(worker_key)
            try:
                detail = self.query_one(f"#worker-detail-{dom_id}", WorkerDetailTabs)
            except NoMatches:
                self._ensure_worker_tab(worker_key)
                continue
            log = detail.query_one("#worker-log", Log)
            input_body = detail.query_one("#worker-input", Static)
            result_body = detail.query_one("#worker-result", Static)
            item = self._detail_item_for_worker(worker_key)
            log.clear()
            header = item.label if item is not None else worker.current_item_label or "idle"
            log.write_line(f"{worker.label} · {header}")
            log.write_line("")
            if item is not None and item.logs:
                for line in list(item.logs)[-20:]:
                    log.write_line(line)
            elif worker.logs:
                for line in list(worker.logs)[-20:]:
                    log.write_line(line)
            else:
                log.write_line("No worker logs yet.")
            input_body.update(self._render_input_detail(item))
            result_body.update(self._render_result_detail(item))
        self._ensure_queue_worker()
        queue_key = QUEUE_WORKER_KEY
        queue_dom_id = _worker_dom_id(queue_key)
        try:
            detail = self.query_one(f"#worker-detail-{queue_dom_id}", WorkerDetailTabs)
        except NoMatches:
            self._ensure_worker_tab(queue_key)
        else:
            log = detail.query_one("#worker-log", Log)
            input_body = detail.query_one("#worker-input", Static)
            result_body = detail.query_one("#worker-result", Static)
            item = self._detail_item_for_worker(queue_key)
            log.clear()
            header = item.label if item is not None else "idle"
            log.write_line(f"{QUEUE_WORKER_LABEL} · {header}")
            log.write_line("")
            if item is not None and item.logs:
                for line in list(item.logs)[-20:]:
                    log.write_line(line)
            else:
                log.write_line("No queue logs yet.")
            input_body.update(self._render_input_detail(item))
            result_body.update(self._render_result_detail(item))
        tabs = self.query_one("#worker-tabs", TabbedContent)
        if self.active_worker_key:
            try:
                tabs.active = f"worker-pane-{_worker_dom_id(self.active_worker_key)}"
            except Exception:
                pass
        elif any(item.status == "pending" for item in self.work_items.values()):
            try:
                tabs.active = f"worker-pane-{_worker_dom_id(QUEUE_WORKER_KEY)}"
            except Exception:
                pass

    def _refresh_progress(self) -> None:
        complete = sum(1 for item in self.work_items.values() if item.status == "complete")
        running = sum(1 for item in self.work_items.values() if item.status == "running")
        failed = sum(1 for item in self.work_items.values() if item.status == "failed")
        self.query_one("#progress-meta", Static).update(
            f"{complete}/{len(self.work_items)} complete · {running} active · {failed} failed"
        )
        renderable = _snapshot_progress_renderable(self.runtime)
        self.query_one("#progress-render", Static).update(renderable or "")


def run_control_room(
    fn: Callable[..., Any],
    jobs: list[Any],
    *,
    desc: str | None = None,
    n_workers: int = 4,
    pool_mode: str = "process",
    ordered: bool = False,
    refresh_hz: int = 12,
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
        ordered=ordered,
        refresh_hz=refresh_hz,
        label=label,
        install_logging=install_logging,
        logger=logger,
        log_level=log_level,
        **fn_kw,
    )
    app.run()


def _demo_job(sensor_id: str, *, csv_dir: str, seed: int = 0) -> int:
    logger = logging.getLogger("mp-control-room.demo")
    rng = random.Random(seed + sum(ord(ch) for ch in sensor_id))
    paths = [f"{csv_dir}/{sensor_id}/chunk-{i:02d}.csv" for i in range(rng.randint(13, 60))]
    desc = lambda path, i: f"{sensor_id} - {os.path.basename(path)}"
    total = 0
    for path in mqdm.mqdm(paths, desc=desc):
        time.sleep(rng.uniform(0.15, 0.35))
        batches = rng.randint(8, 48)
        for _ in mqdm.mqdm(range(batches), desc=f"parse {os.path.basename(path)}", transient=True):
            time.sleep(rng.uniform(0.02, 0.06))
            total += 1
        if rng.random() < 0.35:
            mqdm.print("remarkable file", path)
        logger.info("processed %s", path)
    return total


def main(
    n_items: int = 8,
    n_workers: int = 3,
    seed: int = 7,
    refresh_hz: int = 12,
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
        ordered=False,
        refresh_hz=refresh_hz,
        label=lambda job, _i: mqdm.args.from_item(job).a[0],
        install_logging=True,
    )


if __name__ == "__main__":
    fire.Fire(main)
