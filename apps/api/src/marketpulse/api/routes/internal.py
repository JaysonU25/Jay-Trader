from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from marketpulse.api.errors import UNAUTHORIZED_RESPONSE, not_found
from marketpulse.config import get_settings
from marketpulse.core.security import SignatureError, verify
from marketpulse.db.session import make_engine, make_session_factory
from marketpulse.ingest.jobs import JOB_NAMES, run_source

router = APIRouter(tags=["internal"])


async def _run(job: str) -> None:
    """Own the engine for the life of the job.

    Background tasks outlive the request, so they cannot borrow the request's
    session — it is closed by then.
    """
    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        await run_source(
            job, full=False,
            session_factory=make_session_factory(engine), settings=settings,
        )
    finally:
        await engine.dispose()


@router.post(
    "/ingest/{source}", status_code=202, responses=UNAUTHORIZED_RESPONSE
)
async def trigger_ingest(
    source: str,
    background: BackgroundTasks,
    x_timestamp: str | None = Header(None),
    x_signature: str | None = Header(None),
):
    if x_timestamp is None or x_signature is None:
        raise HTTPException(status_code=401, detail="unauthorized")

    try:
        verify(get_settings().ingest_hmac_secret, x_timestamp, source, x_signature)
    except SignatureError:
        # Deliberately opaque: never reveal which check failed.
        raise HTTPException(status_code=401, detail="unauthorized") from None

    if source not in JOB_NAMES:
        # Past signature verification, so this path is not security-opaque.
        raise not_found("job", source)

    background.add_task(_run, source)
    return {"accepted": True, "job": source}
