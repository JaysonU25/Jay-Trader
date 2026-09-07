from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session.

    Replaced at app startup by a factory bound to the real engine, and
    overridden in tests by the transactional fixture session.
    """
    raise RuntimeError("get_session dependency was not configured")
