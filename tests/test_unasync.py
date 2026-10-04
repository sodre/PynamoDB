import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "unasync.py"
_spec = importlib.util.spec_from_file_location("unasync", _PATH)
unasync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(unasync)  # type: ignore


def t(text):
    return unasync.transform(text, "pynamodb/asyncio/x.py")


HEADER = "# AUTO-GENERATED from pynamodb/asyncio/x.py by scripts/unasync.py - DO NOT EDIT\n"


@pytest.mark.parametrize("src, expected", [
    ("async def f():\n", "def f():\n"),
    ("    async with a as b:\n", "    with a as b:\n"),
    ("    async for x in y:\n", "    for x in y:\n"),
    ("    return await self.f()\n", "    return self.f()\n"),
    ("    async def __aenter__(self):\n", "    def __enter__(self):\n"),
    ("    async def __aexit__(self, *a):\n", "    def __exit__(self, *a):\n"),
    ("    def __aiter__(self):\n", "    def __iter__(self):\n"),
    ("    async def __anext__(self):\n", "    def __next__(self):\n"),
    ("        raise StopAsyncIteration\n", "        raise StopIteration\n"),
    ("from typing import AsyncIterator\n", "from typing import Iterator\n"),
    ("from typing import AsyncIterable\n", "from typing import Iterable\n"),
    ("from contextlib import asynccontextmanager\n", "from contextlib import contextmanager\n"),
    ("from aiobotocore.session import get_session\n", "from botocore.session import get_session\n"),
    ("P = 'aiobotocore.httpsession.AIOHTTPSession.send'\n", "P = 'botocore.httpsession.URLLib3Session.send'\n"),
    ("from aiobotocore.awsrequest import AioAWSResponse\n", "from botocore.awsrequest import AWSResponse\n"),
    ("from pynamodb.asyncio.models import Model\n", "from pynamodb.models import Model\n"),
    ("from pynamodb.asyncio import _compat\n", "from pynamodb import _compat\n"),
    ("P = 'pynamodb.asyncio.connection.Connection._make_api_call'\n",
     "P = 'pynamodb.connection.Connection._make_api_call'\n"),
    ("from tests.asyncio.test_model import X\n", "from tests.sync_generated.test_model import X\n"),
    ("class T(IsolatedAsyncioTestCase):\n", "class T(TestCase):\n"),
    ("m = AsyncMock()\n", "m = MagicMock()\n"),
    ("    page = await anext(self.page_iter)\n", "    page = next(self.page_iter)\n"),
    ("    await _compat.alist(it)\n", "    list(it)\n"),
    ("    return (await cls.describe_table()).get(X)\n", "    return cls.describe_table().get(X)\n"),
])
def test_rules(src, expected):
    assert t(src) == HEADER + expected


@pytest.mark.parametrize("src", [
    "my_async_def = 1\n",
    "awaited = 2\n",
    "x = MyAsyncMockery()\n",
    "from pynamodb.asyncioextra import y\n",
])
def test_whole_token_only(src):
    assert t(src) == HEADER + src


def test_comments_and_blank_lines_preserved():
    src = "# leading comment\n\nasync def f():  # trailing\n    # inner\n    await g()\n"
    assert t(src) == HEADER + "# leading comment\n\ndef f():  # trailing\n    # inner\n    g()\n"


def test_pytestmark_line_removed():
    src = "import pytest\npytestmark = pytest.mark.asyncio\nx = 1\n"
    assert t(src) == HEADER + "import pytest\nx = 1\n"


@pytest.mark.parametrize("construct", ["asyncio.gather(", "asyncio.create_task(", "asyncio.wait_for("])
def test_forbidden_constructs_abort(construct):
    with pytest.raises(unasync.UnasyncError, match=r"pynamodb/asyncio/x.py:2: .*" + construct.replace("(", r"\(")):
        t("x = 1\ny = " + construct + "a)\n")


def test_import_asyncio_forbidden_in_library_source():
    with pytest.raises(unasync.UnasyncError, match=r"x.py:1: .*import asyncio"):
        t("import asyncio\n")


def test_import_asyncio_allowed_in_tests():
    out = unasync.transform("import asyncio\n", "tests/asyncio/test_x.py")
    assert out.endswith("import asyncio\n")


def test_generate_and_check(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("async def f():\n    await g()\n")
    files = [("src/a.py", "out/a.py")]

    assert unasync.generate(tmp_path, files, check=True) == ["out/a.py"]  # missing -> stale
    assert unasync.generate(tmp_path, files, check=False) == ["out/a.py"]  # written
    assert (tmp_path / "out" / "a.py").read_text().endswith("def f():\n    g()\n")
    assert unasync.generate(tmp_path, files, check=True) == []  # up to date

    (tmp_path / "out" / "a.py").write_text("tampered\n")
    assert unasync.generate(tmp_path, files, check=True) == ["out/a.py"]
