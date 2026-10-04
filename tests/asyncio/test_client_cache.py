import asyncio
import gc
import weakref
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
    async def use_and_close():
        client = await conn.get_client()
        await conn.close()
        return client

    assert asyncio.run(use_and_close()) is not asyncio.run(use_and_close())


async def test_connections_context_closes_everything():
    async with pynamodb.asyncio.connections():
        a, b = Connection(region='us-east-1'), Connection(region='eu-west-1')
        await a.get_client()
        await b.get_client()
    assert a._client is None and b._client is None
    assert not _compat._clients.get(asyncio.get_running_loop())


def test_finished_loop_is_dropped_from_cache_without_close():
    conn = Connection(region='us-east-1')
    loops = []

    async def use():
        loops.append(weakref.ref(asyncio.get_running_loop()))
        await conn.get_client()

    asyncio.run(use())
    gc.collect()
    assert loops[0]() is None
    assert len(_compat._clients) == 0


async def test_concurrent_first_use_shares_one_client_and_closes_extras():
    from aiobotocore.session import ClientCreatorContext

    created = []
    exited = []
    orig_enter = ClientCreatorContext.__aenter__

    async def slow_enter(self):
        await asyncio.sleep(0)
        client = await orig_enter(self)
        created.append(client)
        cls = type(client)
        if not getattr(cls, '_counting', False):
            orig_exit = cls.__aexit__

            async def counting_exit(self_, *args):
                exited.append(self_)
                return await orig_exit(self_, *args)

            cls.__aexit__ = counting_exit
            cls._counting = True
            cls._orig_exit = orig_exit
        return client

    a, b, c = (Connection(region='us-east-1') for _ in range(3))
    try:
        with patch.object(ClientCreatorContext, '__aenter__', slow_enter):
            got = await asyncio.gather(a.get_client(), a.get_client(), b.get_client(), c.get_client())
        shared = got[0]
        assert all(g is shared for g in got)
        assert len(created) > 1  # extras really were created concurrently
        # every extra client was closed right away; the shared one is still open
        assert sorted(map(id, exited)) == sorted(id(x) for x in created if x is not shared)
        for conn in (a, b):
            await conn.close()
        assert shared not in exited
        await c.close()
        assert exited.count(shared) == 1
        assert not _compat._clients.get(asyncio.get_running_loop())
    finally:
        for conn in (a, b, c):
            await conn.close()
        cls = type(created[0]) if created else None
        if cls is not None and getattr(cls, '_counting', False):
            cls.__aexit__ = cls._orig_exit
            del cls._counting, cls._orig_exit
