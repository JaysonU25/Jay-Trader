from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# config.py -> marketpulse -> src -> api -> apps -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[4]

# Look for .env beside the package first, then at the repo root. Without the
# second location, running alembic from apps/ api would silently miss a root
# .env and report every field as missing.
_ENV_FILES = (_REPO_ROOT / "apps" / "api" / ".env", _REPO_ROOT / ".env")

_ASYNC_DRIVER = "postgresql+asyncpg"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILES, extra="ignore")

    database_url: str
    alphavantage_api_key: str
    fred_api_key: str
    finnhub_api_key: str
    # Optional: /coins/markets answers anonymously, but /coins/{id}/market_chart
    # returns 401 without a key, which is the whole crypto backfill.
    coingecko_api_key: str | None = None
    ingest_hmac_secret: str
    cors_origins: Annotated[list[str], NoDecode] = []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalise_database_url(cls, value: object) -> object:
        """Accept a Postgres URL as a provider hands it out.

        Neon, Supabase, Railway and Heroku all print a libpq-style URL that
        SQLAlchemy's async stack cannot use unchanged. Two edits are needed and
        both fail confusingly if skipped:

        * `postgresql://` (or `postgres://`) selects the psycopg2 dialect, which
          is not installed, so the failure is `ModuleNotFoundError: psycopg2`
          rather than anything about the URL.
        * `sslmode=` is a libpq parameter. asyncpg does not accept it and rejects
          the connection; its own spelling is `ssl=`.

        Normalising here keeps every call site — the app, the CLI, and alembic —
        working with whatever the provider printed.
        """
        if not isinstance(value, str) or not value.strip():
            return value

        parts = urlsplit(value.strip())

        scheme = parts.scheme
        if scheme in ("postgres", "postgresql"):
            scheme = _ASYNC_DRIVER
        elif scheme.startswith(("postgres+", "postgresql+")):
            # An explicit driver was requested; leave the caller's choice alone.
            pass

        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
        if scheme == _ASYNC_DRIVER:
            rewritten: list[tuple[str, str]] = []
            for key, val in query:
                if key == "sslmode":
                    # libpq's disable/allow/prefer have no asyncpg equivalent;
                    # anything stricter maps onto a plain ssl request.
                    if val in ("disable", "allow", "prefer"):
                        continue
                    rewritten.append(("ssl", "require"))
                elif key in ("channel_binding", "options"):
                    # libpq-only parameters that asyncpg rejects outright.
                    continue
                else:
                    rewritten.append((key, val))
            query = rewritten

        return urlunsplit(
            (scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
