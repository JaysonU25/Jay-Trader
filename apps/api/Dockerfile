# syntax=docker/dockerfile:1

# Pinned to 3.12 to match .python-version and pyproject's requires-python.
FROM python:3.12-slim AS base

# uv is the same resolver used locally, so the image installs from uv.lock
# rather than re-resolving and drifting from what the tests ran against.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first, as their own layer: application edits should not
# reinstall the whole dependency tree on every build.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY alembic.ini ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

EXPOSE 8080

# One worker on purpose. The token buckets in core/ratelimit live in process
# memory, so a second worker would hold a second set and the Alpha Vantage
# 25/day cap could be spent twice over. Scaling past one instance needs shared
# rate-limit state first.
CMD ["uvicorn", "marketpulse.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
