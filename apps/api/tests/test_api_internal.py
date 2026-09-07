import time

import pytest

from marketpulse.core.security import sign

pytestmark = pytest.mark.asyncio(loop_scope="session")

SECRET = "test-secret"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    """create_app reads settings at construction, so patch before the client."""
    monkeypatch.setenv("INGEST_HMAC_SECRET", SECRET)
    from marketpulse.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def headers(source: str, secret: str = SECRET, ts: str | None = None) -> dict[str, str]:
    stamp = ts or str(int(time.time()))
    return {"X-Timestamp": stamp, "X-Signature": sign(secret, stamp, source)}


async def test_a_valid_signature_is_accepted(client, monkeypatch):
    called = {}

    async def fake_run_source(job, *, full, session_factory, settings):
        called["job"] = job
        return 1

    monkeypatch.setattr("marketpulse.api.routes.internal.run_source", fake_run_source)
    response = await client.post("/internal/ingest/fx", headers=headers("fx"))
    assert response.status_code == 202
    assert response.json()["job"] == "fx"


async def test_a_missing_signature_is_401(client):
    assert (await client.post("/internal/ingest/fx")).status_code == 401


async def test_a_wrong_signature_is_401(client):
    bad = headers("fx", secret="wrong")
    assert (await client.post("/internal/ingest/fx", headers=bad)).status_code == 401


async def test_an_expired_timestamp_is_401(client):
    old = str(int(time.time()) - 400)
    assert (await client.post(
        "/internal/ingest/fx", headers=headers("fx", ts=old))).status_code == 401


async def test_a_signature_for_another_source_is_401(client):
    """A captured fx signature must not trigger the prices job."""
    assert (await client.post(
        "/internal/ingest/prices", headers=headers("fx"))).status_code == 401


async def test_an_unknown_job_is_404(client):
    assert (await client.post(
        "/internal/ingest/nope", headers=headers("nope"))).status_code == 404


async def test_the_error_body_leaks_nothing(client):
    body = (await client.post("/internal/ingest/fx")).json()
    assert body["detail"] == "unauthorized"


async def test_internal_responses_are_never_cached(client):
    response = await client.post("/internal/ingest/fx")
    assert response.headers["cache-control"] == "no-store"
