"""The URL a hosted Postgres provider prints is not the URL SQLAlchemy's async
stack can use. These tests pin the translation, because every failure mode here
surfaces as something that does not mention the URL at all — a missing psycopg2
module, or an intermittent prepared-statement error.
"""

import pytest

from marketpulse.config import Settings
from marketpulse.db.session import _connect_args

REQUIRED = {
    "ALPHAVANTAGE_API_KEY": "av",
    "FRED_API_KEY": "fred",
    "FINNHUB_API_KEY": "fh",
    "INGEST_HMAC_SECRET": "secret",
}


def build(monkeypatch, url: str) -> Settings:
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DATABASE_URL", url)
    return Settings()


def test_plain_postgresql_scheme_gets_the_asyncpg_driver(monkeypatch):
    """Without this, SQLAlchemy loads psycopg2 and raises ModuleNotFoundError."""
    settings = build(monkeypatch, "postgresql://u:p@host/db")
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_heroku_style_postgres_scheme_is_also_upgraded(monkeypatch):
    settings = build(monkeypatch, "postgres://u:p@host/db")
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_an_explicit_driver_is_left_alone(monkeypatch):
    """A caller who named a driver meant it."""
    settings = build(monkeypatch, "postgresql+psycopg://u:p@host/db")
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_sslmode_is_rewritten_to_the_asyncpg_spelling(monkeypatch):
    """asyncpg rejects libpq's sslmode outright."""
    settings = build(monkeypatch, "postgresql://u:p@host/db?sslmode=require")
    assert "sslmode=" not in settings.database_url
    assert "ssl=require" in settings.database_url


@pytest.mark.parametrize("mode", ["verify-ca", "verify-full", "require"])
def test_strict_sslmodes_all_map_to_ssl_require(monkeypatch, mode):
    settings = build(monkeypatch, f"postgresql://u:p@host/db?sslmode={mode}")
    assert "ssl=require" in settings.database_url


@pytest.mark.parametrize("mode", ["disable", "allow", "prefer"])
def test_permissive_sslmodes_are_dropped_rather_than_forced(monkeypatch, mode):
    """These have no asyncpg equivalent; forcing ssl=require would change intent."""
    settings = build(monkeypatch, f"postgresql://u:p@host/db?sslmode={mode}")
    assert "ssl" not in settings.database_url


def test_libpq_only_parameters_are_stripped(monkeypatch):
    """Neon appends channel_binding; asyncpg rejects it."""
    settings = build(
        monkeypatch, "postgresql://u:p@host/db?sslmode=require&channel_binding=require"
    )
    assert "channel_binding" not in settings.database_url


def test_unrelated_query_parameters_survive(monkeypatch):
    settings = build(
        monkeypatch, "postgresql://u:p@host/db?sslmode=require&application_name=mp"
    )
    assert "application_name=mp" in settings.database_url


def test_credentials_and_host_are_preserved(monkeypatch):
    settings = build(
        monkeypatch,
        "postgresql://user:pa55@ep-x-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require",
    )
    assert "user:pa55@ep-x-pooler.us-east-2.aws.neon.tech" in settings.database_url
    assert settings.database_url.endswith("/neondb?ssl=require")


def test_a_real_neon_url_becomes_directly_usable(monkeypatch):
    """The exact shape Neon's dashboard prints."""
    settings = build(
        monkeypatch,
        "postgresql://neondb_owner:npg_x@ep-cool-lake-123456-pooler.c-2.us-east-2"
        ".aws.neon.tech/neondb?sslmode=require&channel_binding=require",
    )
    assert settings.database_url == (
        "postgresql+asyncpg://neondb_owner:npg_x@ep-cool-lake-123456-pooler.c-2"
        ".us-east-2.aws.neon.tech/neondb?ssl=require"
    )


def test_local_url_is_untouched(monkeypatch):
    url = "postgresql+asyncpg://marketpulse:marketpulse@localhost:5433/marketpulse_test"
    assert build(monkeypatch, url).database_url == url


# --- pooled-endpoint connect args -------------------------------------------------


def test_pooled_neon_endpoint_disables_the_statement_cache():
    """PgBouncer transaction pooling breaks asyncpg's per-connection cache."""
    args = _connect_args("postgresql+asyncpg://u:p@ep-x-pooler.aws.neon.tech/db")
    assert args["statement_cache_size"] == 0


def test_supabase_pooler_port_is_also_detected():
    args = _connect_args("postgresql+asyncpg://u:p@db.abc.supabase.co:6543/postgres")
    assert args["statement_cache_size"] == 0


def test_direct_endpoint_keeps_the_statement_cache():
    """Prepared statements are a real speedup; only disable them when forced to."""
    assert _connect_args("postgresql+asyncpg://u:p@ep-x.aws.neon.tech/db") == {}


def test_local_database_keeps_the_statement_cache():
    assert _connect_args("postgresql+asyncpg://u:p@localhost:5433/db") == {}
