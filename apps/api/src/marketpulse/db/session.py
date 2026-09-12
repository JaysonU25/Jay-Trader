from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def _connect_args(url: str) -> dict[str, object]:
    """Settings a pooled Postgres endpoint needs.

    Neon's `-pooler` host (and Supabase's port 6543) is PgBouncer in transaction
    pooling mode: each transaction may land on a different backend connection.
    asyncpg prepares statements by default and caches them per connection, so the
    cached name is missing on the next backend and you get an intermittent
    `prepared statement "__asyncpg_stmt_1__" does not exist`. Disabling the cache
    is the supported fix.
    """
    if "-pooler." in url or ":6543/" in url:
        return {"statement_cache_size": 0, "prepared_statement_cache_size": 0}
    return {}


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args=_connect_args(url),
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
