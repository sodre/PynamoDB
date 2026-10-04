"""
An async example using Amazon's Thread example for motivation

http://docs.aws.amazon.com/amazondynamodb/latest/developerguide/SampleTablesAndData.html

Requires DynamoDB Local on localhost:8000 and ``pip install pynamodb[asyncio]``.
"""
import asyncio
import logging
from datetime import datetime

import pynamodb.asyncio
from pynamodb.asyncio.models import Model
from pynamodb.attributes import (
    ListAttribute, UnicodeAttribute, NumberAttribute, UnicodeSetAttribute, UTCDateTimeAttribute
)

logging.basicConfig()
log = logging.getLogger("pynamodb")
log.setLevel(logging.INFO)
log.propagate = True


class Thread(Model):
    class Meta:
        read_capacity_units = 1
        write_capacity_units = 1
        table_name = "AsyncThread"
        host = "http://localhost:8000"
    forum_name = UnicodeAttribute(hash_key=True)
    subject = UnicodeAttribute(range_key=True)
    views = NumberAttribute(default=0)
    replies = NumberAttribute(default=0)
    answered = NumberAttribute(default=0)
    tags = UnicodeSetAttribute()
    last_post_datetime = UTCDateTimeAttribute(null=True)
    notes = ListAttribute(default=list)  # type: ignore


async def main() -> None:
    # Closes every client opened inside the block when it exits
    async with pynamodb.asyncio.connections():
        # Create the table
        if not await Thread.exists():
            await Thread.create_table(wait=True)

        try:
            # Create and save a thread
            thread_item = Thread(
                'Some Forum',
                'Some Subject',
                tags=['foo', 'bar'],
                last_post_datetime=datetime.now()
            )
            await thread_item.save()

            # Get it back
            thread = await Thread.get('Some Forum', 'Some Subject')
            print("Got: {0}".format(thread.subject))

            # Batch write operation
            async with Thread.batch_write() as batch:
                for x in range(100):
                    thread = Thread('forum-{0}'.format(x), 'subject-{0}'.format(x))
                    thread.tags = {'tag1', 'tag2'}
                    thread.last_post_datetime = datetime.now()
                    await batch.save(thread)

            # Get table count
            print(await Thread.count())

            # Query
            async for item in Thread.query('forum-1', Thread.subject.startswith('subject')):
                print("Query result: {0}".format(item))

            # Update, then delete an item
            await thread_item.update(actions=[Thread.views.add(1)])
            await thread_item.delete()
        finally:
            # Delete the table
            await Thread.delete_table()


if __name__ == "__main__":
    asyncio.run(main())
