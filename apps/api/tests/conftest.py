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
    session = AsyncSession(bind=connection, expire_on_commit=False)
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
