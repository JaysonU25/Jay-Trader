from marketpulse.config import Settings
from marketpulse import universe


def test_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "av-key")
    monkeypatch.setenv("FRED_API_KEY", "fred-key")
    monkeypatch.setenv("FINNHUB_API_KEY", "fh-key")
    monkeypatch.setenv("INGEST_HMAC_SECRET", "secret")

    settings = Settings()

    assert settings.database_url == "postgresql+asyncpg://u:p@localhost/db"
    assert settings.alphavantage_api_key == "av-key"
    assert settings.cors_origins == []


def test_cors_origins_parsed_from_comma_separated_string(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "av-key")
    monkeypatch.setenv("FRED_API_KEY", "fred-key")
    monkeypatch.setenv("FINNHUB_API_KEY", "fh-key")
    monkeypatch.setenv("INGEST_HMAC_SECRET", "secret")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.dev,https://b.dev")

    assert Settings().cors_origins == ["https://a.dev", "https://b.dev"]


def test_universe_matches_spec():
    assert len(universe.EQUITIES) == 15
    assert "SPY" in universe.EQUITIES
    assert len(universe.FRED_SERIES) == 15
    assert "CPIAUCSL" in universe.FRED_SERIES
    assert universe.CRYPTO_LIMIT == 20
    assert universe.FX_BASE == "EUR"
