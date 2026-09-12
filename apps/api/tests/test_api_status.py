from datetime import datetime, timedelta, timezone

import pytest

from marketpulse.db.models import IngestRun

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_returns_only_the_latest_run_per_source(client, db_session):
    now = datetime.now(timezone.utc)
    db_session.add_all([
        IngestRun(source="fred", job="macro", status="success",
                  started_at=now - timedelta(hours=2), rows_upserted=10),
        IngestRun(source="fred", job="macro", status="failed",
                  started_at=now, rows_upserted=0, error="boom"),
        IngestRun(source="frankfurter", job="fx", status="success",
                  started_at=now - timedelta(hours=1), rows_upserted=99),
    ])
    await db_session.flush()

    body = (await client.get("/v1/status")).json()
    by_source = {r["source"]: r for r in body}
    assert set(by_source) == {"fred", "frankfurter"}
    assert by_source["fred"]["status"] == "failed"
    assert by_source["fred"]["error"] == "boom"


async def test_no_runs_returns_an_empty_list(client, db_session):
    assert (await client.get("/v1/status")).json() == []
