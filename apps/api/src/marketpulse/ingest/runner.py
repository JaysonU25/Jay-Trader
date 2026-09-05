from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.db.models import IngestRun


@dataclass
class JobResult:
    rows_upserted: int = 0
    api_calls_used: int = 0
    errors: list[str] = field(default_factory=list)


async def calls_used_today(session: AsyncSession, source: str) -> int:
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    statement = (
        select(func.coalesce(func.sum(IngestRun.api_calls_used), 0))
        .where(IngestRun.source == source)
        .where(IngestRun.started_at >= day_start)
        .where(IngestRun.started_at < day_end)
    )
    return int((await session.execute(statement)).scalar_one())


async def run_job(
    session_factory,
    source: str,
    job: str,
    fn: Callable[[AsyncSession], Awaitable[JobResult]],
) -> int:
    async with session_factory() as session:
        run = IngestRun(source=source, job=job, status="running",
                        started_at=datetime.now(timezone.utc))
        session.add(run)
        await session.flush()

        try:
            result = await fn(session)
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)[:2000]
            run.finished_at = datetime.now(timezone.utc)
            await session.flush()
            await session.commit()
            raise

        run.rows_upserted = result.rows_upserted
        run.api_calls_used = result.api_calls_used
        run.error = "; ".join(result.errors)[:2000] if result.errors else None
        run.status = "partial" if result.errors else "success"
        run.finished_at = datetime.now(timezone.utc)
        await session.flush()
        await session.commit()
        return run.id
