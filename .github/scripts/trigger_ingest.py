#!/usr/bin/env python3
"""Fire ingest jobs at the API over HMAC-signed HTTP.

Standard library only, on purpose: the workflow then needs no dependency
install step, so a trigger is a checkout and one `python` call.

The signing here must stay byte-identical to marketpulse.core.security.sign,
which is what the API verifies with. apps/api/tests/test_trigger_script.py
cross-checks the two implementations so drift fails a test instead of quietly
401-ing every scheduled run.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import sys
import time
import urllib.error
import urllib.request

# Cron expression -> the jobs it fires. GitHub passes the matched expression as
# github.event.schedule, so this is how one workflow serves several schedules.
#
# Unlike a Cloudflare trigger, a schedule may fire several jobs, so there is no
# need to give two jobs artificially different times just to tell them apart.
JOBS_BY_SCHEDULE: dict[str, tuple[str, ...]] = {
    "15 13 * * *": ("macro",),        # after the 08:30 ET FRED releases
    "30 15 * * 1-5": ("fx",),         # after the ECB publishes, ~15:00 UTC
    "0 22 * * 1-5": ("prices",),      # after the US close, 21:00 UTC
    "0 */6 * * *": ("crypto", "news"),
    "0 23 * * *": ("earnings",),
    "0 4 * * 1": ("ratings",),        # weekly; analyst ratings barely move
}

# JOB_NAMES in marketpulse/ingest/jobs.py. Anything else 404s at the API.
KNOWN_JOBS = frozenset(
    {"prices", "macro", "crypto", "news", "earnings", "ratings", "fx"}
)


def sign(secret: str, timestamp: str, job: str) -> str:
    """HMAC-SHA256 over `{timestamp}.{job}`, hex encoded."""
    message = f"{timestamp}.{job}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def jobs_for(schedule: str) -> tuple[str, ...]:
    """Jobs a cron expression should fire, or () if it maps to nothing."""
    return JOBS_BY_SCHEDULE.get(schedule.strip(), ())


def trigger(base_url: str, secret: str, job: str, *, timeout: float = 30.0) -> int:
    """POST one signed trigger. Returns the HTTP status."""
    timestamp = str(int(time.time()))
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/internal/ingest/{job}",
        method="POST",
        data=b"",
        headers={
            "X-Timestamp": timestamp,
            "X-Signature": sign(secret, timestamp, job),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        # Print the body, not just the status: a 401 here is almost always a
        # secret mismatch, and the status alone sends you looking at the URL.
        body = error.read().decode("utf-8", "replace")[:300]
        print(f"  {job}: HTTP {error.code} {body}", file=sys.stderr)
        return error.code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--secret", required=True)
    parser.add_argument(
        "--schedule",
        default="",
        help="Cron expression that fired, from github.event.schedule.",
    )
    parser.add_argument(
        "--jobs",
        default="",
        help="Comma-separated job names. Overrides --schedule; used by manual runs.",
    )
    args = parser.parse_args(argv)

    if args.jobs.strip():
        requested = tuple(j.strip() for j in args.jobs.split(",") if j.strip())
        if requested == ("all",):
            requested = tuple(sorted(KNOWN_JOBS))
    else:
        requested = jobs_for(args.schedule)

    if not requested:
        print(
            f"no jobs for schedule {args.schedule!r}; nothing to do",
            file=sys.stderr,
        )
        return 1

    unknown = [job for job in requested if job not in KNOWN_JOBS]
    if unknown:
        print(f"unknown jobs: {', '.join(unknown)}", file=sys.stderr)
        return 1

    failures = 0
    for job in requested:
        status = trigger(args.base_url, args.secret, job)
        if status == 202:
            print(f"  {job}: accepted")
        else:
            failures += 1

    # Every job is attempted before giving up: one vendor's outage should not
    # stop the others from refreshing.
    print(f"{len(requested) - failures}/{len(requested)} accepted")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
