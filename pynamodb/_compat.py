"""
Sync halves of operations that differ between the sync and async APIs.

pynamodb/asyncio/_compat.py holds the async halves under the same names. The
async source (pynamodb/asyncio/) calls these through ``_compat``, and
scripts/unasync.py rewrites that import, so the generated sync modules use
this file. Keep the two files' public names in step.
"""
import time
from typing import Any

# Default clock for pynamodb.pagination.RateLimiter.
TIME_MODULE: Any = time


def sleep(seconds: float) -> None:
    time.sleep(seconds)


from pynamodb.constants import SERVICE_NAME  # noqa: E402


def client_usable(connection: Any) -> bool:
    # botocore caches empty credentials (see Connection._get_client); such a
    # client must be replaced.
    client = connection._client
    return bool(client) and not (client._request_signer and not client._request_signer._credentials)


def open_client(connection: Any, config: Any) -> Any:
    client = connection.session.create_client(SERVICE_NAME, connection.region, endpoint_url=connection.host, config=config)
    client.meta.events.register_first('before-send.*.*', connection._before_send)
    return client


def replace_client(connection: Any) -> None:
    # Other threads may still be mid-request on the old client; just drop it.
    pass


def close_client(connection: Any) -> None:
    close = getattr(connection._client, 'close', None)  # absent on old botocore
    if close is not None:
        close()


def client_property(connection: Any) -> Any:
    return connection._get_client()


def connection_repr(connection: Any) -> str:
    return "Connection<{}>".format(connection.client.meta.endpoint_url)
