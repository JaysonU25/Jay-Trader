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
    """The background task must not run for real in this test.

    _run builds its own engine; if it executed here, it would (per the
    reviewer's finding) construct an engine against the production database
    URL. Patch _run itself so it is never invoked.
    """
    called = {}

    async def fake_run(job):
        called["job"] = job

    monkeypatch.setattr("marketpulse.api.routes.internal._run", fake_run)
    response = await client.post("/internal/ingest/fx", headers=headers("fx"))
    assert response.status_code == 202
    assert response.json()["job"] == "fx"
    assert called["job"] == "fx"


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


async def test_an_unknown_job_uses_the_structured_error_body(client):
    response = await client.post("/internal/ingest/nope", headers=headers("nope"))
    assert response.json()["detail"] == {
        "error": "not_found", "resource": "job", "id": "nope",
    }


async def test_the_error_body_leaks_nothing(client):
    body = (await client.post("/internal/ingest/fx")).json()
    assert body["detail"] == "unauthorized"


async def test_internal_responses_are_never_cached(client):
    response = await client.post("/internal/ingest/fx")
    assert response.headers["cache-control"] == "no-store"


class _FakeEngine:
    def __init__(self):
        self.disposed = False

    async def dispose(self):
        self.disposed = True


async def test_run_disposes_its_own_engine_after_success(monkeypatch):
    from marketpulse.api.routes.internal import _run

    fake_engine = _FakeEngine()
    called = {}

    def fake_make_engine(url):
        return fake_engine

    async def fake_run_source(job, *, full, session_factory, settings):
        called["job"] = job
        called["full"] = full
        return 1

    monkeypatch.setattr("marketpulse.api.routes.internal.make_engine", fake_make_engine)
    monkeypatch.setattr("marketpulse.api.routes.internal.run_source", fake_run_source)

    await _run("fx")

    assert called["job"] == "fx"
    assert fake_engine.disposed is True


async def test_run_disposes_its_engine_even_when_run_source_raises(monkeypatch):
    from marketpulse.api.routes.internal import _run

    fake_engine = _FakeEngine()

    def fake_make_engine(url):
        return fake_engine

    async def fake_run_source(job, *, full, session_factory, settings):
        raise RuntimeError("boom")

    monkeypatch.setattr("marketpulse.api.routes.internal.make_engine", fake_make_engine)
    monkeypatch.setattr("marketpulse.api.routes.internal.run_source", fake_run_source)

    with pytest.raises(RuntimeError):
        await _run("fx")

    assert fake_engine.disposed is True


async def test_openapi_declares_401_on_the_internal_route(client):
    spec = (await client.get("/openapi.json")).json()
    responses = spec["paths"]["/internal/ingest/{source}"]["post"]["responses"]
    assert "401" in responses
