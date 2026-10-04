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
