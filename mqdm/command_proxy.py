from __future__ import annotations

from functools import wraps
import multiprocessing as mp
import os
from queue import Empty
import threading
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable


TRef = TypeVar("TRef")
TProxy = TypeVar("TProxy", bound="CommandProxyMixin[Any]")
TTransportProxy = TypeVar("TTransportProxy", bound="TransportCommandProxy[Any]")


@runtime_checkable
class CommandTransport(Protocol[TRef]):
    """Transport for forwarding method-like commands to a target."""

    ref: TRef | None

    def _is_owner(self) -> bool | None: ...
    def send(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None: ...
    def request(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any: ...


class CommandDriver(Generic[TRef]):
    """Replay transport commands onto a concrete target object."""

    def __init__(self, target: TRef) -> None:
        self.target = target

    def dispatch(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        return getattr(self.target, method)(*args, **kwargs)


class LocalTransport(Generic[TRef]):
    """In-process transport used for tests and synchronous replay."""

    def __init__(self, driver: CommandDriver[TRef]) -> None:
        self.driver = driver
        self.ref = driver.target

    def _is_owner(self) -> bool:
        return True

    def send(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self.driver.dispatch(method, args, kwargs)

    def request(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        return self.driver.dispatch(method, args, kwargs)


class QueueTransport(Generic[TRef]):
    """Command transport backed by a queue, with direct local fast-path."""

    def __init__(
        self,
        queue: Any,
        *,
        ref: TRef | None = None,
        owner_pid: int | None = None,
    ) -> None:
        self.queue = queue
        self.ref = ref
        self.owner_pid = os.getpid() if owner_pid is None else owner_pid

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state['ref'] = None
        return state

    # def __setstate__(self, state: dict[str, Any]) -> None:
    #     self.__dict__.update(state)

    def _is_owner(self) -> bool:
        return self.ref is not None and os.getpid() == self.owner_pid

    def send(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        if self._is_owner():
            getattr(self.ref, method)(*args, **kwargs)
            return
        self.queue.put(("send", method, args, kwargs))

    def request(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        if self._is_owner():
            return getattr(self.ref, method)(*args, **kwargs)
        recv_end, send_end = mp.Pipe(duplex=False)
        try:
            self.queue.put(("request", method, args, kwargs, send_end))
            ok, payload = recv_end.recv()
            if ok:
                return payload
            raise payload
        finally:
            recv_end.close()
            send_end.close()


class QueueCommandBridge(Generic[TRef]):
    """Drain queued commands and replay them onto a local target in a thread."""

    def __init__(self, queue: Any, driver: CommandDriver[TRef]) -> None:
        self.queue = queue
        self.driver = driver
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        thread = threading.Thread(target=self._run, name="mqdm-command-bridge", daemon=True)
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
            if len(item) == 3:
                method, args, kwargs = item
                self.driver.dispatch(method, args, kwargs)
                continue
            kind = item[0]
            if kind == "send":
                _, method, args, kwargs = item
                self.driver.dispatch(method, args, kwargs)
                continue
            if kind == "request":
                _, method, args, kwargs, reply = item
                try:
                    reply.send((True, self.driver.dispatch(method, args, kwargs)))
                except BaseException as exc:
                    reply.send((False, exc))
                finally:
                    reply.close()
                continue

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        self.queue.put(None)
        self._thread.join(timeout=1.0)
        self._thread = None


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
    def from_ref(cls: type[TProxy], ref: TRef, *, runtime=None) -> TProxy:
        raise NotImplementedError(f"{cls.__name__}.from_ref() must be implemented")

    @property
    def ref(self) -> TRef | None:
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


class TransportCommandProxy(CommandProxyMixin[TRef], Generic[TRef]):
    """Generic proxy backed by a CommandTransport."""

    def __init__(self, transport: CommandTransport[TRef]) -> None:
        self._transport = transport

    @classmethod
    def from_ref(cls: type[TTransportProxy], ref: TRef, *, runtime=None) -> TTransportProxy:
        return cls(QueueTransport(mp.Queue(), ref=ref))

    @property
    def ref(self) -> TRef | None:
        return self._transport.ref

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
