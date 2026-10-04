"""
Async halves of operations that differ between the sync and async APIs.

See pynamodb/_compat.py for the sync halves; keep public names in step. This is
the only module under pynamodb/asyncio/ allowed to import asyncio.
"""
import asyncio
import time
import weakref
from typing import Any, Dict, Hashable

from aiobotocore.config import AioConfig

from pynamodb.constants import SERVICE_NAME


class _AsyncTime:
    """Default clock for RateLimiter: real time, non-blocking sleep."""

    time = staticmethod(time.time)

    @staticmethod
    async def sleep(seconds: float) -> None:
        await asyncio.sleep(seconds)


TIME_MODULE: Any = _AsyncTime()


async def sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _has_credentials(client: Any) -> bool:
    signer = client._request_signer
    return not (signer and not signer._credentials)


def client_usable(connection: Any) -> bool:
    client = connection._client
    if not client or not _has_credentials(client):
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    # aiobotocore clients only work on the loop that created them.
    return _held_loop(connection) is loop


class _Entry:
    __slots__ = ('client', 'refs')

    def __init__(self, client: Any) -> None:
        self.client = client
        self.refs = 0


# event loop -> {Connection._client_key() -> shared client}. Weak on the loop,
# so entries for finished loops go away with the loop.
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Dict[Hashable, _Entry]]" = weakref.WeakKeyDictionary()


def _held_loop(connection: Any) -> Any:
    ref = getattr(connection, '_client_loop', None)
    return ref() if ref is not None else None


def _held_entry(connection: Any, loop: Any) -> Any:
    """The usable entry this connection already holds on `loop`, if any."""
    entry = getattr(connection, '_client_entry', None)
    if entry is not None and _held_loop(connection) is loop and _has_credentials(entry.client):
        return entry
    return None


def _make_header_hook(headers: Any) -> Any:
    # Closes over a copy of the headers, not the connection: the client lives in
    # a shared cache and must not keep a connection (and so its loop) alive.
    headers = dict(headers) if headers else None

    def _before_send(request: Any, **_: Any) -> None:
        if headers:
            request.headers.update(headers)

    return _before_send


async def open_client(connection: Any, config: Any) -> Any:
    loop = asyncio.get_running_loop()
    held = _held_entry(connection, loop)
    if held is not None:
        return held.client
    per_loop = _clients.setdefault(loop, {})
    key = connection._client_key()
    entry = per_loop.get(key)
    if entry is None or not _has_credentials(entry.client):
        # A poisoned entry is replaced in the cache; connections still holding
        # it release it when they notice (client_usable) or close.
        client = await connection.session.create_client(
            SERVICE_NAME, connection.region, endpoint_url=connection.host, config=AioConfig().merge(config),
        ).__aenter__()
        # Another coroutine may have opened a client while we were suspended.
        held = _held_entry(connection, loop)
        existing = per_loop.get(key)
        if held is not None:
            winner = held
        elif existing is not None and _has_credentials(existing.client):
            winner = existing
        else:
            winner = None
        if winner is not None:
            await client.__aexit__(None, None, None)
            if winner is held:
                return winner.client
            entry = winner
        else:
            # extra_headers is part of the key, so every holder sends the same headers.
            client.meta.events.register_first('before-send.*.*', _make_header_hook(connection._extra_headers))
            entry = _Entry(client)
            per_loop[key] = entry
    assert entry is not None
    entry.refs += 1
    connection._client_entry = entry
    connection._client_loop = weakref.ref(loop)
    return entry.client


async def _release(connection: Any) -> None:
    entry = getattr(connection, '_client_entry', None)
    loop = _held_loop(connection)
    connection._client_entry = None
    connection._client_loop = None
    connection._client = None
    if entry is None:
        return
    entry.refs -= 1
    if entry.refs > 0:
        return
    per_loop = _clients.get(loop) if loop is not None else None
    if per_loop is not None:
        for key, value in list(per_loop.items()):
            if value is entry:
                del per_loop[key]
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is not None and running is loop:
        await entry.client.__aexit__(None, None, None)
    # Otherwise the owning loop is gone or different; its sockets cannot be
    # closed from here, so the client is dropped.


async def replace_client(connection: Any) -> None:
    await _release(connection)


async def close_client(connection: Any) -> None:
    await _release(connection)


def client_property(connection: Any) -> Any:
    if connection._client is None:
        raise RuntimeError(
            "The async client is not open yet; use `await connection.get_client()` "
            "(any awaited operation opens it)"
        )
    return connection._client


def connection_repr(connection: Any) -> str:
    # repr must never raise, so it cannot go through the (not yet open) client.
    if connection._client is not None:
        return "Connection<{}>".format(connection._client.meta.endpoint_url)
    return "Connection<{}>".format(connection.host or connection.region)
