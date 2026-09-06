import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.db.models import Base
from marketpulse.db.session import make_engine

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://marketpulse:marketpulse@localhost:5433/marketpulse_test",
)


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    engine = make_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    connection = await db_engine.connect()
    transaction = await connection.begin()
    # create_savepoint, not the default conditional_savepoint: run_job's
    # failure path calls session.rollback() before writing its audit row, and
    # under the default that rollback tears down this fixture's own outer
    # transaction, letting the follow-up commit leak rows into the shared test
    # database. Pinning the session to a SAVEPOINT keeps rollback/commit inside
    # it so the outer transaction still cleans up. (SQLAlchemy's documented
    # recipe for "joining an external transaction" when the code under test
    # manages transactions itself.)
    session = AsyncSession(bind=connection, expire_on_commit=False,
                           join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest.fixture
def fixture_path():
    from pathlib import Path
    return Path(__file__).parent / "fixtures"
