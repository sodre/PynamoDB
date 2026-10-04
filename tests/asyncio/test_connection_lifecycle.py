import asyncio

import pytest

from pynamodb.asyncio.connection import Connection


async def test_client_property_raises_until_opened():
    conn = Connection(region='us-east-1')
    with pytest.raises(RuntimeError, match='get_client'):
        conn.client
    client = await conn.get_client()
    assert conn.client is client
    await conn.close()


async def test_get_client_is_cached_and_close_resets():
    conn = Connection(region='us-east-1')
    c1 = await conn.get_client()
    assert await conn.get_client() is c1
    await conn.close()
    assert conn._client is None
    c2 = await conn.get_client()
    assert c2 is not c1
    await conn.close()


async def test_close_without_open_is_noop():
    await Connection(region='us-east-1').close()


def test_new_event_loop_gets_new_client():
    conn = Connection(region='us-east-1')
    c1 = asyncio.run(conn.get_client())
    c2 = asyncio.run(conn.get_client())
    assert c1 is not c2
    asyncio.run(conn.close())


async def test_repr_does_not_raise_before_open():
    conn = Connection(region='us-east-1')
    assert 'us-east-1' in repr(conn)
    await conn.get_client()
    assert 'dynamodb.us-east-1.amazonaws.com' in repr(conn)
    await conn.close()


async def test_table_connection_close_releases_client():
    from pynamodb.asyncio import _compat
    from pynamodb.asyncio.connection import TableConnection

    table = TableConnection('mock', region='us-east-1')
    client = await table.connection.get_client()
    await table.close()

    assert table.connection._client is None
    entries = _compat._clients.get(asyncio.get_running_loop(), {}).values()
    assert all(entry.client is not client for entry in entries)


async def test_open_connections_tracks_opened_clients():
    from pynamodb.asyncio.connection.base import _open_connections

    conn = Connection(region='us-east-1')
    assert conn not in _open_connections
    await conn.get_client()
    assert conn in _open_connections
    await conn.close()
    assert conn not in _open_connections
