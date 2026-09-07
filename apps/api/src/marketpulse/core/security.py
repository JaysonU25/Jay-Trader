import hashlib
import hmac
import time


class SignatureError(Exception):
    """The request did not carry a valid, fresh signature."""


def sign(secret: str, timestamp: str, source: str) -> str:
    message = f"{timestamp}.{source}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


MAX_CLOCK_SKEW_SECONDS = 30


def verify(
    secret: str,
    timestamp: str,
    source: str,
    signature: str,
    *,
    max_age_seconds: int = 300,
    now: float | None = None,
) -> None:
    """Raise SignatureError unless the signature is valid and recent.

    The timestamp is part of the signed message, so it cannot be edited without
    invalidating the signature; bounding its age then caps how long a captured
    request stays replayable. Per spec 7.1, "more than max_age_seconds old" is
    rejected on the past side; the future side gets only a small clock-skew
    allowance, not the same window, or the effective replay window would be
    doubled. The comparison is constant-time.
    """
    try:
        issued = float(timestamp)
    except (TypeError, ValueError):
        raise SignatureError("malformed timestamp") from None

    current = time.time() if now is None else now
    age = current - issued
    if age > max_age_seconds or age < -MAX_CLOCK_SKEW_SECONDS:
        raise SignatureError("timestamp outside the replay window")

    if not hmac.compare_digest(sign(secret, timestamp, source), signature):
        raise SignatureError("signature mismatch")
