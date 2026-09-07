from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.api.deps import get_session
from marketpulse.api.schemas import IngestRunOut
from marketpulse.db.models import IngestRun

router = APIRouter(tags=["meta"])


@router.get("/status", response_model=list[IngestRunOut])
async def status(session: AsyncSession = Depends(get_session)):
    """Most recent run per source — what the Pipeline view renders."""
    rows = await session.execute(
        select(IngestRun)
        .distinct(IngestRun.source)
        .order_by(IngestRun.source, IngestRun.started_at.desc())
    )
    return rows.scalars().all()
