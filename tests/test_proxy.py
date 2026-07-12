from types import SimpleNamespace

import pytest
from rich.console import Console

import mqdm as M
from mqdm.backend import TaskState
from mqdm.command_proxy import CommandDriver, CommandProxyMixin, CommandTransportClosed, LocalTransport, QueueCommandBridge, QueueTransport, TransportCommandProxy, exposed_methods_for, proxymethod
from mqdm.progress import Progress, QueueProgressProxy


def test_load_task_restores_finished_metadata():
    progress = Progress(disable=True)
    task_id = progress.add_task("done", total=3, start=True)
    progress.update(task_id, advance=3)
    progress.stop_task(task_id)

    task = progress.tasks[task_id]
    task.finished_speed = 12.5
    snapshot = progress.dump_task(task_id)

    restored = Progress(disable=True)
    restored.load_task(snapshot, start=False)
    restored_task = restored.tasks[task_id]

    assert restored_task.finished
    assert restored_task.start_time == task.start_time
    assert restored_task.stop_time == task.stop_time
    assert restored_task.finished_time == task.finished_time
    assert restored_task.finished_speed == 12.5


def test_convert_proxy_preserves_existing_tasks_in_shadow_state():
    progress = Progress(disable=True)
    first = progress.add_task("one", total=2, start=False)
    second = progress.add_task("two", total=4, start=True, completed=1, transient=True)
    snapshot = progress.dump_tasks()
    runtime = M.Runtime()

    proxy = progress.convert_proxy(command_bridge=runtime._ensure_command_bridge())

    assert isinstance(proxy, QueueProgressProxy)
    assert proxy.dump_tasks() == snapshot
    assert set(proxy.dump_tasks()) == {first, second}


def test_load_task_advances_task_index():
    progress = Progress(disable=True)

    progress.load_task({
        "id": 7,
        "description": "restored",
        "total": 10,
        "completed": 3,
        "visible": True,
        "fields": {},
        "start_time": 1.0,
    }, start=False)

    new_task_id = progress.add_task("new", total=1)

    assert new_task_id == 8


def test_runtime_install_command_bridge_starts_and_stops():
    runtime = M.Runtime()
    progress = Progress(disable=True)
    # proxy = progress.convert_proxy(runtime=runtime)
    runtime._ensure_process_backend(progress)

    assert runtime.command_bridge is not None

    runtime.shutdown_command_bridge()

    assert runtime.command_bridge is None


def test_progress_write_prints_to_own_console():
    import io

    console = Console(file=io.StringIO(), force_terminal=True)
    progress = Progress(disable=True, console=console)

    progress.write("hello")

    assert "hello" in console.file.getvalue()


def test_runtime_get_pbar_converts_with_owning_runtime(monkeypatch):
    runtime = M.Runtime()
    progress = Progress(disable=True)
    runtime.pbar = progress
    captured = {}

    class Proxy:
        multiprocess = True

        def start(self):
            return None

    def fake_convert_proxy(*, command_bridge=None):
        captured["command_bridge"] = command_bridge
        return Proxy()

    monkeypatch.setattr(progress, "convert_proxy", fake_convert_proxy)

    proxy = runtime.get_pbar(pool_mode="process")

    assert isinstance(proxy, Proxy)
    assert runtime.pbar is proxy
    assert captured["command_bridge"] is runtime.command_bridge


class _MinimalBackend:
    multiprocess = False

    def __init__(self):
        self.tasks: dict[int, TaskState] = {}
        self.next_id = 0

    def start(self):
        return None

    def stop(self):
        return None

    def refresh(self):
        return None

    def write(self, *args, **kw):
        return None

    def add_task(self, **task_kw):
        task_id = self.next_id
        self.next_id += 1
        self.tasks[task_id] = {"id": task_id, **task_kw}
        return task_id

    def try_update(self, task_id, **task_update):
        task = self.tasks.setdefault(task_id, {"id": task_id})
        task.update(task_update)

    def dump_task(self, task_id):
        return self.tasks.get(task_id)

    def load_task(self, task, start=True):
        self.tasks[task["id"]] = dict(task)

    def pop_task(self, task_id, remove=None):
        if remove:
            return self.tasks.pop(task_id, None)
        return self.tasks.get(task_id)


class _MinimalFactory:
    def __init__(self):
        self.calls = []

    def create(self, *, runtime, columns, **kw):
        self.calls.append((runtime, columns, kw))
        return _MinimalBackend()


def test_runtime_uses_configured_backend_factory():
    factory = _MinimalFactory()
    runtime = M.Runtime(backend_factory=factory)

    pbar = runtime.get_pbar()

    assert isinstance(pbar, _MinimalBackend)
    assert runtime.pbar is pbar
    assert factory.calls
    created_runtime, columns, kw = factory.calls[0]
    assert created_runtime is runtime
    assert columns is None
    assert kw["auto_refresh"] is True


def test_runtime_process_mode_rejects_non_convertible_backend():
    runtime = M.Runtime(backend_factory=_MinimalFactory())

    with pytest.raises(RuntimeError, match="does not support process mode promotion"):
        runtime.get_pbar(pool_mode="process")


def test_queue_progress_proxy_rich_console_uses_owner_renderable():
    progress = Progress(disable=True)
    progress.add_task("demo", total=1, completed=0)
    proxy = QueueProgressProxy.from_ref(progress)

    renderables = list(proxy.__rich_console__(Console(), None))

    assert len(renderables) == 1
    assert hasattr(renderables[0], "__rich_console__")


def test_progress_silent_uses_in_memory_console():
    progress = Progress(disable=True, silent=True)

    assert progress.console.file is not None
    assert hasattr(progress.console.file, "getvalue")
    assert progress._init_options["silent"] is True
    assert "console" not in progress._init_options


def test_queue_transport_remote_queues_send_commands():
    q = __import__("queue").SimpleQueue()
    transport = QueueTransport(q)

    transport.send("refresh", (), {})
    transport.send("write", ("hello",), {})

    assert q.get() == ("send", None, "refresh", (), {})
    assert q.get() == ("send", None, "write", ("hello",), {})


def test_queue_command_bridge_replays_commands():
    target = SimpleNamespace(calls=[])

    def write(*args, **kwargs):
        target.calls.append((args, kwargs))

    target.write = write
    q = __import__("queue").Queue()
    bridge = QueueCommandBridge(q, CommandDriver(target))
    bridge.start()
    q.put(("send", None, "write", ("hello",), {"markup": False}))
    import time
    deadline = time.time() + 1
    while not target.calls and time.time() < deadline:
        time.sleep(0.01)
    bridge.stop()

    assert target.calls == [(("hello",), {"markup": False})]


def test_queue_command_bridge_survives_failing_send():
    # A fire-and-forget send that raises must not kill the bridge thread, or
    # every later command would be silently dropped (and request-callers hang).
    import time

    target = SimpleNamespace(calls=[])
    target.boom = lambda: (_ for _ in ()).throw(ValueError("kaboom"))
    target.ok = lambda x: target.calls.append(x)

    q = __import__("queue").Queue()
    bridge = QueueCommandBridge(q, CommandDriver(target))
    bridge.start()
    try:
        q.put(("send", None, "boom", (), {}))       # raises inside the bridge
        q.put(("send", None, "ok", (7,), {}))        # must still be delivered
        deadline = time.time() + 1
        while not target.calls and time.time() < deadline:
            time.sleep(0.01)

        assert bridge._thread is not None and bridge._thread.is_alive()
        assert target.calls == [7]
    finally:
        bridge.stop()


def test_queue_transport_reuses_one_reply_channel():
    # Many requests on one transport must share a single persistent reply pipe,
    # not allocate one per call (the whole point of the hybrid).
    target = SimpleNamespace(echo=lambda v: v)
    q = __import__("queue").Queue()
    bridge = QueueCommandBridge(q, CommandDriver(target), target_id="t")
    bridge.start()
    transport = QueueTransport(q, target_id="t")  # ref=None -> routed through queue
    try:
        assert transport.request("echo", (1,), {}) == 1
        assert transport.request("echo", (2,), {}) == 2
        assert transport.request("echo", (3,), {}) == 3
        assert len(bridge._reply_ends) == 1  # one channel, reused
    finally:
        bridge.stop()


def test_queue_command_bridge_routes_multiple_targets_over_one_queue():
    first = SimpleNamespace(calls=[])
    second = SimpleNamespace(calls=[])

    first.write = lambda *args, **kwargs: first.calls.append((args, kwargs))
    second.write = lambda *args, **kwargs: second.calls.append((args, kwargs))

    q = __import__("queue").Queue()
    bridge = QueueCommandBridge(q)
    bridge.register(first, target_id="first")
    bridge.register(second, target_id="second")
    bridge.start()
    q.put(("send", "first", "write", ("one",), {"markup": False}))
    q.put(("send", "second", "write", ("two",), {"markup": True}))

    import time
    deadline = time.time() + 1
    while (not first.calls or not second.calls) and time.time() < deadline:
        time.sleep(0.01)
    bridge.stop()

    assert first.calls == [(("one",), {"markup": False})]
    assert second.calls == [(("two",), {"markup": True})]


def test_command_proxy_owner_only_and_worker_only_flags():
    class Target:
        def __init__(self):
            self.calls = []

        def owner(self, value):
            self.calls.append(("owner", value))

        def worker(self, value):
            self.calls.append(("worker", value))

    class Proxy(TransportCommandProxy):
        owner = proxymethod(Target.owner, expect_reply=False, owner_only=True)
        worker = proxymethod(Target.worker, expect_reply=False, worker_only=True)

        def __init__(self, transport, *, is_owner):
            super().__init__(transport)
            self._is_owner = is_owner

        def _proxy_is_owner(self):
            return self._is_owner

    target = Target()
    owner_proxy = Proxy(LocalTransport(CommandDriver(target)), is_owner=True)
    worker_proxy = Proxy(LocalTransport(CommandDriver(target)), is_owner=False)

    owner_proxy.owner(1)
    owner_proxy.worker(2)
    worker_proxy.owner(3)
    worker_proxy.worker(4)

    assert target.calls == [("owner", 1), ("worker", 4)]


def test_queue_progress_proxy_refuses_non_owner_render():
    q = __import__("queue").SimpleQueue()
    proxy = QueueProgressProxy(QueueTransport(q))

    with pytest.raises(RuntimeError, match="owner process"):
        list(proxy.__rich_console__(Console(), None))


def test_command_proxy_mixin_from_ref_requires_subclass_override():
    class Proxy(CommandProxyMixin[object]):
        pass

    with pytest.raises(NotImplementedError, match="must be implemented"):
        Proxy.from_ref(object())


def test_transport_command_proxy_create_command_bridge_requires_owner_ref():
    proxy = QueueProgressProxy(QueueTransport(__import__("queue").SimpleQueue()))

    with pytest.raises(RuntimeError, match="owner process"):
        proxy.create_command_bridge()


def test_transport_command_proxy_from_ref_uses_shared_command_bridge():
    runtime = M.Runtime()
    progress = Progress(disable=True)
    bridge = runtime._ensure_command_bridge()

    proxy = QueueProgressProxy.from_ref(progress, command_bridge=bridge)

    assert runtime.command_bridge is not None
    assert runtime.command_bridge.queue is proxy._transport.queue
    assert proxy._transport.target_id == id(progress)
    assert id(progress) in runtime.command_bridge.drivers


def test_transport_command_proxy_dispatches_send_and_request():
    class Target:
        def __init__(self):
            self.calls = []

        def record(self, value):
            self.calls.append(("record", value))

        def echo(self, value):
            self.calls.append(("echo", value))
            return value

    class Proxy(TransportCommandProxy):
        record = proxymethod(Target.record, expect_reply=False)
        echo = proxymethod(Target.echo)

    target = Target()
    proxy = Proxy(LocalTransport(CommandDriver(target)))

    assert proxy.record(7) is None
    assert proxy.echo(9) == 9
    assert target.calls == [("record", 7), ("echo", 9)]


def test_queue_transport_request_fails_fast_when_bridge_is_closed():
    q = __import__("queue").SimpleQueue()
    bridge = QueueCommandBridge(q)
    transport = QueueTransport(q, closed=bridge.closed)
    bridge.closed.set()

    with pytest.raises(CommandTransportClosed, match="closed"):
        transport.request("echo", (1,), {})


def test_queue_transport_send_fails_fast_when_bridge_is_closed():
    q = __import__("queue").SimpleQueue()
    bridge = QueueCommandBridge(q)
    transport = QueueTransport(q, closed=bridge.closed)
    bridge.closed.set()

    with pytest.raises(CommandTransportClosed, match="closed"):
        transport.send("write", ("hello",), {})


def test_bar_close_ignores_closed_command_transport():
    runtime = M.Runtime()
    bar = M.mqdm(range(1), runtime=runtime)
    q = __import__("queue").SimpleQueue()
    closed = __import__("threading").Event()
    closed.set()
    runtime.pbar = QueueProgressProxy(QueueTransport(q, target_id=0, closed=closed))

    bar.close()

    assert hash(bar) not in runtime.instances


def test_exposed_methods_for_uses_proxy_wrapped_methods():
    class Target:
        def send_only(self):
            return None

        def ask(self):
            return 1

    class Proxy(TransportCommandProxy):
        send_only = proxymethod(Target.send_only, expect_reply=False)
        ask = proxymethod(Target.ask)

    assert exposed_methods_for(Proxy) == ("send_only", "ask")
