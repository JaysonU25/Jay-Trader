from pathlib import Path

import pytest
from pydantic import ValidationError

from marketpulse.config import Settings
from marketpulse import universe


def test_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "av-key")
    monkeypatch.setenv("FRED_API_KEY", "fred-key")
    monkeypatch.setenv("FINNHUB_API_KEY", "fh-key")
    monkeypatch.setenv("INGEST_HMAC_SECRET", "secret")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example")

    settings = Settings()

    assert settings.database_url == "postgresql+asyncpg://u:p@localhost/db"
    assert settings.alphavantage_api_key == "av-key"
    assert settings.cors_origins == ["https://app.example"]


def test_cors_origins_parsed_from_comma_separated_string(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "av-key")
    monkeypatch.setenv("FRED_API_KEY", "fred-key")
    monkeypatch.setenv("FINNHUB_API_KEY", "fh-key")
    monkeypatch.setenv("INGEST_HMAC_SECRET", "secret")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.dev,https://b.dev")

    assert Settings().cors_origins == ["https://a.dev", "https://b.dev"]


def test_missing_cors_origins_fails_at_startup(monkeypatch):
    """CORS_ORIGINS has no default on purpose.

    An empty allow-list is not a safe fallback: every browser request is
    rejected while curl and every server-side health check still pass, so the
    frontend fails with an opaque "Failed to fetch" and nothing server-side
    reports a problem. Failing to boot is the louder, cheaper failure.
    """
    for key in ("DATABASE_URL", "ALPHAVANTAGE_API_KEY", "FRED_API_KEY",
                "FINNHUB_API_KEY", "INGEST_HMAC_SECRET"):
        monkeypatch.setenv(key, "x")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    # _env_file=None so the repo's own .env cannot satisfy the field and hide
    # the very misconfiguration this test is about.
    with pytest.raises(ValidationError, match="cors_origins"):
        Settings(_env_file=None)


def test_universe_matches_spec():
    assert len(universe.EQUITIES) == 15
    assert "SPY" in universe.EQUITIES
    assert len(universe.FRED_SERIES) == 15
    assert "CPIAUCSL" in universe.FRED_SERIES
    assert universe.CRYPTO_LIMIT == 20
    assert universe.FX_BASE == "EUR"


def test_env_file_discovery_survives_a_shallow_install_path():
    """The container installs the package at /app/src/marketpulse, which has
    fewer ancestors than a source checkout. Indexing a fixed depth there raises
    IndexError while config.py is being imported, so the app dies at startup
    with a traceback that never mentions configuration.
    """
    from pathlib import PurePosixPath

    from marketpulse.config import _env_files

    shallow = PurePosixPath("/app/src/marketpulse/config.py")
    assert len(shallow.parents) == 4  # guards the premise of this test

    files = _env_files(Path("/app/src/marketpulse/config.py"))

    assert all(isinstance(f, Path) for f in files)
    assert len(files) == 1  # apps/api depth only; repo-root depth does not exist


def test_env_file_discovery_finds_both_locations_in_a_checkout():
    from marketpulse.config import _env_files

    files = _env_files(Path("/repo/apps/api/src/marketpulse/config.py"))

    # Compared as posix suffixes: resolve() prepends a drive letter on Windows,
    # so absolute equality would assert the host OS rather than the behaviour.
    suffixes = [f.as_posix() for f in files]
    assert len(suffixes) == 2
    assert suffixes[0].endswith("/repo/apps/api/.env")
    assert suffixes[1].endswith("/repo/.env")
