import asyncio
from unittest.mock import patch

import pytest

import pynamodb.asyncio
from pynamodb.asyncio import _compat
from pynamodb.asyncio.connection import Connection


async def test_same_settings_share_one_client():
    a, b = Connection(region='us-east-1'), Connection(region='us-east-1')
    assert await a.get_client() is await b.get_client()
    await a.close()
    await b.close()


async def test_different_extra_headers_do_not_share():
    a = Connection(region='us-east-1', extra_headers={'x': '1'})
    b = Connection(region='us-east-1', extra_headers={'x': '2'})
    assert await a.get_client() is not await b.get_client()
    await a.close()
    await b.close()


async def test_closing_one_holder_keeps_client_open_for_others():
    a, b = Connection(region='us-east-1'), Connection(region='us-east-1')
    client = await a.get_client()
    await b.get_client()
    with patch.object(type(client), '__aexit__', wraps=client.__aexit__) as aexit:
        await a.close()
        aexit.assert_not_called()
        assert await b.get_client() is client
        await b.close()
        aexit.assert_called_once()


async def test_poisoned_shared_client_is_replaced():
    a, b = Connection(region='us-east-1'), Connection(region='us-east-1')
    old = await a.get_client()
    await b.get_client()
    old._request_signer._credentials = None  # simulate empty cached credentials
    new = await a.get_client()
    assert new is not old
    assert await b.get_client() is new  # b notices too and moves over
    await a.close()
    await b.close()


def test_separate_event_loops_get_separate_clients():
    conn = Connection(region='us-east-1')
    c1 = asyncio.run(conn.get_client())
    c2 = asyncio.run(conn.get_client())
    assert c1 is not c2


async def test_connections_context_closes_everything():
    async with pynamodb.asyncio.connections():
        a, b = Connection(region='us-east-1'), Connection(region='eu-west-1')
        await a.get_client()
        await b.get_client()
    assert a._client is None and b._client is None
    assert not _compat._clients.get(asyncio.get_running_loop())
