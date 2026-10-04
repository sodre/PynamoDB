# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PynamoDB is a Pythonic ODM (object-document mapper) for Amazon DynamoDB, built directly on `botocore` (not `boto3`). Supports Python 3.7+; the only runtime deps are `botocore` and `typing-extensions` (`blinker` is the optional `signals` extra, `aiobotocore` the optional `asyncio` extra, Python 3.10+).

## Commands

Setup (the repo uses plain pip/setuptools; with uv):

```bash
uv venv && uv pip install -e '.[signals,asyncio]' -r requirements-dev.txt
```

Tests (`pytest.ini` sets fake AWS credentials via `pytest-env`):

```bash
uv run pytest tests/ -k "not ddblocal"                         # unit tests only
uv run pytest tests/test_model.py::ModelTestCase::test_save    # single test
uv run pytest tests/                                            # includes integration tests
```

Integration tests are marked `@pytest.mark.ddblocal` and need DynamoDB Local on `localhost:8000` (override with `PYNAMODB_INTEGRATION_TEST_DDB_URL`). Requires Java:

```bash
wget --quiet http://dynamodb-local.s3-website-us-west-2.amazonaws.com/dynamodb_local_latest.tar.gz -O /tmp/dynamodb_local_latest.tar.gz
tar -xzf /tmp/dynamodb_local_latest.tar.gz -C /tmp
java -Djava.library.path=/tmp/DynamoDBLocal_lib -jar /tmp/DynamoDBLocal.jar -inMemory -port 8000
```

Type checking (CI runs this on Python 3.11 with pinned `mypy==1.2.0`):

```bash
uv run mypy .
```

`typing_tests/` is not run by pytest — it is checked by mypy only (uses `assert_type` to verify the public API's type signatures). `tests.*` has mypy errors ignored.

Generated sync code (see "Async source and generated files" below):

```bash
uv run python scripts/unasync.py          # regenerate
uv run python scripts/unasync.py --check  # CI check: fails if generated files are stale
```

Docs (Sphinx, warnings are errors in CI; docs build runs on Python 3.11):

```bash
uv pip install -r docs/requirements.txt && uv run sphinx-build -W docs /tmp/docs-build
```

## Architecture

The async API under `pynamodb/asyncio/` is the source of truth; the sync modules are generated from it (next section).

Layered, top to bottom:

1. **`pynamodb/models.py` — `Model`** (metaclass `MetaModel`). User-facing API: `get`, `query`, `scan`, `save`, `update`, `delete`, `batch_get`, `batch_write`, `create_table`, etc. Reads table config from the inner `class Meta` (table name, region, host, billing, etc.), falling back to `pynamodb/settings.py`. Each model class lazily builds its own `TableConnection` via `_get_connection()`.
2. **`pynamodb/connection/table.py` — `TableConnection`**: thin wrapper binding a table name to a `Connection`.
3. **`pynamodb/connection/base.py` — `Connection`**: builds DynamoDB request dicts, calls the botocore client, handles retries/errors, and caches table metadata (`MetaTable`). Raw DynamoDB wire format lives here. `_botocore_private.py` types botocore internals it relies on.

Cross-cutting pieces:

- **`attributes.py`**: `Attribute[T]` base with `serialize`/`deserialize`, plus `AttributeContainer`/`AttributeContainerMeta`, which collect `Attribute` class members into `_attributes` and map Python names to DynamoDB names (`attr_name=`). Both `Model` and `MapAttribute` are `AttributeContainer`s. `MapAttribute` is dual-mode: as a class attribute it is a schema/path; as an instance value it is data. `DiscriminatorAttribute` enables polymorphic models (subclass chosen on deserialize).
- **`expressions/`**: attributes double as expression builders. `Model.attr == 5`, `.startswith()`, `.set()`, `.add()`, etc. return `Condition`/`Action` objects (`condition.py`, `update.py`) built on `Path`/`Value` operands (`operand.py`); `util.py` turns them into DynamoDB expression strings plus placeholder name/value maps.
- **`indexes.py`**: `GlobalSecondaryIndex` / `LocalSecondaryIndex` declared as class attributes on a `Model`, with their own `query`/`scan`.
- **`pagination.py`**: `ResultIterator` / `PageIterator` drive `query`/`scan` paging and optional rate limiting.
- **`transactions.py`**: `TransactGet` / `TransactWrite` context managers.
- **`settings.py`**: defaults, overridable by a Python file at `$PYNAMODB_CONFIG` (default `/etc/pynamodb/global_default_settings.py`).
- **`signals.py`**: `pre_dynamodb_send` / `post_dynamodb_send` (blinker if installed, no-op otherwise).
- **`constants.py`**: DynamoDB API key/type string constants used throughout instead of literals.

Tests: `tests/data.py` and `tests/response.py` hold canned DynamoDB responses; unit tests mock botocore calls (e.g. `PATCH_METHOD` in `test_model.py`) rather than hitting a server.

## Project rules (from `docs/contributing.rst`)

- **Backwards compatibility of stored data matters most.** Data written by an older version must still be readable. If an attribute's serialization must change, keep reading the old format for at least one major version, or add a new attribute under a new name and deprecate the old one. Follow semver for API changes.
- **Scope**: an ODM for app runtime, not a DB admin tool. Table-admin ops exist only to support dynamodb-local/moto in tests; don't add features like PITR or index updates. Generic non-DynamoDB-specific attributes (e.g. UUID-as-string) belong in [pynamodb-attributes](https://github.com/lyft/pynamodb-attributes), not here.
- Add type annotations to any code you modify; new code needs test coverage (CI checks the delta).
- Non-trivial changes get an entry in `docs/release_notes.rst`. The version string is `__version__` in `pynamodb/__init__.py`.

## Async source and generated files

Edit `pynamodb/asyncio/` and `tests/asyncio/`, then run `uv run python scripts/unasync.py`. CI runs `--check`. Generated files start with `# AUTO-GENERATED from <source> by scripts/unasync.py - DO NOT EDIT`.

- Behaviour that cannot be rewritten textually goes in the hand-written pair `pynamodb/_compat.py` (sync) / `pynamodb/asyncio/_compat.py` (async). Async source never does `import asyncio`; the generator aborts on that and on `asyncio.gather` / `create_task` / `wait_for`.
- Async clients (aiobotocore) are shared per (event loop, region, host, credentials, timeouts, retry config, max_pool_connections, extra_headers), reference counted and closed when the last holder closes. Sync keeps one client per model. `Model.close()`, `Connection.close()` and `connections()` exist on both sides.
- All library and generated code uses Python 3.7 syntax only.

### Generated files - DO NOT EDIT

Source -> generated (the `FILES` table in `scripts/unasync.py` is authoritative):

| Async source | Generated |
|---|---|
| `pynamodb/asyncio/pagination.py` | `pynamodb/pagination.py` |
| `pynamodb/asyncio/connection/__init__.py` | `pynamodb/connection/__init__.py` |
| `pynamodb/asyncio/connection/base.py` | `pynamodb/connection/base.py` |
| `pynamodb/asyncio/connection/table.py` | `pynamodb/connection/table.py` |
| `pynamodb/asyncio/models.py` | `pynamodb/models.py` |
| `pynamodb/asyncio/indexes.py` | `pynamodb/indexes.py` |
| `pynamodb/asyncio/transactions.py` | `pynamodb/transactions.py` |
| `tests/asyncio/test_{base_connection,table_connection,signals,pagination,model,transaction}.py` | same names in `tests/sync_generated/` |
| `tests/asyncio/integration/{__init__,conftest,base_integration_test,binary_update_test,model_integration_test,table_integration_test,test_discriminator_index,test_transaction_integration}.py` | same names in `tests/sync_generated/integration/` |

### Test layout

- `tests/asyncio/`: async tests (source; need Python 3.10+). `tests/sync_generated/`: their generated sync twins.
- `tests/test_*.py` and `tests/integration/*.py`: the frozen sync compatibility suite; do not edit for async work.
- Other hand-written tests (`tests/asyncio/test_client_cache.py`, `test_connection_lifecycle.py`, `test_model_close.py`, `tests/test_unasync.py`) are not generated.
