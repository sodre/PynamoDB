# AUTO-GENERATED from tests/asyncio/integration/conftest.py by scripts/unasync.py - DO NOT EDIT
import os

import pytest

from pynamodb import connections


@pytest.fixture(scope='module')
def ddb_url():
    """Obtain the URL of a local DynamoDB instance.

    This is meant to be used with something like DynamoDB Local:

      http://docs.aws.amazon.com/amazondynamodb/latest/developerguide/DynamoDBLocal.html

    It must be set up "out of band"; we merely assume it exists on
    http://localhost:8000 or a URL specified though the
    PYNAMODB_INTEGRATION_TEST_DDB_URL environment variable.
    """
    ddb_url = os.getenv("PYNAMODB_INTEGRATION_TEST_DDB_URL")
    return "http://localhost:8000" if ddb_url is None else ddb_url


@pytest.fixture(autouse=True)
def close_connections():
    """Closes every client a test opened, so no aiohttp session outlives its test."""
    with connections():
        yield
