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
FILES: List[Tuple[str, str]] = [
    ("pynamodb/asyncio/pagination.py", "pynamodb/pagination.py"),
    ("pynamodb/asyncio/connection/__init__.py", "pynamodb/connection/__init__.py"),
    ("pynamodb/asyncio/connection/base.py", "pynamodb/connection/base.py"),
    ("pynamodb/asyncio/connection/table.py", "pynamodb/connection/table.py"),
    ("pynamodb/asyncio/models.py", "pynamodb/models.py"),
    ("pynamodb/asyncio/indexes.py", "pynamodb/indexes.py"),
    ("pynamodb/asyncio/transactions.py", "pynamodb/transactions.py"),
    ("tests/asyncio/test_base_connection.py", "tests/sync_generated/test_base_connection.py"),
    ("tests/asyncio/test_table_connection.py", "tests/sync_generated/test_table_connection.py"),
    ("tests/asyncio/test_signals.py", "tests/sync_generated/test_signals.py"),
    ("tests/asyncio/test_pagination.py", "tests/sync_generated/test_pagination.py"),
    ("tests/asyncio/test_model.py", "tests/sync_generated/test_model.py"),
    ("tests/asyncio/test_transaction.py", "tests/sync_generated/test_transaction.py"),
    ("tests/asyncio/integration/__init__.py", "tests/sync_generated/integration/__init__.py"),
    ("tests/asyncio/integration/conftest.py", "tests/sync_generated/integration/conftest.py"),
    ("tests/asyncio/integration/base_integration_test.py", "tests/sync_generated/integration/base_integration_test.py"),
    ("tests/asyncio/integration/binary_update_test.py", "tests/sync_generated/integration/binary_update_test.py"),
    ("tests/asyncio/integration/model_integration_test.py", "tests/sync_generated/integration/model_integration_test.py"),
    ("tests/asyncio/integration/table_integration_test.py", "tests/sync_generated/integration/table_integration_test.py"),
    ("tests/asyncio/integration/test_discriminator_index.py", "tests/sync_generated/integration/test_discriminator_index.py"),
    ("tests/asyncio/integration/test_transaction_integration.py", "tests/sync_generated/integration/test_transaction_integration.py"),
]

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
        # (await f(a)).x -> f(a).x. Only fires on a grouping paren (not after a name or
        # closing bracket, so `len(await f())` is untouched). Known limits: nested calls
        # `(await f(g(a))).y` and non-call operands `(await self.a).b` stay parenthesised,
        # which is still valid.
        (r"(?<![\w\])])\(await (\w[\w.]*\([^()]*\))\)", r"\1"),
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
        (r"\baiobotocore\.httpsession\.AIOHTTPSession\b", "botocore.httpsession.URLLib3Session"),
        (r"\baiobotocore\.awsrequest\b", "botocore.awsrequest"),
        (r"\bAioAWSResponse\b", "AWSResponse"),
        (r"\bIsolatedAsyncioTestCase\b", "TestCase"),
        (r"\bAsyncMock\b", "MagicMock"),
        # MagicMock has no await assertions; the sync twin checks the call instead.
        (r"\.assert_awaited_once_with\(", ".assert_called_once_with("),
        (r"\.assert_awaited_once\(", ".assert_called_once("),
        (r"\banext\(", "next("),
        (r"\b_compat\.alist\(", "list("),
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
