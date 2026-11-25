from alembic import context

from support_demo.asyncio_support import run as run_async
from support_demo.db import Base, engine


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def online():
    async with engine.connect() as connection:
        await connection.run_sync(run)
    await engine.dispose()


run_async(online())
