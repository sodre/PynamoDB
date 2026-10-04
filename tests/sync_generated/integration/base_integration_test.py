# AUTO-GENERATED from tests/asyncio/integration/base_integration_test.py by scripts/unasync.py - DO NOT EDIT
"""
Runs tests against dynamodb
"""
from pynamodb import _compat

from pynamodb.connection import Connection
from pynamodb.constants import PROVISIONED_THROUGHPUT, READ_CAPACITY_UNITS
from pynamodb.expressions.condition import BeginsWith, NotExists
from pynamodb.expressions.operand import Path, Value
from pynamodb.exceptions import TableDoesNotExist
from pynamodb.types import STRING, HASH, RANGE, NUMBER

import pytest


@pytest.fixture
def conn(ddb_url):
    connection = Connection(host=ddb_url)
    yield connection
    connection.close()


@pytest.mark.ddblocal
def test_connection_integration(conn):
    table_name = 'pynamodb-ci-connection'

    # For use with a fake dynamodb connection
    # See: http://aws.amazon.com/dynamodb/developer-resources/

    print(conn)
    print("conn.describe_table...")
    table = None
    try:
        table = conn.describe_table(table_name)
    except TableDoesNotExist:
        params = {
            'read_capacity_units': 1,
            'write_capacity_units': 1,
            'attribute_definitions': [
                {
                    'attribute_type': STRING,
                    'attribute_name': 'Forum'
                },
                {
                    'attribute_type': STRING,
                    'attribute_name': 'Thread'
                },
                {
                    'attribute_type': STRING,
                    'attribute_name': 'AltKey'
                },
                {
                    'attribute_type': NUMBER,
                    'attribute_name': 'number'
                }
            ],
            'key_schema': [
                {
                    'key_type': HASH,
                    'attribute_name': 'Forum'
                },
                {
                    'key_type': RANGE,
                    'attribute_name': 'Thread'
                }
            ],
            'global_secondary_indexes': [
                {
                    'index_name': 'alt-index',
                    'key_schema': [
                        {
                            'KeyType': 'HASH',
                            'AttributeName': 'AltKey'
                        }
                    ],
                    'projection': {
                        'ProjectionType': 'KEYS_ONLY'
                    },
                    'provisioned_throughput': {
                        'ReadCapacityUnits': 1,
                        'WriteCapacityUnits': 1,
                    }
                }
            ],
            'local_secondary_indexes': [
                {
                    'index_name': 'view-index',
                    'key_schema': [
                        {
                            'KeyType': 'HASH',
                            'AttributeName': 'Forum'
                        },
                        {
                            'KeyType': 'RANGE',
                            'AttributeName': 'AltKey'
                        }
                    ],
                    'projection': {
                        'ProjectionType': 'KEYS_ONLY'
                    }
                }
            ]
        }
        print("conn.create_table...")
        conn.create_table(table_name, **params)

    while table is None:
        _compat.sleep(1)
        table = conn.describe_table(table_name)

    while table['TableStatus'] == 'CREATING':
        _compat.sleep(2)
        table = conn.describe_table(table_name)
    print("conn.list_tables")
    conn.list_tables()
    print("conn.update_table...")

    conn.update_table(
        table_name,
        read_capacity_units=table.get(PROVISIONED_THROUGHPUT).get(READ_CAPACITY_UNITS) + 1,
        write_capacity_units=2
    )

    table = conn.describe_table(table_name)

    while table['TableStatus'] != 'ACTIVE':
        _compat.sleep(2)
        table = conn.describe_table(table_name)

    print("conn.put_item")
    conn.put_item(
        table_name,
        'item1-hash',
        range_key='item1-range',
        attributes={'foo': {'S': 'bar'}},
        condition=NotExists(Path('Forum')),
    )
    conn.get_item(
        table_name,
        'item1-hash',
        range_key='item1-range'
    )
    conn.delete_item(
        table_name,
        'item1-hash',
        range_key='item1-range'
    )

    items = []
    for i in range(10):
        items.append(
            {"Forum": "FooForum", "Thread": "thread-{}".format(i)}
        )
    print("conn.batch_write_items...")
    conn.batch_write_item(
        table_name,
        put_items=items
    )
    print("conn.batch_get_items...")
    data = conn.batch_get_item(
        table_name,
        items
    )
    print("conn.query...")
    conn.query(
        table_name,
        "FooForum",
        range_key_condition=(BeginsWith(Path('Thread'), Value('thread'))),
    )
    print("conn.scan...")
    conn.scan(
        table_name,
    )
    print("conn.delete_table...")
    conn.delete_table(table_name)
