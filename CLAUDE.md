# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PynamoDB is a Pythonic ODM (object-document mapper) for Amazon DynamoDB, built directly on `botocore` (not `boto3`). Supports Python 3.7+; the only runtime deps are `botocore` and `typing-extensions` (`blinker` is the optional `signals` extra).

## Commands

Setup (the repo uses plain pip/setuptools; with uv):

```bash
uv venv && uv pip install -e '.[signals]' -r requirements-dev.txt
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

Type checking (CI runs this on Python 3.8 with pinned `mypy==1.2.0`):

```bash
uv run mypy .
```

`typing_tests/` is not run by pytest — it is checked by mypy only (uses `assert_type` to verify the public API's type signatures). `tests.*` has mypy errors ignored.

Docs (Sphinx, warnings are errors in CI):

```bash
uv pip install -r docs/requirements.txt && uv run sphinx-build -W docs /tmp/docs-build
```

## Architecture

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
