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


def _spent(calls_used: Callable[[], int] | None) -> int:
    """Ask the caller how many API calls were actually spent.

    The reporter is invoked on the failure path too, where it may run before
    the client even exists (the job blew up while building it), so anything
    unusable counts as zero rather than propagating a second exception.
    """
    if calls_used is None:
        return 0
    try:
        return int(calls_used() or 0)
    except Exception:
        return 0


async def run_job(
    session_factory,
    source: str,
    job: str,
    fn: Callable[[AsyncSession], Awaitable[JobResult]],
    calls_used: Callable[[], int] | None = None,
) -> int:
    """Run one ingest job and record exactly one `ingest_run` audit row.

    `calls_used` lets the caller report the vendor requests actually spent.
    `fn` closes over the client, so on the failure path there is no JobResult
    to read the count from -- and losing it would make `calls_used_today`
    under-report, which reseeds the next process's token bucket too low and
    lets identical retries drain a non-renewable daily quota.
    """
    started_at = datetime.now(timezone.utc)
    async with session_factory() as session:
        run = IngestRun(source=source, job=job, status="running",
                        started_at=started_at)
        session.add(run)
        await session.flush()

        try:
            result = await fn(session)

            run.rows_upserted = result.rows_upserted
            run.api_calls_used = result.api_calls_used
            run.error = "; ".join(result.errors)[:2000] if result.errors else None
            run.status = "partial" if result.errors else "success"
            run.finished_at = datetime.now(timezone.utc)
            await session.flush()
            await session.commit()
            return run.id
        except Exception as exc:
            # A server-side database error leaves the transaction aborted, so
            # any UPDATE here would raise InFailedSQLTransactionError and mask
            # the real cause -- and the audit row, inserted in that same dead
            # transaction, would never commit. Roll back first, then write a
            # fresh failure row on a clean transaction, then re-raise the
            # ORIGINAL exception so the operator sees the real cause.
            try:
                await session.rollback()
                session.add(IngestRun(
                    source=source,
                    job=job,
                    status="failed",
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    rows_upserted=0,
                    api_calls_used=_spent(calls_used),
                    error=str(exc)[:2000],
                ))
                await session.commit()
            except Exception as audit_exc:
                # Even the audit write failed (the connection is gone, say).
                # The original failure is still the one the operator needs, so
                # re-raise that and hang this off it rather than replacing it.
                exc.add_note(f"ingest_run audit row could not be written: {audit_exc!r}")
            raise
