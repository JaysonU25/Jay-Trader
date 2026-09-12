from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# In a source checkout this module sits at
#   <repo root>/apps/api/src/marketpulse/config.py
# so parents[2] is apps/api and parents[4] is the repo root.
_APPS_API_DEPTH = 2
_REPO_ROOT_DEPTH = 4


def _env_files(module_path: Path | None = None) -> tuple[Path, ...]:
    """`.env` locations to read, lowest priority first.

    Look beside the package first, then at the repo root; without the second,
    running alembic from apps/api would miss a root .env and report every field
    as missing.

    The depths are bounds-checked rather than indexed directly. In the
    container the package is installed at /app/src/marketpulse, which has only
    four ancestors, so a bare parents[4] raises IndexError while this module is
    being imported — the app dies at startup with a traceback that never
    mentions configuration. There is no .env in the image at all (secrets
    arrive as real environment variables), so returning fewer paths there is
    correct, not a fallback.
    """
    parents = (module_path or Path(__file__)).resolve().parents
    return tuple(
        parents[depth] / ".env"
        for depth in (_APPS_API_DEPTH, _REPO_ROOT_DEPTH)
        if depth < len(parents)
    )


_ENV_FILES = _env_files()

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
    cors_origins: Annotated[list[str], NoDecode] 

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
