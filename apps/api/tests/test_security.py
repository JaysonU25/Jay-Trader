import pytest

from marketpulse.core.security import SignatureError, sign, verify

SECRET = "topsecret"


def test_a_freshly_signed_request_verifies():
    ts = "1000"
    verify(SECRET, ts, "fred", sign(SECRET, ts, "fred"), now=1000.0)


def test_a_wrong_signature_is_rejected():
    with pytest.raises(SignatureError):
        verify(SECRET, "1000", "fred", "deadbeef", now=1000.0)


def test_a_signature_for_a_different_source_is_rejected():
    """Otherwise a captured signature could trigger any job."""
    sig = sign(SECRET, "1000", "fred")
    with pytest.raises(SignatureError):
        verify(SECRET, "1000", "alphavantage", sig, now=1000.0)


def test_a_signature_from_a_different_secret_is_rejected():
    sig = sign("other", "1000", "fred")
    with pytest.raises(SignatureError):
        verify(SECRET, "1000", "fred", sig, now=1000.0)


def test_an_expired_timestamp_is_rejected():
    sig = sign(SECRET, "1000", "fred")
    with pytest.raises(SignatureError):
        verify(SECRET, "1000", "fred", sig, now=1000.0 + 301)


def test_a_timestamp_inside_the_replay_window_is_accepted():
    sig = sign(SECRET, "1000", "fred")
    verify(SECRET, "1000", "fred", sig, now=1000.0 + 299)


def test_a_clock_skewed_future_timestamp_is_still_bounded():
    sig = sign(SECRET, "2000", "fred")
    with pytest.raises(SignatureError):
        verify(SECRET, "2000", "fred", sig, now=1000.0)


def test_a_non_numeric_timestamp_is_rejected():
    with pytest.raises(SignatureError):
        verify(SECRET, "not-a-number", "fred", "x", now=1000.0)
