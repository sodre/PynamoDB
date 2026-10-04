import subprocess
import sys

import pytest


def _run(code):
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)


def test_sync_import_does_not_import_aiobotocore():
    r = _run(
        "import sys, pynamodb, pynamodb.models, pynamodb.connection;"
        "assert 'aiobotocore' not in sys.modules, sorted(m for m in sys.modules if 'aio' in m);"
        "assert 'pynamodb.asyncio' not in sys.modules"
    )
    assert r.returncode == 0, r.stderr


def test_asyncio_import_error_names_extra():
    # Simulate a missing aiobotocore by blocking the import.
    r = _run(
        "import sys; sys.modules['aiobotocore'] = None\n"
        "try:\n"
        "    import pynamodb.asyncio\n"
        "except ImportError as e:\n"
        "    assert 'pynamodb[asyncio]' in str(e), str(e)\n"
        "    assert '3.10' in str(e), str(e)\n"
        "else:\n"
        "    raise SystemExit('expected ImportError')\n"
    )
    assert r.returncode == 0, r.stderr + r.stdout


def test_sync_compat_sleep(monkeypatch):
    from pynamodb import _compat
    import time
    calls = []
    monkeypatch.setattr(time, "sleep", calls.append)
    _compat.sleep(2)
    assert calls == [2]
    assert _compat.TIME_MODULE is time


@pytest.mark.skipif(sys.version_info < (3, 10), reason="async requires Python 3.10+")
def test_async_compat_time_module():
    import asyncio
    pytest.importorskip("aiobotocore")
    from pynamodb.asyncio import _compat
    assert isinstance(_compat.TIME_MODULE.time(), float)
    asyncio.run(_compat.TIME_MODULE.sleep(0))
    asyncio.run(_compat.sleep(0))


def test_sync_connection_close():
    from pynamodb.connection import Connection
    conn = Connection(region='us-east-1')
    client = conn.client
    assert conn.get_client() is client
    conn.close()
    assert conn._client is None
    assert conn.client is not client


def test_sync_connections_context_closes_clients():
    import pynamodb
    from pynamodb.connection import Connection
    with pynamodb.connections():
        conn = Connection(region='us-east-1')
        conn.get_client()
    assert conn._client is None


def test_sync_connections_does_not_import_asyncio_package():
    import subprocess, sys
    r = subprocess.run([sys.executable, "-c",
        "import sys, pynamodb\nwith pynamodb.connections(): pass\nassert 'aiobotocore' not in sys.modules"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_sync_model_close():
    from pynamodb.models import Model
    from pynamodb.attributes import UnicodeAttribute

    class Thing(Model):
        class Meta:
            table_name = 'things'
            region = 'us-east-1'
        id = UnicodeAttribute(hash_key=True)

    Thing._get_connection().connection.get_client()
    Thing.close()
    assert Thing._connection is None


def test_sync_modules_keep_time_for_existing_patches():
    # Existing users patch `pynamodb.models.time.sleep` / `pynamodb.pagination.time`;
    # the modules must keep a `time` attribute and the patch must still take effect.
    from unittest import mock
    import pynamodb.models
    import pynamodb.pagination
    from pynamodb import _compat
    import time
    assert pynamodb.models.time is time
    assert pynamodb.pagination.time is time
    with mock.patch('pynamodb.models.time.sleep') as sleep:
        _compat.sleep(2)
    sleep.assert_called_once_with(2)
