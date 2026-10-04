# Async support for PynamoDB — design

- **Date:** 2026-10-03
- **Status:** Approved in conversation; spec pending review
- **Branch:** `async-support` (local only — we do not own upstream; nothing is pushed)

## Goal

Add an async API to PynamoDB on top of `aiobotocore`, while today's sync API keeps working
**byte-for-byte the same** for existing users.

The pattern is "unasync": the async code is the single hand-edited source, and the sync code is
generated from it by a script, committed to git, and checked in CI. This mirrors
`zeroae/zae-limiter` (ADR-121), with one deliberate difference: we generate with a line-based text
rewriter instead of an AST transformer, so comments and layout survive and the generated sync files
diff cleanly against today's files.

## Non-goals (this branch)

- Running DynamoDB calls concurrently (`asyncio.gather`): parallel scan, concurrent `batch_get`
  pages, overlapping `BatchWrite` flushes. Planned as a follow-up via a `run_concurrently` helper
  in `_compat` (see "Future: concurrency").
- Sharing clients on the **sync** side. Sync keeps one client per model, as today.
- Any behaviour change for sync users, except the purely additive `close()` / `connections()` API.

## Decisions

| # | Topic | Decision |
|---|---|---|
| D1 | Public async API | Separate module with the same class names: `from pynamodb.asyncio.models import Model` |
| D2 | Closing clients | Both: `await Model.close()` per model, and `async with pynamodb.asyncio.connections():` to close all |
| D3 | Tests | Hybrid: today's tests stay untouched; async tests are the source; their sync twins are generated |
| D4 | Docs | Focused set plus Sync/Async tabs on every page whose examples make network calls |
| D5 | Generator | Line-based text rewriter + small hand-written `_compat` modules per side |
| D6 | Client sharing | Async only: clients shared per (event loop, settings) key, reference counted |
| D7 | Concurrency | Out of scope; follow-up |
| D8 | Workspace | Worktree `.claude/worktrees/async-support`, based on local `add-claude-md` |

## 1. Layout and generator

### Modules

Shared, unchanged (no network I/O; verified none of them import the network modules):
`attributes.py`, `expressions/`, `_util.py`, `_schema.py`, `constants.py`, `exceptions.py`,
`settings.py`, `signals.py`, `types.py`.

Async source (hand-edited, public as `pynamodb.asyncio.*`):

```
pynamodb/asyncio/__init__.py
pynamodb/asyncio/models.py
pynamodb/asyncio/indexes.py
pynamodb/asyncio/pagination.py
pynamodb/asyncio/transactions.py
pynamodb/asyncio/connection/__init__.py
pynamodb/asyncio/connection/base.py
pynamodb/asyncio/connection/table.py
```

Generated sync twins (at today's paths, so no import changes for sync users):

```
pynamodb/models.py  pynamodb/indexes.py  pynamodb/pagination.py  pynamodb/transactions.py
pynamodb/connection/__init__.py  pynamodb/connection/base.py  pynamodb/connection/table.py
```

Hand-written pairs (never generated):

| Async | Sync | Holds |
|---|---|---|
| `pynamodb/asyncio/_compat.py` | `pynamodb/_compat.py` | open/close client, `client` property body, `sleep`, default rate-limiter time module, async client cache |
| `pynamodb/asyncio/connection/_botocore_private.py` | `pynamodb/connection/_botocore_private.py` (exists) | typing for the private client API |

`pynamodb/asyncio/__init__.py` raises a clear `ImportError` ("install `pynamodb[asyncio]`,
Python 3.10+") when `aiobotocore` is not importable. `import pynamodb` never imports
`pynamodb.asyncio`.

### Generator: `scripts/unasync.py`

- Line-based; preserves comments and formatting. Roughly 150 lines, no third-party dependencies.
- Source → target mapping is an explicit table in the script (source modules above, and the
  test files in section 5).
- Each generated file starts with:
  `# AUTO-GENERATED from <source path> by scripts/unasync.py - DO NOT EDIT`
- `--check` regenerates in memory and exits 1 listing any file that differs.
- Aborts with a clear error (file, line, construct) if the source contains `asyncio.gather`,
  `asyncio.create_task`, or `asyncio.wait_for`. These cannot be rewritten textually and belong in
  `_compat`.

Rewrite rules (whole-token matches, applied in this order — more specific first):

| Async | Sync |
|---|---|
| `pynamodb.asyncio.` | `pynamodb.` |
| `tests.asyncio.` | `tests.sync_generated.` |
| `async def` | `def` |
| `async with` | `with` |
| `async for` | `for` |
| `await ` | (removed) |
| `__aenter__` / `__aexit__` | `__enter__` / `__exit__` |
| `__aiter__` / `__anext__` | `__iter__` / `__next__` |
| `StopAsyncIteration` | `StopIteration` |
| `AsyncIterator` / `AsyncIterable` | `Iterator` / `Iterable` |
| `asynccontextmanager` | `contextmanager` |
| `aiobotocore.session` | `botocore.session` |
| `IsolatedAsyncioTestCase` | `TestCase` |
| `AsyncMock` | `MagicMock` |
| line `pytestmark = pytest.mark.asyncio` | (line removed) |

### Proof that sync did not change

The first conversion is done by copying each sync module into `pynamodb/asyncio/`, adding
`async`/`await`, and regenerating. `git diff` of the generated sync files against the
`add-claude-md` base must show only: the generated-file header, and call sites that now go through
`_compat` helpers (client open/close, `client` property body, retry `sleep`, rate-limiter default).
Any other diff line is a bug in the conversion.

## 2. Connection and closing

- New `Connection._get_client()` (async in source). Holds today's `client` property logic
  (config, credential-poisoning guard, `before-send` header hook). `_make_api_call` awaits it.
- The `client` property stays; its body is `_compat.client_property(self)`:
  - sync: lazily creates the client — identical to today.
  - async: returns the already-open client, or raises `RuntimeError` telling the user to
    `await conn.get_client()` first. A public `get_client()` wraps `_get_client()`.
- Opening: sync `session.create_client(...)`; async
  `await session.create_client(...).__aenter__()`.
- Closing: sync calls `client.close()` when botocore provides it; async
  `await client.__aexit__(None, None, None)`.
- Per-thread session (`threading.local`) is kept on both sides.

### Async client sharing (async only)

Async clients live in a cache in `pynamodb/asyncio/_compat.py`, keyed by:

> (running event loop, region, host, credentials, connect/read timeouts, retry configuration,
> max_pool_connections, extra_headers)

`extra_headers` must be in the key because the header hook is registered on the client
(`register_first('before-send.*.*', ...)`); sharing across different headers would leak them.
The loop is in the key because an aiobotocore client is bound to the loop that created it. The
cache holds the loop weakly so entries for finished loops are dropped.

Entries are reference counted: each `Connection` acquires on first use and releases on `close()`;
the client is closed when the count reaches zero.

### Close API (added on both sides)

| API | Effect |
|---|---|
| `Model.close()` (classmethod; awaitable on async) | closes/releases that model's connection and clears `cls._connection` |
| `Connection.close()` / `TableConnection.close()` | same for direct connection users |
| `pynamodb.asyncio.connections()` / `pynamodb.connections()` | context manager; on exit closes every connection that opened a client. Connections register in a module-level `weakref.WeakSet` when they open a client |

### To verify during implementation

- aiobotocore's client exposes `_request_signer._credentials` like botocore (used by the
  empty-credentials guard), or the guard needs an async-side variant in `_compat`.
- `botocore` `BaseClient.close()` availability across the supported botocore range.
- Minimum `aiobotocore` version providing async `_make_api_call` and `__aenter__`.

## 3. Async user API

| Area | Async | Sync (unchanged) |
|---|---|---|
| Item ops | `await item.save()` / `update()` / `delete()` / `refresh()`; `await User.get(k)` | no `await` |
| Table ops | `await User.create_table()` / `delete_table()` / `describe_table()` / `exists()` / `update_ttl()` | no `await` |
| Count | `await User.count(...)`, `await User.idx.count(...)` | no `await` |
| Query / scan | `async for u in User.query(...)` (call is not awaited) | `for` |
| Paging | `.last_evaluated_key`, `.total_count`, `await it.next()` | `it.next()` |
| Batch get | `async for u in User.batch_get(keys)` | `for` |
| Batch write | `async with User.batch_write() as b:` then `await b.save(x)` / `await b.delete(x)` (may auto-commit) | `with`, no `await` |
| Transactions | `async with TransactWrite() as t:` then `t.save(x)` (collect only, no `await`) | `with` |
| Transact get | `async with TransactGet() as t: f = t.get(User, k)`; `f.get()` after the block | `with` |
| No I/O | constructors, attributes, conditions, `serialize`, `from_raw_data` | same |

- Rate limiter: source uses `await self._time_module.sleep(...)`, which generates to today's
  `self._time_module.sleep(...)`. Default time module: sync `time`; async a small object in
  `asyncio/_compat.py` with `time = time.time` and `async def sleep`.
- Retry sleeps in `models.py` use `await _compat.sleep(2)`.
- Iterator bases: `AsyncIterator[_T]` in source → `Iterator[_T]` generated.

## 4. Packaging, Python versions, CI

- New extra in `setup.py`: `'asyncio': ['aiobotocore>=<min>; python_version>="3.10"']`
  (`<min>` confirmed during implementation). Core `install_requires` unchanged.
- Python 3.7–3.9: extra installs nothing; sync works as today.
- Async source and generated code both use Python 3.7 syntax only.
- `.github/workflows/test.yaml`:
  - `test`: install `.[signals,asyncio]`; async tests run on 3.10+, skipped below with a reason.
  - new step: `python scripts/unasync.py --check`.
  - `mypy`: Python 3.8 → 3.11, install `.[signals,asyncio]` and `types-aiobotocore[dynamodb]`.
    Keep `mypy==1.2.0` unless it cannot handle the stubs.
  - `build-docs`: Python 3.8 → 3.11 (matches `.readthedocs.yaml`).
- `requirements-dev.txt`: add `types-aiobotocore[dynamodb]` and
  `pytest-asyncio; python_version>="3.10"`.
- `docs/requirements.txt`: `.[signals]` → `.[signals,asyncio]`; add `sphinx-tabs`.

## 5. Tests

| Path | Contents | Edited by |
|---|---|---|
| `tests/test_*.py`, `tests/integration/*` | today's tests, **untouched** (compat proof) | nobody |
| `tests/asyncio/` | async source of `test_model`, `test_base_connection`, `test_table_connection`, `test_transaction`, `test_signals`, `test_pagination`, plus `integration/` | hand |
| `tests/sync_generated/` | generated sync twins of `tests/asyncio/` | `scripts/unasync.py` |
| `typing_tests/asyncio/` | mypy checks of the async public API | hand |
| `tests/test_unasync.py` | generator tests: each rule, comment preservation, forbidden constructs abort | hand |

- `PATCH_METHOD` in async tests targets `pynamodb.asyncio.connection.Connection._make_api_call`;
  `patch` on an `async def` yields an `AsyncMock` (to confirm on first conversion).
- `pytest.ini` sets `asyncio_mode = auto`, so async test functions need no marker (a module-level
  `pytestmark` would also mark the plain tests converted files keep); `unittest` classes use
  `IsolatedAsyncioTestCase`. The generator still drops a `pytestmark = pytest.mark.asyncio` line
  defensively.
- `tests/asyncio/conftest.py` skips the folder on Python < 3.10 or without `aiobotocore`.
- New tests: client sharing key (same settings share, different `extra_headers` do not), reference
  counting, `connections()` closes all, async `client` property raises before open, loop change
  gets a fresh client, `asyncio` import error message.
- Coverage measured on both async source and generated sync.

### Done means

1. Original tests pass unchanged.
2. Async tests pass on Python 3.10+.
3. Generated sync tests pass on every supported Python.
4. `python scripts/unasync.py --check` passes.
5. `mypy .` is clean.
6. `sphinx-build -W docs /tmp/docs-build` passes.

## 6. Documentation

| File | Change |
|---|---|
| `docs/asyncio.rst` (new) | install; Python 3.10+; API table; closing; client sharing and `extra_headers`; event-loop rule; concurrency not yet supported |
| `docs/index.rst` | add `asyncio` to the toctree after `quickstart` |
| `docs/api.rst` | autodoc for `pynamodb.asyncio.models`, `.connection`, `.transactions`, `.pagination` |
| `docs/low_level.rst` | async `Connection` usage and the `client` property rule |
| `docs/contributing.rst` | "Async source and generated sync code" workflow |
| `docs/release_notes.rst` | unreleased entry: async extra; `close()` / `connections()` |
| `docs/conf.py` | add `sphinx_tabs.tabs` |
| `CLAUDE.md` | async architecture, generator workflow, do-not-edit list |
| `examples/` | one async example script |

Sync/Async tabs (`.. tabs::` / `.. code-tab:: python Sync|Async`) on examples that perform network
calls in: `transaction`, `optimistic_locking`, `quickstart`, `updates`, `conditional`, `tutorial`,
`batch`, `indexes`, `rate_limited_operations`, `attributes`, `upgrading_binary`. Model-declaration
examples stay single blocks. `quickstart.rst` is converted to the tab format. Release notes,
upgrading pages, and `logging` stay sync-only.

## Future: concurrency

Add `run_concurrently(*funcs)` to both `_compat` modules — async `asyncio.gather` with a bounded
concurrency limit, sync serial by default — so the line-based generator never needs to translate
`gather`. Candidates in value order: a parallel-scan helper, concurrent `batch_get` pages,
overlapping `BatchWrite` flushes. Results should stream (`as_completed` / queue) rather than wait for
all pages.

## Risks

| Risk | Mitigation |
|---|---|
| Text rules mangle a string or identifier | whole-token matching; `--check` + diff-against-original proof; generator unit tests |
| aiobotocore private API drift (`_make_api_call`, request signer) | version floor in extra; typed private shim per side; async tests |
| aiobotocore's tight botocore pin | only affects users of the `asyncio` extra |
| Large diff (≈3k source + ≈6k test lines) | conversion is mechanical; the original sync tests and the diff proof guard it |
