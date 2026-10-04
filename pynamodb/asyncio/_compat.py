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
