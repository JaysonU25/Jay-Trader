import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_health_returns_ok(client):
    response = await client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_read_routes_carry_the_edge_cache_header(client):
    response = await client.get("/v1/health")
    assert response.headers["cache-control"] == "public, s-maxage=3600"


async def test_unknown_route_is_404_and_not_cached(client):
    response = await client.get("/v1/nope")
    assert response.status_code == 404
    assert response.headers.get("cache-control") != "public, s-maxage=3600"


async def test_openapi_schema_is_served(client):
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Jay Trader API"
