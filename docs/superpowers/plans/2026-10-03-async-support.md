# Async Support (unasync) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `pynamodb.asyncio` (aiobotocore-based async API) whose code is the hand-edited source from which today's sync modules are generated, with no behaviour change for sync users.

**Architecture:** Async modules under `pynamodb/asyncio/` are the source of truth. `scripts/unasync.py` rewrites them line by line (keeping comments) into today's sync paths. Behaviour that cannot be rewritten textually lives in a hand-written pair of `_compat` modules (`pynamodb/_compat.py`, `pynamodb/asyncio/_compat.py`). Tests follow the same pattern (`tests/asyncio/` → `tests/sync_generated/`), while the original sync tests stay untouched as the backwards-compatibility proof.

**Tech Stack:** Python 3.7+ (sync) / 3.10+ (async), botocore, aiobotocore ≥ 2.13.0, pytest, pytest-asyncio, unittest `IsolatedAsyncioTestCase`, mypy 1.2.0, Sphinx + sphinx-tabs, uv.

**Spec:** `docs/superpowers/specs/2026-10-03-async-support-design.md`

## Global Constraints

- Work only in the worktree `/Users/sodre/ghq/github.com/pynamodb/pynamodb/.claude/worktrees/async-support`, branch `async-support`. **Never push, never open PRs, never post to GitHub** (we do not own upstream).
- Run everything through uv: `uv run pytest ...`, `uv run mypy .`, `uv run python scripts/unasync.py`. The venv already exists (Python 3.11).
- One commit per task, message explains *why*, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never amend.
- Never hand-edit a generated file. Generated files start with `# AUTO-GENERATED from <source> by scripts/unasync.py - DO NOT EDIT`.
- Original sync tests (`tests/test_*.py`, `tests/integration/*.py`) are never modified.
- All code (async source and generated) uses Python 3.7 syntax only: no `match`, no `X | Y` type unions, no parenthesised context managers, no walrus in comprehensions.
- Async source modules never `import asyncio` directly; anything needing asyncio goes through `pynamodb/asyncio/_compat.py`.
- Async source modules never use `asyncio.gather`, `asyncio.create_task`, `asyncio.wait_for` (the generator aborts).
- Core `install_requires` stays `botocore>=1.12.54` and `typing-extensions>=4; python_version<"3.11"`. Async dependency only via extra: `'asyncio': ['aiobotocore>=2.13.0; python_version>="3.10"']`.
- Sync behaviour must not change except the additive `close()` / `connections()` API.
- Unit test command: `uv run pytest tests/ -k "not ddblocal" -q -p no:cacheprovider`. Baseline before this plan: **388 passed, 21 deselected**; `uv run mypy .` clean.

## Review Focus

1. A model used across two `asyncio.run()` calls (pytest, scripts, Lambda handlers) must get a fresh client on the second loop, not "attached to a different loop" errors. → test in Task 5.
2. Two async models with identical settings but different `extra_headers` must not share a client (headers would leak). → test in Task 5.
3. Closing one async model must not break another model that shares its client. → test in Task 5.
4. A sync user on Python 3.7–3.9, or without the `asyncio` extra, must see no change: `import pynamodb` / `pynamodb.models` work and do not import aiobotocore; `import pynamodb.asyncio` raises an `ImportError` naming `pynamodb[asyncio]`. → test in Task 2.
5. An async shared client whose credentials come back empty (IAM metadata flakiness) must be replaced for the connection that notices, and other holders keep working until they notice too. → test in Task 5.

---

## File Map

| File | Kind | Task |
|---|---|---|
| `scripts/unasync.py` | new, hand | 1 (mapping extended in 3, 4, 5, 6, 7, 8, 9) |
| `tests/test_unasync.py` | new, hand | 1 |
| `setup.py`, `requirements-dev.txt` | modify | 2 |
| `pynamodb/_compat.py` | new, hand (sync halves) | 2, 4 |
| `pynamodb/asyncio/__init__.py` | new, hand (import guard, re-exports) | 2, 5 |
| `pynamodb/asyncio/_compat.py` | new, hand (async halves, client cache) | 2, 4, 5 |
| `tests/asyncio/__init__.py`, `tests/asyncio/conftest.py`, `tests/sync_generated/__init__.py` | new | 2 |
| `tests/test_asyncio_import.py` | new, hand | 2 |
| `pynamodb/asyncio/pagination.py` → `pynamodb/pagination.py` | source → generated | 3 |
| `tests/asyncio/test_pagination.py` → `tests/sync_generated/test_pagination.py` | source → generated | 3 |
| `pynamodb/asyncio/connection/{__init__,base,table}.py` → `pynamodb/connection/...` | source → generated | 4 |
| `pynamodb/asyncio/connection/_botocore_private.py` | new, hand | 4 |
| `tests/asyncio/test_{base_connection,table_connection,signals}.py` → `tests/sync_generated/...` | source → generated | 4 |
| `pynamodb/__init__.py` | modify (lazy `connections`) | 5 |
| `tests/asyncio/test_client_cache.py` | new, hand, async-only (not generated) | 5 |
| `pynamodb/asyncio/{models,indexes}.py` → `pynamodb/{models,indexes}.py` | source → generated | 6 |
| `tests/asyncio/test_model.py` → `tests/sync_generated/test_model.py` | source → generated | 7 |
| `pynamodb/asyncio/transactions.py` → `pynamodb/transactions.py`; `tests/asyncio/test_transaction.py` | source → generated | 8 |
| `tests/asyncio/integration/*` → `tests/sync_generated/integration/*`; `typing_tests/asyncio/*` | source → generated / hand | 9 |
| `.github/workflows/test.yaml`, `mypy.ini`, `.coveragerc` | modify | 10 |
| `docs/asyncio.rst`, `docs/{index,api,low_level,contributing,release_notes,conf}.rst/.py`, `docs/requirements.txt`, `CLAUDE.md`, `examples/async_model.py` | new / modify | 11 |
| 11 docs pages with Sync/Async tabs | modify | 12 |

## The conversion procedure (used by Tasks 3, 4, 6, 7, 8, 9)

Every "convert module X" step follows exactly this procedure. It is written once here and referenced by name ("**Conversion procedure**") — each task still lists its own file-specific edits in full.

1. `mkdir -p` the target directory and `git mv`-free copy: `cp pynamodb/X.py pynamodb/asyncio/X.py` (tests: `cp tests/test_X.py tests/asyncio/test_X.py`).
2. In the copy, apply the file-specific edits listed in the task (these are the only *semantic* edits).
3. Apply the mechanical edits everywhere in the copy:
   - Every `def` that (directly or transitively) calls `dispatch`, `_make_api_call`, `get_client`, `_compat.sleep`, another converted `async def`, or iterates a converted async iterator becomes `async def`, and each call to such a function gets `await `.
   - `for x in <async iterator>` → `async for x in ...`; `with <converted ctx manager>` → `async with`.
   - `__iter__`/`__next__`/`StopIteration`/`Iterator[...]` on converted iterators → `__aiter__`/`__anext__`/`StopAsyncIteration`/`AsyncIterator[...]`. Note `__aiter__` is a plain `def` (not `async def`) returning `self`.
   - Builtin `next(it)` on a converted iterator → `await anext(it)` (generator rewrites `anext(` → `next(`).
   - Imports `from pynamodb.<converted module>` → `from pynamodb.asyncio.<converted module>`. Shared modules (`attributes`, `expressions`, `constants`, `exceptions`, `settings`, `signals`, `types`, `_util`, `_schema`) keep their import paths.
   - `from typing import Iterator` → `AsyncIterator` only where the sync file needs `Iterator` for a converted iterator (so the generated file gets back exactly the original import).
4. Add the module path pair to `FILES` in `scripts/unasync.py`.
5. Run `uv run python scripts/unasync.py`.
6. Run `git diff -- <generated sync path>`. **Allowed** diff lines: the header line, and lines listed under "Expected sync diff" in the task. Anything else means step 2/3 was wrong — fix the async source and regenerate. Never edit the generated file.
7. Run the original sync tests and the generated tests (commands in each task).

Test-file mechanical edits (Tasks 3, 4, 7, 8, 9):
- `PATCH_METHOD = 'pynamodb.connection.Connection._make_api_call'` → `'pynamodb.asyncio.connection.Connection._make_api_call'`. Every other `'pynamodb.<converted module>...'` patch target likewise gains `asyncio.`.
- No asyncio markers: `pytest.ini` sets `asyncio_mode = auto` (Task 2), so `async def test_...` functions just run. Do not add `pytestmark = pytest.mark.asyncio` (module-level marks would also hit the plain `def` tests that converted files keep).
- `class X(TestCase)` → `class X(IsolatedAsyncioTestCase)` and `from unittest import TestCase` → `from unittest import IsolatedAsyncioTestCase` (keep `TestCase` import only if still used by a non-converted class — then the generated file will import `TestCase` twice, which is harmless).
- Test functions/methods that call converted APIs → `async def test_...` with `await`.
- `MagicMock()` objects that stand in for awaited things → `AsyncMock()`. `patch(...)` on an `async def` target already yields an `AsyncMock`; `return_value=` and `side_effect=` keep working.
- Imports from other test modules: `from tests.test_model import ...` stays (shared helpers); imports from converted test modules use `tests.asyncio.`.

---

### Task 1: The generator `scripts/unasync.py`

**Files:**
- Create: `scripts/unasync.py`
- Test: `tests/test_unasync.py`

**Interfaces:**
- Produces: `unasync.FILES: List[Tuple[str, str]]`; `unasync.transform(text: str, source: str) -> str`; `unasync.generate(root: Path, files, check: bool) -> List[str]` (returns stale/changed target paths); `unasync.UnasyncError`; CLI `python scripts/unasync.py [--check]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_unasync.py`:

```python
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
    ("from pynamodb.asyncio.models import Model\n", "from pynamodb.models import Model\n"),
    ("from pynamodb.asyncio import _compat\n", "from pynamodb import _compat\n"),
    ("P = 'pynamodb.asyncio.connection.Connection._make_api_call'\n",
     "P = 'pynamodb.connection.Connection._make_api_call'\n"),
    ("from tests.asyncio.test_model import X\n", "from tests.sync_generated.test_model import X\n"),
    ("class T(IsolatedAsyncioTestCase):\n", "class T(TestCase):\n"),
    ("m = AsyncMock()\n", "m = MagicMock()\n"),
    ("    page = await anext(self.page_iter)\n", "    page = next(self.page_iter)\n"),
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_unasync.py -q -p no:cacheprovider`
Expected: FAIL / error — `scripts/unasync.py` does not exist.

- [ ] **Step 3: Write the generator**

`scripts/unasync.py`:

```python
#!/usr/bin/env python3
"""Generate PynamoDB's sync modules from the async source ("unasync").

The async code under pynamodb/asyncio/ and tests/asyncio/ is the hand-edited
source of truth. This script rewrites it line by line into the sync twins, so
comments and layout survive and the generated files diff cleanly.

    python scripts/unasync.py          # regenerate every file in FILES
    python scripts/unasync.py --check  # exit 1 if any generated file is stale

Behaviour that cannot be rewritten textually belongs in the hand-written pair
pynamodb/_compat.py / pynamodb/asyncio/_compat.py, never here.
"""
import argparse
import re
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent

# (async source, generated sync target), relative to ROOT. Extended as modules
# are converted; files not listed here (e.g. async-only tests) are not generated.
FILES: List[Tuple[str, str]] = []

HEADER = "# AUTO-GENERATED from {source} by scripts/unasync.py - DO NOT EDIT\n"

# Ordered, whole-token rewrites; more specific patterns first.
RULES: List[Tuple["re.Pattern[str]", str]] = [
    (re.compile(p), r) for p, r in [
        (r"\bfrom pynamodb\.asyncio import\b", "from pynamodb import"),
        (r"\bpynamodb\.asyncio\.", "pynamodb."),
        (r"\btests\.asyncio\.", "tests.sync_generated."),
        (r"\basync def\b", "def"),
        (r"\basync with\b", "with"),
        (r"\basync for\b", "for"),
        (r"\bawait ", ""),
        (r"\b__aenter__\b", "__enter__"),
        (r"\b__aexit__\b", "__exit__"),
        (r"\b__aiter__\b", "__iter__"),
        (r"\b__anext__\b", "__next__"),
        (r"\bStopAsyncIteration\b", "StopIteration"),
        (r"\bAsyncIterator\b", "Iterator"),
        (r"\bAsyncIterable\b", "Iterable"),
        (r"\basynccontextmanager\b", "contextmanager"),
        (r"\baiobotocore\.session\b", "botocore.session"),
        (r"\bIsolatedAsyncioTestCase\b", "TestCase"),
        (r"\bAsyncMock\b", "MagicMock"),
        (r"\banext\(", "next("),
    ]
]

# Lines dropped entirely (exact match after stripping).
DROP_LINES = {"pytestmark = pytest.mark.asyncio"}

FORBIDDEN = [
    (re.compile(r"\basyncio\.gather\("), "asyncio.gather("),
    (re.compile(r"\basyncio\.create_task\("), "asyncio.create_task("),
    (re.compile(r"\basyncio\.wait_for\("), "asyncio.wait_for("),
]
# Library source must reach asyncio only through pynamodb/asyncio/_compat.py.
FORBIDDEN_IN_LIBRARY = re.compile(r"^\s*(import asyncio\b|from asyncio\b)")


class UnasyncError(Exception):
    pass


def transform(text: str, source: str) -> str:
    """Rewrite one async source file's text into its sync twin."""
    is_library = source.startswith("pynamodb/")
    out = [HEADER.format(source=source)]
    for lineno, line in enumerate(text.splitlines(keepends=True), start=1):
        for pattern, name in FORBIDDEN:
            if pattern.search(line):
                raise UnasyncError(
                    f"{source}:{lineno}: {name} cannot be rewritten to sync; "
                    f"put it behind a helper in pynamodb/asyncio/_compat.py"
                )
        if is_library and FORBIDDEN_IN_LIBRARY.search(line):
            raise UnasyncError(
                f"{source}:{lineno}: import asyncio in library source; "
                f"use pynamodb/asyncio/_compat.py instead"
            )
        if line.strip() in DROP_LINES:
            continue
        for pattern, replacement in RULES:
            line = pattern.sub(replacement, line)
        out.append(line)
    return "".join(out)


def generate(root: Path, files: Sequence[Tuple[str, str]], check: bool) -> List[str]:
    """Regenerate (or, with check=True, compare) each target. Returns changed/stale targets."""
    changed = []
    for source, target in files:
        expected = transform((root / source).read_text(), source)
        target_path = root / target
        current = target_path.read_text() if target_path.exists() else None
        if current == expected:
            continue
        changed.append(target)
        if not check:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(expected)
    return changed


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if generated files are stale")
    args = parser.parse_args(argv)
    try:
        changed = generate(ROOT, FILES, check=args.check)
    except UnasyncError as e:
        print(f"unasync: {e}", file=sys.stderr)
        return 1
    if args.check and changed:
        for target in changed:
            print(f"stale: {target}", file=sys.stderr)
        print("Generated sync code is out of date. Run: python scripts/unasync.py", file=sys.stderr)
        return 1
    for target in changed:
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_unasync.py -q -p no:cacheprovider`
Expected: all PASS. Also `uv run python scripts/unasync.py --check` → exit 0 (empty `FILES`).

- [ ] **Step 5: Commit**

```bash
git add scripts/unasync.py tests/test_unasync.py
git commit -m "Add unasync generator for deriving sync modules from async source

A line-based rewriter keeps comments and layout, so generated sync files
diff cleanly against today's hand-written ones; that diff is how each
conversion proves sync behaviour did not change. Constructs that cannot be
translated textually (gather, create_task, wait_for, direct asyncio
imports in library code) abort generation instead of producing a twin
that silently behaves differently.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Packaging, `_compat` scaffolding, async test scaffolding

**Files:**
- Modify: `setup.py` (extras_require), `requirements-dev.txt`, `pytest.ini`
- Create: `pynamodb/_compat.py`, `pynamodb/asyncio/__init__.py`, `pynamodb/asyncio/_compat.py`
- Create: `tests/asyncio/__init__.py`, `tests/asyncio/conftest.py`, `tests/sync_generated/__init__.py`
- Test: `tests/test_asyncio_import.py`

**Interfaces:**
- Produces: `pynamodb._compat.TIME_MODULE`, `pynamodb._compat.sleep(seconds) -> None`; `pynamodb.asyncio._compat.TIME_MODULE` (has `.time()` and `async .sleep()`), `async pynamodb.asyncio._compat.sleep(seconds)`. Later tasks add client functions to both.

- [ ] **Step 1: Write the failing tests**

`tests/test_asyncio_import.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_asyncio_import.py -q -p no:cacheprovider`
Expected: FAIL — `pynamodb._compat` / `pynamodb.asyncio` do not exist.

- [ ] **Step 3: Implement**

`setup.py` — change `extras_require`:

```python
    extras_require={
        'signals': ['blinker>=1.3,<2.0'],
        'asyncio': ['aiobotocore>=2.13.0; python_version>="3.10"'],
    },
```

(`aiobotocore>=2.13.0` is the floor zae-limiter runs on with the same `create_client(...).__aenter__()` / async `_make_api_call` API. Also add `'pynamodb.asyncio'` packages are picked up automatically by `find_packages`; no change needed there.)

`requirements-dev.txt` — append:

```
# async support (Python 3.10+)
pytest-asyncio; python_version>="3.10"
types-aiobotocore[dynamodb]; python_version>="3.10"
```

`pytest.ini` — add under `[pytest]` (pytest only warns "unknown config option" on Python < 3.10, where pytest-asyncio is not installed):

```ini
asyncio_mode = auto
```

Install: `uv pip install -e '.[signals,asyncio]' -r requirements-dev.txt`

`pynamodb/_compat.py`:

```python
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
```

`pynamodb/asyncio/_compat.py`:

```python
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
```

`pynamodb/asyncio/__init__.py`:

```python
"""
Async API for PynamoDB, built on aiobotocore.

Install with ``pip install pynamodb[asyncio]`` (Python 3.10+). Usage mirrors the
sync API: ``from pynamodb.asyncio.models import Model``.
"""
import sys

if sys.version_info < (3, 10):  # pragma: no cover
    raise ImportError("pynamodb.asyncio requires Python 3.10+; install pynamodb[asyncio]")
try:
    import aiobotocore  # noqa: F401
except ImportError as e:
    raise ImportError(
        "pynamodb.asyncio requires aiobotocore; install pynamodb[asyncio] (Python 3.10+)"
    ) from e
```

`tests/asyncio/__init__.py` and `tests/sync_generated/__init__.py`: empty files.

`tests/asyncio/conftest.py`:

```python
import sys

collect_ignore_glob = []
if sys.version_info < (3, 10):
    collect_ignore_glob = ["*"]
else:
    try:
        import aiobotocore  # noqa: F401
    except ImportError:
        collect_ignore_glob = ["*"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_asyncio_import.py -q -p no:cacheprovider` → PASS.
Run: `uv run pytest tests/ -k "not ddblocal" -q -p no:cacheprovider` → 388 original + new tests pass.
Run: `uv run mypy .` → clean.

- [ ] **Step 5: Commit**

```bash
git add setup.py requirements-dev.txt pynamodb/_compat.py pynamodb/asyncio tests/asyncio tests/sync_generated tests/test_asyncio_import.py
git commit -m "Add asyncio extra and the hand-written _compat pair

aiobotocore needs Python 3.10+ and pins botocore tightly, so it must be an
opt-in extra that never reaches sync users. The _compat pair is where
sync and async genuinely differ (sleep, rate-limiter clock); the async
source calls it by one name and the generator swaps the import.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Convert `pagination.py` (first real conversion)

**Files:**
- Create: `pynamodb/asyncio/pagination.py` (source)
- Generated: `pynamodb/pagination.py`
- Create: `tests/asyncio/test_pagination.py` (source); generated `tests/sync_generated/test_pagination.py`
- Modify: `scripts/unasync.py` (`FILES`)

**Interfaces:**
- Consumes: `_compat.TIME_MODULE` (Task 2).
- Produces: `pynamodb.asyncio.pagination.RateLimiter` (`async acquire()`), `PageIterator` / `ResultIterator` (async iterators; `async next()`; properties unchanged). The `_operation` passed to `PageIterator` is an `async def` (supplied by converted Model/Index in Task 6).

- [ ] **Step 1: Create the async source** with the **Conversion procedure**. File-specific edits in `pynamodb/asyncio/pagination.py`:
  - `import time` → remove; add `from pynamodb.asyncio import _compat`.
  - `RateLimiter.__init__`: `self._time_module: Any = time_module or time` → `self._time_module: Any = time_module or _compat.TIME_MODULE`.
  - `def acquire(self)` → `async def acquire(self)`; its sleep line → `await self._time_module.sleep(max(0, ...))` (expression unchanged).
  - `class PageIterator(Iterator[_T])` → `class PageIterator(AsyncIterator[_T])`; `def __iter__(self) -> Iterator[_T]` → `def __aiter__(self) -> AsyncIterator[_T]`; `def __next__` → `async def __anext__`; inside: `raise StopIteration` → `raise StopAsyncIteration`; `self._rate_limiter.acquire()` → `await self._rate_limiter.acquire()`; `page = self._operation(...)` → `page = await self._operation(...)`.
  - `def next(self)` → `async def next(self)`, body `return await self.__anext__()`.
  - `ResultIterator`: same iterator edits; `_get_next_page` → `async def`, its `next(self.page_iter)` → `await anext(self.page_iter)`; `__anext__` calls `await self._get_next_page()`; `next()` as above.
  - `typing` import: replace `Iterator` with `AsyncIterator`.
- [ ] **Step 2:** Add `("pynamodb/asyncio/pagination.py", "pynamodb/pagination.py")` to `FILES`; run `uv run python scripts/unasync.py`.
- [ ] **Step 3: Diff proof.** `git diff -- pynamodb/pagination.py`. **Expected sync diff:** the header line; `import time` → `from pynamodb import _compat`; `time_module or time` → `time_module or _compat.TIME_MODULE`. Nothing else.
- [ ] **Step 4: Original tests.** `uv run pytest tests/ -k "not ddblocal" -q -p no:cacheprovider` → same pass count as after Task 2.
- [ ] **Step 5: Convert the test.** `cp tests/test_pagination.py tests/asyncio/test_pagination.py`, apply the test-file mechanical edits. File-specific: the fake time module's `def sleep(self, amount)` → `async def sleep(self, amount)`; every `rate_limiter.acquire()` → `await rate_limiter.acquire()`; each `def test_...` → `async def test_...`. Add `("tests/asyncio/test_pagination.py", "tests/sync_generated/test_pagination.py")` to `FILES`; regenerate.
- [ ] **Step 6: Run** `uv run pytest tests/asyncio/test_pagination.py tests/sync_generated/test_pagination.py tests/test_pagination.py -v -p no:cacheprovider` → all PASS. `uv run python scripts/unasync.py --check` → exit 0. `uv run mypy .` → clean.
- [ ] **Step 7: Commit**

```bash
git add scripts/unasync.py pynamodb/asyncio/pagination.py pynamodb/pagination.py tests/asyncio/test_pagination.py tests/sync_generated/test_pagination.py
git commit -m "Make pagination async-sourced; generate the sync module

Pagination has no network code of its own, so it is the smallest real
proof of the pipeline: the generated pynamodb/pagination.py differs from
the original only in the header and in taking its default clock from
_compat, and the untouched sync tests still pass.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Convert the connection layer, add `get_client` / `close`

**Files:**
- Create (source): `pynamodb/asyncio/connection/__init__.py`, `pynamodb/asyncio/connection/base.py`, `pynamodb/asyncio/connection/table.py`
- Create (hand): `pynamodb/asyncio/connection/_botocore_private.py`
- Generated: `pynamodb/connection/__init__.py`, `pynamodb/connection/base.py`, `pynamodb/connection/table.py`
- Modify: `pynamodb/_compat.py`, `pynamodb/asyncio/_compat.py`, `scripts/unasync.py`
- Tests (source → generated): `tests/asyncio/test_base_connection.py`, `tests/asyncio/test_table_connection.py`, `tests/asyncio/test_signals.py`

**Interfaces:**
- Produces on `Connection` (both sides; async = `async def`): `get_client() -> BotocoreBaseClientPrivate`, `_get_client()`, `close() -> None`, `_client_key() -> Hashable`, `client` property (sync: lazily creates; async: raises `RuntimeError` until opened). `TableConnection.close()`.
- `_compat` functions (both sides, same names): `client_usable(connection) -> bool`, `open_client(connection, config) -> client`, `replace_client(connection) -> None`, `close_client(connection) -> None`, `client_property(connection) -> client`. Async versions are coroutines except `client_usable` and `client_property`.
- Module-level in `connection/base.py`: `_open_connections: weakref.WeakSet` (used by Task 5).

- [ ] **Step 1: Add the `_compat` client functions.**

Append to `pynamodb/_compat.py`:

```python
from pynamodb.constants import SERVICE_NAME


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
```

Append to `pynamodb/asyncio/_compat.py` (Task 5 replaces `open_client` / `release` with the shared cache; this version gives every connection its own client):

```python
from aiobotocore.config import AioConfig

from pynamodb.constants import SERVICE_NAME


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
```

- [ ] **Step 2: Write the failing async-only lifecycle tests** — `tests/asyncio/test_connection_lifecycle.py` (hand-written, **not** in `FILES`):

```python
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
```

Sync side (append to `tests/test_asyncio_import.py`, since original tests are frozen):

```python
def test_sync_connection_close():
    from pynamodb.connection import Connection
    conn = Connection(region='us-east-1')
    client = conn.client
    assert conn.get_client() is client
    conn.close()
    assert conn._client is None
    assert conn.client is not client
```

Run: `uv run pytest tests/asyncio/test_connection_lifecycle.py tests/test_asyncio_import.py -q -p no:cacheprovider` → FAIL (no `pynamodb.asyncio.connection`, no `close`).

- [ ] **Step 3: Create the async connection source** with the **Conversion procedure** for `connection/__init__.py`, `connection/base.py`, `connection/table.py`. File-specific edits:

`pynamodb/asyncio/connection/_botocore_private.py` (hand-written):

```python
"""Typing for the private aiobotocore client API PynamoDB relies on."""
from typing import Any, Dict

from aiobotocore.client import AioBaseClient


class BotocoreBaseClientPrivate(AioBaseClient):
    _endpoint: Any
    _request_signer: Any

    async def _make_api_call(self, operation_name: str, operation_kwargs: Dict) -> Any:
        raise NotImplementedError
```

(Check the sync `pynamodb/connection/_botocore_private.py` for any other attributes it declares and mirror them with the same names.)

`pynamodb/asyncio/connection/base.py`:
- Imports: `from botocore.session import get_session` → `from aiobotocore.session import get_session`; `from pynamodb.connection._botocore_private import ...` → `from pynamodb.asyncio.connection._botocore_private import ...`; add `import weakref`, `from typing import Hashable` (to the existing typing import), `from pynamodb.asyncio import _compat`.
- After the `log = ...` line add: `_open_connections: "weakref.WeakSet[Connection]" = weakref.WeakSet()`
- Keep the `session` property unchanged except its return annotation stays `botocore.session.Session` (the async session is a subclass; mypy is satisfied via `types-aiobotocore` or `ignore_missing_imports`).
- Replace the body of the `client` property and add `_get_client`, `get_client`, `_client_key`, `close`:

```python
    @property
    def client(self) -> BotocoreBaseClientPrivate:
        """
        Returns a botocore dynamodb client
        """
        return _compat.client_property(self)

    async def get_client(self) -> BotocoreBaseClientPrivate:
        """
        Returns the dynamodb client, creating it if needed
        """
        return await self._get_client()

    async def _get_client(self) -> BotocoreBaseClientPrivate:
        # botocore has a known issue where it will cache empty credentials
        # https://github.com/boto/botocore/blob/4d55c9b4142/botocore/credentials.py#L1016-L1021
        # if the client does not have credentials, we create a new client
        # otherwise the client is permanently poisoned in the case of metadata service flakiness when using IAM roles
        if not _compat.client_usable(self):
            if self._client is not None:
                await _compat.replace_client(self)
            # Check if we are using the "LEGACY" retry mode to keep previous PynamoDB
            # retry behavior, or if we are using the new retry configuration settings.
            if self._retry_configuration != "LEGACY":
                retries = self._retry_configuration
            else:
                retries = {
                    'total_max_attempts': 1 + self._max_retry_attempts_exception,
                    'mode': 'standard',
                }

            config = botocore.client.Config(
                parameter_validation=False,  # Disable unnecessary validation for performance
                connect_timeout=self._connect_timeout_seconds,
                read_timeout=self._read_timeout_seconds,
                max_pool_connections=self._max_pool_connections,
                retries=retries,
            )
            self._client = cast(BotocoreBaseClientPrivate, await _compat.open_client(self, config))
            _open_connections.add(self)
        return self._client

    def _client_key(self) -> Hashable:
        """
        Settings that must match for two connections to share a client
        """
        retries = self._retry_configuration
        return (
            self.region,
            self.host,
            self._aws_access_key_id,
            self._aws_secret_access_key,
            self._aws_session_token,
            self._connect_timeout_seconds,
            self._read_timeout_seconds,
            tuple(sorted(retries.items())) if isinstance(retries, dict) else retries,
            self._max_retry_attempts_exception,
            self._max_pool_connections,
            tuple(sorted(self._extra_headers.items())) if self._extra_headers else None,
        )

    async def close(self) -> None:
        """
        Closes the dynamodb client, if one is open
        """
        if self._client is not None:
            await _compat.close_client(self)
            self._client = None
        _open_connections.discard(self)
```

(Copy the retry/config block from the original `client` property verbatim — it is reproduced above; confirm the attribute names `_aws_access_key_id`, `_aws_secret_access_key`, `_aws_session_token`, `_extra_headers`, `_max_pool_connections` against `__init__` before relying on them.)
- `_make_api_call` → `async def`; first line of the `try` → `return await (await self.get_client())._make_api_call(operation_name, operation_kwargs)`.
- `dispatch` → `async def`; `data = await self._make_api_call(...)`.
- Every method that calls `self.dispatch(...)` → `async def` with `await self.dispatch(...)`: `create_table`, `update_time_to_live`, `delete_table`, `update_table`, `list_tables`, `describe_table`, `delete_item`, `update_item`, `put_item`, `transact_write_items`, `transact_get_items`, `batch_write_item`, `batch_get_item`, `get_item`, `scan`, `query`. Do **not** convert `get_meta_table`, `add_meta_table`, `get_identifier_map`, `get_attribute_type`, `get_item_attribute_map`, `parse_attribute`, `get_operation_kwargs`, `get_exclusive_start_key_map`, the `*_map` helpers, `_check_condition`, `_reverse_dict` (no I/O — verified: `get_meta_table` is a dict lookup).

`pynamodb/asyncio/connection/table.py`:
- `from pynamodb.connection.base import Connection, MetaTable` → `from pynamodb.asyncio.connection.base import Connection, MetaTable`.
- Each method that `return self.connection.<converted method>(...)` → `async def ...: return await self.connection.<method>(...)`: `delete_item`, `update_item`, `put_item`, `batch_write_item`, `batch_get_item`, `get_item`, `scan`, `query`, `describe_table`, `delete_table`, `update_time_to_live`, `update_table`, `create_table`. `get_meta_table`, `get_operation_kwargs` stay sync.
- Add at the end of the class:

```python
    async def close(self) -> None:
        """
        Closes the underlying connection's client
        """
        await self.connection.close()
```

`pynamodb/asyncio/connection/__init__.py`: copy; imports → `pynamodb.asyncio.connection.base` / `.table`.

- [ ] **Step 4:** Add to `FILES`:

```python
    ("pynamodb/asyncio/connection/__init__.py", "pynamodb/connection/__init__.py"),
    ("pynamodb/asyncio/connection/base.py", "pynamodb/connection/base.py"),
    ("pynamodb/asyncio/connection/table.py", "pynamodb/connection/table.py"),
```

Run `uv run python scripts/unasync.py`.

- [ ] **Step 5: Diff proof.** `git diff -- pynamodb/connection/`. **Expected sync diff:** headers; `import weakref`, `Hashable`, `from pynamodb import _compat` imports; `_open_connections` line; the `client` property body now `return _compat.client_property(self)`; new `get_client`, `_get_client` (the old property body, with `if not _compat.client_usable(self):`, the `replace_client` call, and `open_client` call replacing the inline `create_client` + `register_first` lines), `_client_key`, `close` on `Connection` and `close` on `TableConnection`; `_make_api_call` calling `self.get_client()` instead of `self.client`. Nothing else.
- [ ] **Step 6: Run the lifecycle tests and the original suite**

`uv run pytest tests/asyncio/test_connection_lifecycle.py tests/test_asyncio_import.py -q -p no:cacheprovider` → PASS.
`uv run pytest tests/ -k "not ddblocal" -q -p no:cacheprovider` → all pass (original tests unchanged).

- [ ] **Step 7: Convert the connection tests** with the test-file mechanical edits: `tests/test_base_connection.py`, `tests/test_table_connection.py`, `tests/test_signals.py` → `tests/asyncio/`. File-specific:
  - Patch targets `'pynamodb.connection.Connection.session'`, `'pynamodb.connection.base.uuid'` gain `asyncio.`.
  - Tests that read `conn.client` before any awaited call → `client = await conn.get_client()` first, then keep the assertions (generated sync: `conn.get_client()`, which exists).
  - Tests asserting how `session.create_client` was called: the async call passes `config=AioConfig().merge(config)`; assert on `call_args.kwargs['config'].connect_timeout` etc. rather than object identity. If a sync test asserts `create_client` returned value identity, the async mock must make `create_client(...)` return an object whose `__aenter__` is an `AsyncMock` returning the fake client.
  - Add `FILES` entries for the three files → `tests/sync_generated/`; regenerate.
- [ ] **Step 8: Run** `uv run pytest tests/asyncio tests/sync_generated tests/test_base_connection.py tests/test_table_connection.py tests/test_signals.py -q -p no:cacheprovider` → PASS; `uv run python scripts/unasync.py --check` → 0; `uv run mypy .` → clean.
- [ ] **Step 9: Commit**

```bash
git add -A pynamodb/_compat.py pynamodb/asyncio pynamodb/connection scripts/unasync.py tests/asyncio tests/sync_generated tests/test_asyncio_import.py
git commit -m "Make the connection layer async-sourced; add get_client and close

Every DynamoDB request funnels through Connection._make_api_call, so this
is where async starts. A property cannot await, so client creation moves
to get_client() and the client property's body comes from _compat:
lazily creating on sync (unchanged behaviour) and raising until opened on
async. close() is new on both sides because aiobotocore clients hold an
HTTP session that must be closed.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Async shared clients and `connections()`

**Files:**
- Modify: `pynamodb/asyncio/_compat.py` (cache), `pynamodb/asyncio/connection/base.py` (add `connections`), regenerate `pynamodb/connection/base.py`
- Modify: `pynamodb/__init__.py` (lazy `connections`), `pynamodb/asyncio/__init__.py` (export `connections`)
- Test: `tests/asyncio/test_client_cache.py` (hand-written, async-only, not in `FILES`); sync test appended to `tests/test_asyncio_import.py`

**Interfaces:**
- Consumes: `Connection._client_key()`, `_open_connections`, `_compat.open_client/replace_client/close_client` (Task 4).
- Produces: `pynamodb.asyncio.connections()` (async context manager), `pynamodb.connections()` (sync context manager).

- [ ] **Step 1: Write the failing tests** — `tests/asyncio/test_client_cache.py`:

```python
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
```

Append to `tests/test_asyncio_import.py`:

```python
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
```

Run: `uv run pytest tests/asyncio/test_client_cache.py tests/test_asyncio_import.py -q -p no:cacheprovider` → FAIL.

- [ ] **Step 2: Implement the cache** — in `pynamodb/asyncio/_compat.py`, replace `open_client`, `_release` with:

```python
import weakref
from typing import Dict, Hashable


class _Entry:
    __slots__ = ('client', 'refs')

    def __init__(self, client: Any) -> None:
        self.client = client
        self.refs = 0


# event loop -> {Connection._client_key() -> shared client}. Weak on the loop,
# so entries for finished loops go away with the loop.
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Dict[Hashable, _Entry]]" = weakref.WeakKeyDictionary()


async def open_client(connection: Any, config: Any) -> Any:
    loop = asyncio.get_running_loop()
    per_loop = _clients.setdefault(loop, {})
    key = connection._client_key()
    entry = per_loop.get(key)
    if entry is None or not _has_credentials(entry.client):
        # A poisoned entry is replaced in the cache; connections still holding
        # it release it when they notice (client_usable) or close.
        client = await connection.session.create_client(
            SERVICE_NAME, connection.region, endpoint_url=connection.host, config=AioConfig().merge(config),
        ).__aenter__()
        # extra_headers is part of the key, so every holder sends the same headers.
        client.meta.events.register_first('before-send.*.*', connection._before_send)
        entry = _Entry(client)
        per_loop[key] = entry
    entry.refs += 1
    connection._client_entry = entry
    connection._client_loop = loop
    return entry.client


async def _release(connection: Any) -> None:
    entry = getattr(connection, '_client_entry', None)
    loop = getattr(connection, '_client_loop', None)
    connection._client_entry = None
    connection._client_loop = None
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
```

(`replace_client` / `close_client` keep calling `_release`.)

- [ ] **Step 3: Add `connections()`** to `pynamodb/asyncio/connection/base.py` (module level, after the `Connection` class):

```python
@asynccontextmanager
async def connections() -> AsyncIterator[None]:
    """
    Closes every connection that opened a client, when the block exits
    """
    try:
        yield
    finally:
        for connection in list(_open_connections):
            await connection.close()
```

Imports: `from contextlib import asynccontextmanager`, `AsyncIterator` from typing. Regenerate; expected sync diff adds `from contextlib import contextmanager`, `Iterator` import, and the `@contextmanager def connections() -> Iterator[None]` function.

`pynamodb/asyncio/__init__.py` — append:

```python
from pynamodb.asyncio.connection.base import connections  # noqa: E402

__all__ = ['connections']
```

`pynamodb/__init__.py` — append (lazy, so `import pynamodb` stays light):

```python
def connections():
    """
    Context manager that closes every open PynamoDB connection on exit.
    See also ``pynamodb.asyncio.connections`` for the async API.
    """
    from pynamodb.connection.base import connections as _connections
    return _connections()
```

- [ ] **Step 4: Run** `uv run pytest tests/asyncio tests/sync_generated tests/test_asyncio_import.py -q -p no:cacheprovider` → PASS; full suite `uv run pytest tests/ -k "not ddblocal" -q -p no:cacheprovider` → PASS; `--check` → 0; `uv run mypy .` → clean.
- [ ] **Step 5: Commit**

```bash
git add pynamodb/__init__.py pynamodb/asyncio pynamodb/connection/base.py tests/asyncio/test_client_cache.py tests/test_asyncio_import.py
git commit -m "Share async clients per event loop and settings; add connections()

Each model class opens its own connection, so without sharing an async
app holds one aiohttp pool per model. Clients are keyed by loop (a client
only works on its own loop) and by every setting that is baked into the
client, including extra_headers, whose hook is registered on the client.
connections() gives apps one place to close everything at shutdown.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Convert `models.py` and `indexes.py`; add `Model.close()`

**Files:**
- Create (source): `pynamodb/asyncio/models.py`, `pynamodb/asyncio/indexes.py`
- Generated: `pynamodb/models.py`, `pynamodb/indexes.py`
- Modify: `scripts/unasync.py`
- Test: `tests/asyncio/test_model_close.py` (hand-written, async-only); sync check appended to `tests/test_asyncio_import.py`

**Interfaces:**
- Consumes: async `TableConnection` (Task 4), async `ResultIterator` (Task 3), `_compat.sleep` (Task 2).
- Produces: async `Model` API per spec section 3; `Model.close()` classmethod (async on async side); `BatchWrite` async context manager with `async save/delete/commit`.

- [ ] **Step 1: Write the failing tests** — `tests/asyncio/test_model_close.py`:

```python
import pytest

from pynamodb.asyncio.models import Model
from pynamodb.attributes import UnicodeAttribute


class Thing(Model):
    class Meta:
        table_name = 'things'
        region = 'us-east-1'
    id = UnicodeAttribute(hash_key=True)


async def test_model_close_releases_connection():
    await Thing._get_connection().connection.get_client()
    await Thing.close()
    assert Thing._connection is None


async def test_model_close_without_connection_is_noop():
    Thing._connection = None
    await Thing.close()
```

Append to `tests/test_asyncio_import.py`:

```python
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
```

Run → FAIL.

- [ ] **Step 2: Create the async source** with the **Conversion procedure**. File-specific edits in `pynamodb/asyncio/models.py`:
  - Imports: `pynamodb.connection.base`, `pynamodb.connection.table`, `pynamodb.indexes`, `pynamodb.pagination` → `pynamodb.asyncio.` equivalents; `import time` → remove, add `from pynamodb.asyncio import _compat`; `Iterator` → `AsyncIterator` in `typing` imports **only** for converted return types (`batch_get`).
  - `time.sleep(2)` (two places: `delete_table` wait and `create_table` wait) → `await _compat.sleep(2)`.
  - `BatchWrite`: `__enter__`/`__exit__` → `async def __aenter__`/`async def __aexit__` (`return await self.commit()`); `save`, `delete` → `async def` with `await self.commit()` where they auto-commit; `commit` → `async def`, both `batch_write_item(...)` calls awaited.
  - `Model`: `async def` + `await` for `batch_get` (async generator: `-> AsyncIterator[_T]`, `page, unprocessed_keys = await cls._batch_get_page(...)`), `delete`, `update`, `save`, `refresh`, `get`, `count`, `exists`, `delete_table`, `describe_table`, `create_table`, `update_ttl`, `_batch_get_page`, and any private helper that calls them (check each `self._get_connection().` / `cls._get_connection().` call site: the call is awaited if the connection method is async). `query` and `scan` stay plain `def` (they build a `ResultIterator`); `batch_write` stays plain `def`; `_get_connection` stays plain `def`.
  - `count`: when it pages through results it calls the connection's `query` — await it.
  - Add after `_get_connection`:

```python
    @classmethod
    async def close(cls) -> None:
        """
        Closes this model's connection, if one is open
        """
        if cls._connection is not None:
            await cls._connection.close()
            cls._connection = None
```

  - `pynamodb/asyncio/indexes.py`: imports → async `pagination`, `TYPE_CHECKING` import of `pynamodb.asyncio.models`; `count` → `async def`, `return await self._model.count(...)`. `query`/`scan` stay plain `def`.
- [ ] **Step 3:** Add `("pynamodb/asyncio/models.py", "pynamodb/models.py")`, `("pynamodb/asyncio/indexes.py", "pynamodb/indexes.py")` to `FILES`; regenerate.
- [ ] **Step 4: Diff proof.** `git diff -- pynamodb/models.py pynamodb/indexes.py`. **Expected sync diff:** headers; `import time` → `from pynamodb import _compat`; `time.sleep(2)` → `_compat.sleep(2)` (2 lines); new `close` classmethod. Nothing else.
- [ ] **Step 5: Run** `uv run pytest tests/ -k "not ddblocal" -q -p no:cacheprovider` → all original + generated + new tests PASS; `--check` → 0; `uv run mypy .` → clean.
- [ ] **Step 6: Commit**

```bash
git add pynamodb/asyncio/models.py pynamodb/asyncio/indexes.py pynamodb/models.py pynamodb/indexes.py scripts/unasync.py tests/asyncio/test_model_close.py tests/test_asyncio_import.py
git commit -m "Make Model and indexes async-sourced; add Model.close()

This is the user-facing async API. query/scan/batch_write stay plain
calls returning async iterators or context managers, so only operations
that actually send a request are awaited. The generated sync modules
differ from the originals only in the header, the retry sleep going
through _compat, and the new close() classmethod.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Convert `test_model.py`

**Files:**
- Create (source): `tests/asyncio/test_model.py`; generated `tests/sync_generated/test_model.py`
- Modify: `scripts/unasync.py`

- [ ] **Step 1:** `cp tests/test_model.py tests/asyncio/test_model.py`; apply the test-file mechanical edits. File-specific:
  - `PATCH_METHOD` and `patch("pynamodb.connection.TableConnection.describe_table")` gain `asyncio.`.
  - Model classes defined in the test module subclass `pynamodb.asyncio.models.Model` (fix the import), and imports from `pynamodb.indexes` → `pynamodb.asyncio.indexes`.
  - `for item in Model.query(...)` / `scan` / `batch_get` → `async for`; `list(Model.query(...))` → `[x async for x in Model.query(...)]`; `next(iter(Model.query(...)))` → `await anext(Model.query(...))`.
  - `with Model.batch_write() as batch:` → `async with`; `batch.save(x)` / `batch.delete(x)` → `await`.
  - `fake_db = MagicMock()` used as an awaited `_make_api_call` side effect → keep `MagicMock` but pass it as `side_effect` of the patched `AsyncMock` (the patch is already an `AsyncMock`); objects whose methods are awaited → `AsyncMock()`.
  - `patch('time.time')` targets stay as is.
  - Any test that asserts on `time.sleep` for table waits → patch `'pynamodb.asyncio._compat.sleep'` (generated: `'pynamodb._compat.sleep'`, which the sync code now calls).
- [ ] **Step 2:** Add `("tests/asyncio/test_model.py", "tests/sync_generated/test_model.py")` to `FILES`; regenerate.
- [ ] **Step 3: Run** `uv run pytest tests/asyncio/test_model.py tests/sync_generated/test_model.py tests/test_model.py -q -p no:cacheprovider` → PASS, and the async and generated files each report the same test count as `tests/test_model.py` (97 `def test_`). `--check` → 0.
- [ ] **Step 4: Commit**

```bash
git add tests/asyncio/test_model.py tests/sync_generated/test_model.py scripts/unasync.py
git commit -m "Port the Model test suite to async source with a generated sync twin

The async API needs the same coverage as the sync one. Converting the
existing suite (rather than writing new tests) keeps both sides checked
against identical scenarios, and the generated twin proves the generator
round-trips test code as well as library code.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Convert `transactions.py` and its tests

**Files:**
- Create (source): `pynamodb/asyncio/transactions.py`, `tests/asyncio/test_transaction.py`
- Generated: `pynamodb/transactions.py`, `tests/sync_generated/test_transaction.py`
- Modify: `scripts/unasync.py`

- [ ] **Step 1: Async source** via the **Conversion procedure**. File-specific edits in `pynamodb/asyncio/transactions.py`:
  - Imports: `from pynamodb.connection import Connection` → `from pynamodb.asyncio.connection import Connection`; `from pynamodb.models import ...` → `from pynamodb.asyncio.models import ...`.
  - `Transaction.__enter__` → `async def __aenter__`; `__exit__` → `async def __aexit__` with `await self._commit()`; `_commit` (base and both subclasses) → `async def`, connection calls awaited.
  - `TransactGet.get`, `TransactWrite.condition_check/delete/save/update` stay plain `def` (they only collect operations).
- [ ] **Step 2:** `FILES` += `("pynamodb/asyncio/transactions.py", "pynamodb/transactions.py")`; regenerate. **Expected sync diff:** header only.
- [ ] **Step 3: Tests.** `cp tests/test_transaction.py tests/asyncio/test_transaction.py`; mechanical edits; `with TransactWrite(...)` / `TransactGet(...)` → `async with`; `FILES` += `("tests/asyncio/test_transaction.py", "tests/sync_generated/test_transaction.py")`; regenerate.
- [ ] **Step 4: Run** `uv run pytest tests/ -k "not ddblocal" -q -p no:cacheprovider` → PASS; `--check` → 0; `uv run mypy .` → clean.
- [ ] **Step 5: Commit**

```bash
git add pynamodb/asyncio/transactions.py pynamodb/transactions.py tests/asyncio/test_transaction.py tests/sync_generated/test_transaction.py scripts/unasync.py
git commit -m "Make transactions async-sourced

Transactions only send a request when the block exits, so the async API
is async with plus plain (non-awaited) collect calls; the generated sync
module is identical to the original apart from its header.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Async integration tests and typing tests

**Files:**
- Create (source): `tests/asyncio/integration/__init__.py`, `tests/asyncio/integration/conftest.py`, async copies of each `tests/integration/*.py` test module
- Generated: `tests/sync_generated/integration/*`
- Create (hand): `typing_tests/asyncio/__init__.py`, `typing_tests/asyncio/models.py`, `typing_tests/asyncio/transactions.py`
- Modify: `scripts/unasync.py`

- [ ] **Step 1: Start DynamoDB Local** (scratchpad, not `/tmp`):

```bash
D=/private/tmp/claude-502/-Users-sodre-ghq-github-com-pynamodb-pynamodb/972fa93d-4654-464b-b03f-01135c54364c/scratchpad/ddblocal
mkdir -p "$D" && curl -sSL http://dynamodb-local.s3-website-us-west-2.amazonaws.com/dynamodb_local_latest.tar.gz | tar -xz -C "$D"
java -Djava.library.path="$D/DynamoDBLocal_lib" -jar "$D/DynamoDBLocal.jar" -inMemory -port 8000   # run_in_background
```

Then `uv run pytest tests/integration -q -p no:cacheprovider` → the 21 `ddblocal` tests PASS (sync baseline).

- [ ] **Step 2: Convert** each integration module with the test-file mechanical edits (`ddb_url` fixture comes from a copied `conftest.py`; table creation/deletion calls awaited; add `await Model.close()` / `await conn.close()` in teardown so aiohttp sessions do not leak). Add each pair to `FILES` (`tests/asyncio/integration/X.py` → `tests/sync_generated/integration/X.py`, including `conftest.py` and `__init__.py`); regenerate.
- [ ] **Step 3: Typing tests.** `typing_tests/asyncio/models.py` mirrors `typing_tests/models.py` with async calls, e.g.:

```python
from __future__ import annotations

from typing_extensions import assert_type


async def test_model_count() -> None:
    from pynamodb.asyncio.models import Model
    from pynamodb.expressions.operand import Path

    class MyModel(Model):
        pass

    assert_type(await MyModel.count('hash', Path('a').between(1, 3)), int)


async def test_model_query() -> None:
    from pynamodb.attributes import NumberAttribute
    from pynamodb.asyncio.models import Model

    class MyModel(Model):
        my_attr = NumberAttribute()

    async for item in MyModel.query(123, range_key_condition=(MyModel.my_attr == 5)):
        assert_type(item, MyModel)
```

Port every function in `typing_tests/models.py` and `typing_tests/transactions.py` the same way (`await` on awaited calls, `async for` / `async with` where the sync test iterates or uses `with`).
- [ ] **Step 4: Run** `uv run pytest tests/ -q -p no:cacheprovider` (DynamoDB Local up) → all PASS including `ddblocal`; `uv run mypy .` → clean; `--check` → 0. Stop DynamoDB Local.
- [ ] **Step 5: Commit**

```bash
git add tests/asyncio/integration tests/sync_generated/integration typing_tests/asyncio scripts/unasync.py
git commit -m "Add async integration and typing tests

Unit tests mock _make_api_call, so only DynamoDB Local proves the async
path works end to end (aiohttp transport, signing, waiters). The typing
tests pin the async public signatures the way typing_tests/ pins the
sync ones.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: CI, mypy and coverage configuration

**Files:**
- Modify: `.github/workflows/test.yaml`, `.coveragerc`, `mypy.ini` (only if needed)

- [ ] **Step 1: Edit `.github/workflows/test.yaml`:**
  - `test` job, "Install dependencies": `python -m pip install -e .[signals,asyncio] -r requirements-dev.txt`.
  - `test` job, new step before "Run tests":

```yaml
    - name: Verify generated sync code is up to date
      run: |
        python scripts/unasync.py --check
```

  - `mypy` job: `python-version: 3.8` → `'3.11'`; install `.[signals,asyncio]`.
  - `build-docs` job: `python-version: 3.8` → `'3.11'`.
- [ ] **Step 2:** `.coveragerc`: confirm `pynamodb/asyncio/*` and generated modules are both measured (no `omit` excluding them). If `[run] source` is set, keep it at `pynamodb`.
- [ ] **Step 3: Verify locally what CI runs:** `uv run python scripts/unasync.py --check` → 0; `uv run pytest --cov-report term-missing --cov=pynamodb tests -k "not ddblocal" -q -p no:cacheprovider` → PASS, and the coverage table lists `pynamodb/asyncio/*.py`; `uv run mypy .` → clean. If mypy 1.2.0 cannot parse `types-aiobotocore` stubs, add to `mypy.ini`:

```ini
[mypy-aiobotocore.*]
ignore_errors = True
follow_imports = skip
```

  and record that in the commit message.
- [ ] **Step 4: Python 3.7 sanity (sync only):** `uv run --python 3.8 --isolated --with-editable . --with pytest --with pytest-env --with pytest-mock --with freezegun pytest tests -k "not ddblocal" -q -p no:cacheprovider` → async folder skipped, everything else PASS. (3.7 may not be installable via uv on this machine; 3.8 is the oldest checked locally — CI covers 3.7.)
- [ ] **Step 5: Commit**

```bash
git add .github/workflows/test.yaml .coveragerc mypy.ini
git commit -m "Check generated code and type-check async in CI

A stale generated file would ship sync behaviour that no longer matches
its source, so CI regenerates and fails on any difference. mypy and the
docs build move to 3.11 because the async package, its stubs, and its
API docs need Python 3.10+.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Reference documentation, contributing guide, CLAUDE.md, example

**Files:**
- Create: `docs/asyncio.rst`, `examples/async_model.py`
- Modify: `docs/index.rst`, `docs/api.rst`, `docs/low_level.rst`, `docs/contributing.rst`, `docs/release_notes.rst`, `docs/conf.py`, `docs/requirements.txt`, `CLAUDE.md`

- [ ] **Step 1:** `docs/requirements.txt`: `.[signals]` → `.[signals,asyncio]`; add `sphinx-tabs`. `docs/conf.py` `extensions` += `'sphinx_tabs.tabs'`. Install: `uv pip install -r docs/requirements.txt`.
- [ ] **Step 2: `docs/asyncio.rst`** with these sections (full prose, rst):
  - *Installing* — `pip install pynamodb[asyncio]`; Python 3.10+; the extra pulls aiobotocore, which pins its own botocore range.
  - *Usage* — `from pynamodb.asyncio.models import Model` declaration example; then a table of operations (the spec §3 table) and code for get/save/query/batch_write/transactions.
  - *Closing clients* — `await Model.close()`; `async with pynamodb.asyncio.connections():`; why (aiohttp sessions); sync equivalents exist.
  - *Shared clients* — models with identical settings on the same event loop share one client; `extra_headers` and other settings split them.
  - *Event loops* — a client belongs to its loop; a new loop (e.g. a second `asyncio.run`) gets a new client; prefer one long-lived loop.
  - *Low-level* — `pynamodb.asyncio.connection.Connection`; `await conn.get_client()`; `conn.client` raises until opened.
  - *Not yet supported* — concurrent requests (parallel scan, concurrent batch pages); call `asyncio.gather` yourself across independent operations.
- [ ] **Step 3:** `docs/index.rst`: insert `   asyncio` after `   quickstart` in the toctree. `docs/api.rst`: add a section "Async API" with `.. automodule::` for `pynamodb.asyncio.models` (`:members: Model`), `pynamodb.asyncio.connection` (`:members: Connection, TableConnection`), `pynamodb.asyncio.transactions` (`:members: TransactGet, TransactWrite`), `pynamodb.asyncio.pagination` (`:members: ResultIterator, PageIterator, RateLimiter`), and `pynamodb.asyncio` (`:members: connections`). `docs/low_level.rst`: add an "Async connections" subsection (3 short examples: create, `await conn.get_item(...)`, `await conn.close()`).
- [ ] **Step 4: `docs/contributing.rst`** — new section "Async source and generated sync code": edit `pynamodb/asyncio/` and `tests/asyncio/`, never the generated files (they start with `AUTO-GENERATED`); run `python scripts/unasync.py`; CI runs `--check`; things that cannot be rewritten go in the `_compat` pair; `asyncio.gather`/`create_task`/`wait_for` and `import asyncio` in library source abort generation; async tests need Python 3.10+ and `pip install -e .[signals,asyncio] -r requirements-dev.txt`; original `tests/test_*.py` are the compatibility suite and are not edited for async work.
- [ ] **Step 5: `docs/release_notes.rst`** — new top section:

```rst
Unreleased
----------

Features:

* Add an async API, ``pynamodb.asyncio``, built on aiobotocore. Install with
  ``pip install pynamodb[asyncio]`` (Python 3.10+). See :doc:`asyncio`.
* Add ``Model.close()``, ``Connection.close()``, ``Connection.get_client()`` and the
  ``pynamodb.connections()`` context manager for closing clients explicitly.

Other:

* The sync modules ``models``, ``indexes``, ``pagination``, ``transactions`` and
  ``connection`` are now generated from the async source by ``scripts/unasync.py``.
```

- [ ] **Step 6: `examples/async_model.py`** — a runnable script mirroring `examples/model.py` (read it first) against DynamoDB Local: declares a model, `create_table(wait=True)`, saves, gets, queries with `async for`, batch-writes, deletes the table, all inside `async with pynamodb.asyncio.connections():` under `asyncio.run(main())`.
- [ ] **Step 7: `CLAUDE.md`** — update: Commands (`uv pip install -e '.[signals,asyncio]' -r requirements-dev.txt`; `uv run python scripts/unasync.py [--check]`); Architecture (async source under `pynamodb/asyncio/`, generated sync paths, `_compat` pair, shared async clients); a "Generated files — DO NOT EDIT" list matching `FILES`; tests layout (`tests/asyncio`, `tests/sync_generated`, frozen originals).
- [ ] **Step 8: Verify** `uv run sphinx-build -W docs /private/tmp/claude-502/-Users-sodre-ghq-github-com-pynamodb-pynamodb/972fa93d-4654-464b-b03f-01135c54364c/scratchpad/docs-build` → succeeds with no warnings. With DynamoDB Local running: `uv run python examples/async_model.py` → exits 0.
- [ ] **Step 9: Commit**

```bash
git add docs CLAUDE.md examples/async_model.py
git commit -m "Document the async API and the generated-code workflow

Users need the install extra, the Python floor, and the client-closing
and event-loop rules that have no sync equivalent; contributors need to
know which files are generated and how to regenerate them.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Sync/Async tabs across the guide pages

**Files:**
- Modify: `docs/transaction.rst`, `docs/optimistic_locking.rst`, `docs/quickstart.rst`, `docs/updates.rst`, `docs/conditional.rst`, `docs/tutorial.rst`, `docs/batch.rst`, `docs/indexes.rst`, `docs/rate_limited_operations.rst`, `docs/attributes.rst`, `docs/upgrading_binary.rst`

- [ ] **Step 1:** For each page, every `.. code-block:: python` whose code performs a network call (`.save(`, `.get(`, `.query(`, `.scan(`, `.update(`, `.delete(`, `.refresh(`, `.count(`, `.batch_get(`, `.batch_write(`, `.create_table(`, `.delete_table(`, `.exists(`, `TransactWrite(`, `TransactGet(`) becomes:

```rst
.. tabs::

   .. code-tab:: python Sync

      <original code, unchanged>

   .. code-tab:: python Async

      <same code: awaited calls, async for / async with, imports from pynamodb.asyncio>
```

Blocks that only declare models or attributes stay single `code-block`s. `quickstart.rst` uses `::` literal blocks — convert each network example to the tabs form; leave non-network literal blocks alone.
- [ ] **Step 2: Verify** `uv run sphinx-build -W docs <scratchpad>/docs-build` → no warnings; open `<scratchpad>/docs-build/batch.html` and confirm the tabs render (search the HTML for `sphinx-tabs`).
- [ ] **Step 3: Commit**

```bash
git add docs
git commit -m "Show sync and async side by side in the guide pages

Readers arrive at a guide page from search, not from the asyncio page,
so each network example carries its async form next to the sync one.
Declaration-only examples are unchanged to keep the pages readable.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Final verification ("Done means")

- [ ] **Step 1:** `git diff add-claude-md -- tests/test_*.py tests/integration/` → empty (original tests untouched).
- [ ] **Step 2:** `git diff add-claude-md -- pynamodb/models.py pynamodb/indexes.py pynamodb/pagination.py pynamodb/transactions.py pynamodb/connection/` → only the lines listed as "Expected sync diff" in Tasks 3, 4, 5, 6, 8. Save the diff to the scratchpad and report its size.
- [ ] **Step 3:** With DynamoDB Local running: `uv run pytest tests/ -q -p no:cacheprovider` → all PASS (originals, async, generated, integration).
- [ ] **Step 4:** `uv run python scripts/unasync.py --check` → 0; `uv run mypy .` → clean; `uv run sphinx-build -W docs <scratchpad>/docs-build` → clean.
- [ ] **Step 5:** Sync-only environment on Python 3.8 (Task 10 Step 4 command) → PASS with async skipped.
- [ ] **Step 6:** No commit (verification only). Report results as a table: each "Done means" item from the spec with PASS/FAIL and the command output summary.
