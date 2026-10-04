"""
PynamoDB lowest level connection
"""

from pynamodb.asyncio.connection.base import Connection
from pynamodb.asyncio.connection.table import TableConnection


__all__ = [
    "Connection",
    "TableConnection",
]
