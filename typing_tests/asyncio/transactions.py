from typing_extensions import assert_type


async def test_transact_write() -> None:
    from pynamodb.asyncio.transactions import TransactWrite
    async with TransactWrite() as tx:
        assert_type(tx, TransactWrite)


async def test_transact_get() -> None:
    from pynamodb.asyncio.transactions import TransactGet
    from pynamodb.asyncio.models import Model, _ModelFuture

    class FirstModel(Model):
        pass

    class SecondModel(Model):
        pass

    async with TransactGet() as tx:
        assert_type(tx, TransactGet)
        assert_type(tx.get(FirstModel, "pk"), _ModelFuture[FirstModel])
        assert_type(tx.get(SecondModel, "pk"), _ModelFuture[SecondModel])

        second_model_instance_future = tx.get(SecondModel, "pk")

    assert_type(second_model_instance_future.get(), SecondModel)
    _first_model_instance: FirstModel = second_model_instance_future.get()  # type:ignore[assignment]
