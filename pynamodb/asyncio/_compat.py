"""
Async halves of operations that differ between the sync and async APIs.

See pynamodb/_compat.py for the sync halves; keep public names in step. This is
the only module under pynamodb/asyncio/ allowed to import asyncio.
"""
import asyncio
import time
from typing import Any


class _AsyncTime:
    """Default clock for RateLimiter: real time, non-blocking sleep."""

    time = staticmethod(time.time)

    @staticmethod
    async def sleep(seconds: float) -> None:
        await asyncio.sleep(seconds)


TIME_MODULE: Any = _AsyncTime()


async def sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


from aiobotocore.config import AioConfig  # noqa: E402

from pynamodb.constants import SERVICE_NAME  # noqa: E402


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
    return getattr(connection, '_client_loop', None) is loop


async def open_client(connection: Any, config: Any) -> Any:
    client = await connection.session.create_client(
        SERVICE_NAME, connection.region, endpoint_url=connection.host, config=AioConfig().merge(config),
    ).__aenter__()
    client.meta.events.register_first('before-send.*.*', connection._before_send)
    connection._client_loop = asyncio.get_running_loop()
    return client


async def _release(connection: Any) -> None:
    client = connection._client
    loop = getattr(connection, '_client_loop', None)
    connection._client_loop = None
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if client is not None and running is not None and running is loop:
        await client.__aexit__(None, None, None)
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
