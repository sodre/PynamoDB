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
