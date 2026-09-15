"""The scheduler script signs requests the API verifies, so the two must agree.

The script deliberately reimplements signing with the standard library, so the
workflow needs no dependency install. That is a second implementation, and this
module is what stops it drifting: if it does, these fail instead of every
scheduled run quietly 401-ing in production.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from marketpulse.core.security import sign as api_sign
from marketpulse.core.security import verify
from marketpulse.ingest.jobs import JOB_NAMES

_SCRIPT = (
    Path(__file__).resolve().parents[3] / ".github" / "scripts" / "trigger_ingest.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("trigger_ingest", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["trigger_ingest"] = module
    spec.loader.exec_module(module)
    return module


script = _load()


def test_the_script_signs_exactly_as_the_api_verifies():
    signature = script.sign("a-secret", "1757700000", "macro")
    assert signature == api_sign("a-secret", "1757700000", "macro")


def test_a_script_signature_passes_the_api_verifier():
    timestamp = "1757700000"
    signature = script.sign("a-secret", timestamp, "prices")
    # Raises SignatureError if the script and the API disagree.
    verify("a-secret", timestamp, "prices", signature, now=float(timestamp) + 5)


def test_every_api_job_is_reachable_from_some_schedule():
    """A job no schedule fires never runs, and nothing reports it."""
    scheduled = {job for jobs in script.JOBS_BY_SCHEDULE.values() for job in jobs}
    assert scheduled == set(JOB_NAMES)


def test_the_scripts_job_list_matches_the_api():
    assert script.KNOWN_JOBS == set(JOB_NAMES)


def test_no_schedule_fires_the_same_job_twice():
    fired = [job for jobs in script.JOBS_BY_SCHEDULE.values() for job in jobs]
    assert len(fired) == len(set(fired))


def test_an_unmapped_schedule_exits_nonzero_rather_than_silently_doing_nothing():
    code = script.main(
        ["--base-url", "https://x", "--secret", "s", "--schedule", "* * * * *"]
    )
    assert code == 1


@pytest.mark.parametrize("jobs", ["nope", "macro,bogus"])
def test_unknown_job_names_are_rejected_before_any_request(jobs, monkeypatch):
    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("a request was sent for an unknown job")

    monkeypatch.setattr(script, "trigger", explode)
    assert script.main(
        ["--base-url", "https://x", "--secret", "s", "--jobs", jobs]
    ) == 1


def test_all_expands_to_every_known_job(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(
        script, "trigger", lambda base, secret, job, **kw: sent.append(job) or 202
    )

    assert script.main(
        ["--base-url", "https://x", "--secret", "s", "--jobs", "all"]
    ) == 0
    assert sorted(sent) == sorted(JOB_NAMES)


def test_one_failing_job_does_not_stop_the_others(monkeypatch):
    """A single vendor outage must not block the rest of the refresh."""
    attempted: list[str] = []

    def flaky(base, secret, job, **kwargs):
        attempted.append(job)
        return 401 if job == "crypto" else 202

    monkeypatch.setattr(script, "trigger", flaky)

    exit_code = script.main(
        ["--base-url", "https://x", "--secret", "s", "--jobs", "crypto,news"]
    )

    assert attempted == ["crypto", "news"]
    assert exit_code == 1  # surfaced as a red run, but news was still attempted


@pytest.mark.parametrize(
    "argv",
    [
        # An unset ${{ vars.X }} interpolates to "", so these arrive blank.
        ["--base-url", "", "--secret", "s", "--jobs", "macro"],
        ["--base-url", "   ", "--secret", "s", "--jobs", "macro"],
        ["--base-url", "https://x", "--secret", "", "--jobs", "macro"],
        # A hostname with no scheme is the other easy way to misconfigure it.
        ["--base-url", "market-pulse.fly.dev", "--secret", "s", "--jobs", "macro"],
    ],
)
def test_blank_or_schemeless_configuration_is_reported_not_crashed(argv, monkeypatch):
    """Regression: an unset API_BASE_URL used to surface as

        ValueError: unknown url type: '/internal/ingest/crypto'

    from inside urllib, naming neither the variable nor that it was never set.
    """

    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("a request was attempted with bad configuration")

    monkeypatch.setattr(script, "trigger", explode)
    assert script.main(argv) == 1


def test_trigger_builds_the_url_and_headers_the_api_expects(monkeypatch):
    """Exercises trigger() itself, not a stand-in: the URL join and the header
    names are the parts that must match the API, and mocking trigger away would
    test neither."""
    captured = {}

    class _Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["method"] = request.method
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        return _Response()

    monkeypatch.setattr(script.urllib.request, "urlopen", fake_urlopen)

    # Trailing slash on the base must not produce a doubled slash in the path.
    assert script.trigger("https://x/", "a-secret", "macro") == 202

    assert captured["url"] == "https://x/internal/ingest/macro"
    assert captured["method"] == "POST"

    timestamp = captured["headers"]["x-timestamp"]
    assert captured["headers"]["x-signature"] == api_sign("a-secret", timestamp, "macro")
