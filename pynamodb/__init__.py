"""
PynamoDB Library
^^^^^^^^^^^^^^^^

A simple abstraction over DynamoDB

"""
__author__ = 'Jharrod LaFon'
__license__ = 'MIT'
__version__ = '6.1.0'


def connections():
    """
    Context manager that closes every open PynamoDB connection on exit.
    See also ``pynamodb.asyncio.connections`` for the async API.
    """
    from pynamodb.connection.base import connections as _connections
    return _connections()
