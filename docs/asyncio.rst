.. _asyncio:

Async Support
=============

PynamoDB has an async API, ``pynamodb.asyncio``, built on
`aiobotocore <https://aiobotocore.readthedocs.io/>`_. It mirrors the sync API: the same
models, attributes and conditions, with ``await``, ``async for`` and ``async with`` where
the sync API does I/O.

Installing
----------

.. code-block:: bash

    $ pip install pynamodb[asyncio]

The async API requires Python 3.10 or later. The ``asyncio`` extra installs ``aiobotocore``
(``>=2.13.0``), which pins its own range of ``botocore``. Without the extra,
``import pynamodb.asyncio`` raises an :py:class:`ImportError` that names it.
The sync API is unaffected.

Usage
-----

Import ``Model`` from ``pynamodb.asyncio.models``. Attributes are the same ones you use in
the sync API.

.. code-block:: python

    from pynamodb.asyncio.models import Model
    from pynamodb.attributes import UnicodeAttribute, NumberAttribute

    class User(Model):
        class Meta:
            table_name = "user"
            region = "us-east-1"

        email = UnicodeAttribute(hash_key=True)
        name = UnicodeAttribute()
        age = NumberAttribute(null=True)

Operations that do I/O are awaited; building models, attributes and conditions is not.

.. list-table::
   :header-rows: 1
   :widths: 15 60 25

   * - Area
     - Async
     - Sync
   * - Item ops
     - ``await item.save()``, ``update()``, ``delete()``, ``refresh()``; ``await User.get(key)``
     - no ``await``
   * - Table ops
     - ``await User.create_table()``, ``delete_table()``, ``describe_table()``, ``exists()``, ``update_ttl()``
     - no ``await``
   * - Count
     - ``await User.count(...)``
     - no ``await``
   * - Query / scan
     - ``async for u in User.query(...)`` (the call itself is not awaited)
     - ``for``
   * - Paging
     - ``.last_evaluated_key``, ``.total_count``, ``await it.next()``
     - ``it.next()``
   * - Batch get
     - ``async for u in User.batch_get(keys)``
     - ``for``
   * - Batch write
     - ``async with User.batch_write() as b:`` then ``await b.save(x)`` / ``await b.delete(x)``
     - ``with``, no ``await``
   * - Transactions
     - ``async with TransactWrite() as t:`` then ``t.save(x)`` (no ``await`` inside)
     - ``with``
   * - Transact get
     - ``async with TransactGet() as t:``, ``f = t.get(...)``, then ``f.get()`` after the block
     - ``with``
   * - No I/O
     - constructors, attributes, conditions, ``serialize``, ``from_raw_data``
     - same

Get and save:

.. code-block:: python

    await User.create_table(read_capacity_units=1, write_capacity_units=1, wait=True)

    user = User("ada@example.com", name="Ada", age=36)
    await user.save()

    user = await User.get("ada@example.com")

Query (note that ``query`` is not awaited; you iterate over it):

.. code-block:: python

    async for user in User.query("ada@example.com", User.name.startswith("A")):
        print(user.name)

Batch write:

.. code-block:: python

    async with User.batch_write() as batch:
        for i in range(100):
            await batch.save(User(f"user{i}@example.com", name=f"User {i}"))

Transactions. Operations are only collected inside the block and sent when it exits:

.. code-block:: python

    from pynamodb.asyncio.connection import Connection
    from pynamodb.asyncio.transactions import TransactGet, TransactWrite

    connection = Connection()

    async with TransactWrite(connection=connection) as transaction:
        transaction.save(User("grace@example.com", name="Grace"))
        transaction.delete(user)

    async with TransactGet(connection=connection) as transaction:
        future = transaction.get(User, "grace@example.com")
    grace = future.get()

See :doc:`transaction` for what each transaction operation does.

Closing clients
---------------

Every async client holds an HTTP session. Close it when you are done, or Python warns about
unclosed sessions:

.. code-block:: python

    await User.close()

Or close every connection that was opened inside a block:

.. code-block:: python

    import pynamodb.asyncio

    async with pynamodb.asyncio.connections():
        ...  # use your models here

The sync API has the same calls, for symmetry: ``Model.close()``,
``Connection.close()``, ``TableConnection.close()`` and ``pynamodb.connections()``.

Shared clients
--------------

Async clients are shared. Models with identical settings on the same event loop use one
client. The settings that count are region, host, credentials, timeouts, retry configuration,
``max_pool_connections`` and ``extra_headers``; a model that differs in any of them gets its
own client.

Sharing is reference counted: the client is closed when the last model or connection using it
closes. The sync API keeps one client per model.

Event loops
-----------

An async client belongs to the event loop that created it. If your program runs a second
event loop (for example, a second call to :py:func:`asyncio.run`), models get a new client on
the new loop, and entries for finished loops are dropped. Prefer one long-lived event loop
for the whole program.

Low-level connections
---------------------

``pynamodb.asyncio.connection.Connection`` is the async counterpart of
:doc:`low_level`. The botocore client is opened on first use. To open it yourself:

.. code-block:: python

    from pynamodb.asyncio.connection import Connection

    conn = Connection()
    client = await conn.get_client()
    ...
    await conn.close()

The ``conn.client`` property raises :py:class:`RuntimeError` until the client has been opened,
either with ``await conn.get_client()`` or by awaiting any operation. ``repr(conn)`` never
raises.

Not yet supported
-----------------

PynamoDB does not send requests concurrently on its own: there is no parallel scan, and
batch pages are fetched one after another. You can run independent operations concurrently
yourself:

.. code-block:: python

    import asyncio

    alice, bob = await asyncio.gather(User.get("alice@example.com"), User.get("bob@example.com"))
