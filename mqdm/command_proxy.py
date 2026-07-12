from __future__ import annotations

from functools import wraps
import multiprocessing as mp
import os
from queue import Empty
import threading
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable


TRef = TypeVar("TRef")
TProxy = TypeVar("TProxy", bound="CommandProxyMixin[Any]")
TTransportProxy = TypeVar("TTransportProxy", bound="TransportProxy[Any]")
_REQUEST_POLL_INTERVAL = 0.1


class CommandTransportClosed(RuntimeError):
    """Raised when a proxy transport can no longer reach a live owner dispatch."""


@runtime_checkable
class CommandTransport(Protocol[TRef]):
    """Transport for forwarding method-like commands to a target."""

    target: TRef | None

    def _is_owner(self) -> bool | None: ...
    def send(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None: ...
    def request(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any: ...


class CommandHandler(Generic[TRef]):
    """Replay transport commands onto a concrete target object."""

    def __init__(self, target: TRef) -> None:
        self.target = target

    def invoke(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        return getattr(self.target, method)(*args, **kwargs)


class LocalTransport(Generic[TRef]):
    """In-process transport used for tests and synchronous replay."""

    def __init__(self, handler: CommandHandler[TRef]) -> None:
        self.handler = handler
        self.target = handler.target

    def _is_owner(self) -> bool:
        return True

    def send(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self.handler.invoke(method, args, kwargs)

    def request(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        return self.handler.invoke(method, args, kwargs)


class QueueTransport(Generic[TRef]):
    """Command transport backed by a queue, with direct local fast-path."""

    def __init__(
        self,
        queue: Any,
        *,
        target: TRef | None = None,
        target_id: Any = None,
        owner_pid: int | None = None,
        closed: Any | None = None,
    ) -> None:
        self.queue = queue
        self.target = target
        self.target_id = target_id
        self.owner_pid = os.getpid() if owner_pid is None else owner_pid
        self.closed = mp.Event() if closed is None else closed
        # Persistent per-thread reply channel, created lazily on first request
        # (worker side only). Kept out of pickled state — it is process/thread
        # local, like multiprocessing.managers' thread-local connection.
        self._reply_tls: Any = None

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state['target'] = None
        state['_reply_tls'] = None
        return state

    # def __setstate__(self, state: dict[str, Any]) -> None:
    #     self.__dict__.update(state)

    def _is_owner(self) -> bool:
        return self.target is not None and os.getpid() == self.owner_pid

    def _ensure_open(self) -> None:
        if self.closed.is_set():
            raise CommandTransportClosed("Command transport is closed.")

    def send(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        if self._is_owner():
            getattr(self.target, method)(*args, **kwargs)
            return
        try:
            self._ensure_open()
            self.queue.put(("send", self.target_id, method, args, kwargs))
        except (BrokenPipeError, EOFError, OSError, ValueError) as exc:
            raise CommandTransportClosed("Command transport is closed.") from exc

    def _reply_channel(self) -> tuple[Any, Any]:
        """Return this thread's persistent ``(reply_id, recv_end)`` channel.

        Like ``multiprocessing.managers``, which keeps one connection per thread
        rather than a fresh one per call, we create the reply pipe once per
        thread and reuse it. The paired send end is handed to the dispatch once
        (``open_reply``); every later request just carries ``reply_id``, so no
        file descriptor is transferred per call.
        """
        tls = self._reply_tls
        if tls is None:
            tls = self._reply_tls = threading.local()
        chan = getattr(tls, "chan", None)
        if chan is None:
            recv_end, send_end = mp.Pipe(duplex=False)
            reply_id = (os.getpid(), threading.get_ident(), id(self))
            self.queue.put(("open_reply", reply_id, send_end))
            # Keep send_end referenced: the queue feeder pickles it
            # asynchronously, and the dispatch writes replies to its transferred
            # copy — we just must not GC/close ours out from under the feeder.
            tls.chan = chan = (reply_id, recv_end, send_end)
        return chan[0], chan[1]

    def request(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        if self._is_owner():
            return getattr(self.target, method)(*args, **kwargs)
        self._ensure_open()  # check before touching the reply channel
        reply_id, recv_end = self._reply_channel()
        try:
            self.queue.put(("request", self.target_id, method, args, kwargs, reply_id))
            while True:
                if recv_end.poll(_REQUEST_POLL_INTERVAL):
                    ok, payload = recv_end.recv()
                    if ok:
                        return payload
                    raise payload
                self._ensure_open()
        except (BrokenPipeError, EOFError, OSError, ValueError) as exc:
            raise CommandTransportClosed("Command transport is closed.") from exc


class QueueCommandDispatch(Generic[TRef]):
    """Drain queued commands and replay them onto registered local targets."""

    def __init__(self, queue: Any | None = None, handler: CommandHandler[TRef] | None = None, *, target_id: Any = None, closed: Any | None = None) -> None:
        self.queue = mp.Queue() if queue is None else queue
        self.closed = mp.Event() if closed is None else closed
        self.handlers: dict[Any, CommandHandler[Any]] = {}
        if handler is not None:
            # An explicit single handler keeps whatever key it was given (``None``
            # is the conventional "default target"); only register() auto-assigns.
            self.handlers[target_id] = handler
        # Persistent reply ends, one per requesting worker-thread, keyed by the
        # reply_id sent in an ``open_reply`` message and reused for every reply.
        self._reply_ends: dict[Any, Any] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def register(self, target: TRef | CommandHandler[TRef], *, target_id: Any = None) -> Any:
        handler = target if isinstance(target, CommandHandler) else CommandHandler(target)
        if target_id is None:
            # id() of the live target is unique and stable for its lifetime, and
            # travels to workers as a plain int — no shared counter to race on.
            target_id = id(handler.target)
        self.handlers[target_id] = handler
        return target_id

    def unregister(self, target_id: Any) -> None:
        self.handlers.pop(target_id, None)

    def _dispatch(self, target_id: Any, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        try:
            handler = self.handlers[target_id]
        except KeyError as exc:
            raise KeyError(f"No command dispatch target registered for {target_id!r}.") from exc
        return handler.invoke(method, args, kwargs)

    def start(self) -> None:
        if self._thread is not None:
            return
        self.closed.clear()
        thread = threading.Thread(target=self._run, name="mqdm-command-dispatch", daemon=True)
        thread.start()
        self._thread = thread

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self.queue.get(timeout=0.1)
            except Empty:
                continue
            if item is None:
                break
            kind = item[0]
            if kind == "send":
                _, target_id, method, args, kwargs = item
                try:
                    self._dispatch(target_id, method, args, kwargs)
                except Exception:
                    # A fire-and-forget send that fails (e.g. a late update for
                    # an already-unregistered target, or the target method
                    # raising) must not kill the dispatch thread — that would
                    # silently drop every later command and hang any worker
                    # waiting on a request. Best-effort: drop it and continue.
                    pass
                continue
            if kind == "open_reply":
                _, reply_id, reply = item
                self._reply_ends[reply_id] = reply
                continue
            if kind == "request":
                _, target_id, method, args, kwargs, reply_id = item
                try:
                    payload = (True, self._dispatch(target_id, method, args, kwargs))
                except BaseException as exc:
                    payload = (False, exc)
                reply = self._reply_ends.get(reply_id)
                if reply is not None:
                    try:
                        reply.send(payload)
                    except (BrokenPipeError, EOFError, OSError):
                        # Worker gone — drop its now-dead persistent reply end.
                        end = self._reply_ends.pop(reply_id, None)
                        if end is not None:
                            end.close()
                continue

    def stop(self) -> None:
        if self._thread is None:
            return
        self.closed.set()
        self._stop_event.set()
        self.queue.put(None)
        self._thread.join(timeout=1.0)
        self._thread = None
        # Safe to close reply ends now that the drain thread has stopped.
        for end in self._reply_ends.values():
            try:
                end.close()
            except Exception:
                pass
        self._reply_ends.clear()


def proxymethod(func=None, *, expect_reply: bool = True, owner_only: bool = False, worker_only: bool = False):
    """Wrap a target method name as a proxy-forwarded command method."""
    if func is None:
        return lambda actual: proxymethod(
            actual,
            expect_reply=expect_reply,
            owner_only=owner_only,
            worker_only=worker_only,
        )

    name = func.__name__

    owner_restricted = owner_only or worker_only

    @wraps(func)
    def _call(self, *args, **kwargs):
        if owner_restricted:
            is_owner = self._proxy_is_owner()
            if owner_only and is_owner is False:
                return None
            if worker_only and is_owner is True:
                return None
        if expect_reply:
            return self._proxy_request(name, args, kwargs)
        self._proxy_send(name, args, kwargs)

    _call._is_exposed_ = True
    return _call


def exposed_methods_for(cls: type) -> tuple[str, ...]:
    """Return proxy-exposed method names for a class."""
    return tuple(
        name for name, value in cls.__dict__.items()
        if getattr(value, "_is_exposed_", False)
    )


class CommandProxyMixin(Generic[TRef]):
    """Base mixin for proxies that forward method calls as commands."""

    @classmethod
    def from_target(cls: type[TProxy], target: TRef, *, command_dispatch=None) -> TProxy:
        raise NotImplementedError(f"{cls.__name__}.from_target() must be implemented")

    @property
    def target(self) -> TRef | None:
        return None

    def _proxy_is_owner(self) -> bool | None:
        return None

    def _proxy_send(
        self,
        method: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        raise NotImplementedError

    def _proxy_request(
        self,
        method: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        raise NotImplementedError


class TransportProxy(CommandProxyMixin[TRef], Generic[TRef]):
    """Generic proxy backed by a CommandTransport."""

    def __init__(self, transport: CommandTransport[TRef]) -> None:
        self._transport = transport

    @classmethod
    def from_target(cls: type[TTransportProxy], target: TRef, *, command_dispatch=None) -> TTransportProxy:
        if command_dispatch is not None:
            target_id = command_dispatch.register(target)
            return cls(QueueTransport(
                command_dispatch.queue,
                target=target,
                target_id=target_id,
                closed=command_dispatch.closed,
            ))
        # No dispatch: owner-local only. Use a direct transport rather than an
        # orphan queue that no dispatch drains (which would silently drop commands
        # if the proxy were ever sent to a worker).
        return cls(LocalTransport(CommandHandler(target)))

    @property
    def target(self) -> TRef | None:
        return self._transport.target

    def _proxy_is_owner(self) -> bool | None:
        return self._transport._is_owner()

    def _proxy_send(
        self,
        method: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        self._transport.send(method, args, kwargs)

    def _proxy_request(
        self,
        method: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        return self._transport.request(method, args, kwargs)

    def create_command_dispatch(self) -> QueueCommandDispatch[TRef]:
        transport = self._transport
        if not isinstance(transport, QueueTransport):
            raise TypeError(
                f"{type(self).__name__} cannot create a command dispatch from "
                f"{type(transport).__name__}."
            )
        target = transport.target
        if target is None:
            raise RuntimeError(
                f"{type(self).__name__} can only create a command dispatch in the owner process."
            )
        return QueueCommandDispatch(
            transport.queue,
            CommandHandler(target),
            target_id=transport.target_id,
            closed=transport.closed,
        )
