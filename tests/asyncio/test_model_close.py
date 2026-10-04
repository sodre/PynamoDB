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
