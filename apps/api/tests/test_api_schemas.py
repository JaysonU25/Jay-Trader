from datetime import date, datetime, timezone
from decimal import Decimal

from marketpulse.api.errors import not_found
from marketpulse.api.schemas import IngestRunOut, ObservationOut, PriceBarOut


def _run(error):
    return IngestRunOut(
        id=1, source="fred", job="macro",
        started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        status="failed", rows_upserted=0, api_calls_used=1, error=error,
    )


def test_decimal_fields_serialize_as_json_numbers_not_strings():
    """Pydantic renders Decimal as a string in JSON mode, which breaks charts."""
    bar = PriceBarOut(
        trade_date=date(2024, 5, 1),
        open=Decimal("169.58"), high=Decimal("172.705"),
        low=Decimal("169.11"), close=Decimal("169.30"), volume=50383147,
    )
    dumped = bar.model_dump_json()
    assert '"close":169.3' in dumped
    assert '"close":"169.30"' not in dumped


def test_volume_stays_an_integer():
    bar = PriceBarOut(
        trade_date=date(2024, 5, 1),
        open=Decimal("1"), high=Decimal("1"), low=Decimal("1"), close=Decimal("1"),
        volume=50383147,
    )
    assert bar.model_dump()["volume"] == 50383147


def test_null_observation_survives_as_null_not_zero():
    """A gap in a FRED series must stay visible, per spec 4.1."""
    obs = ObservationOut(obs_date=date(1947, 1, 1), value=None)
    assert obs.model_dump()["value"] is None
    assert '"value":null' in obs.model_dump_json()


def test_not_found_builds_a_consistent_error_body():
    exc = not_found("symbol", "ZZZZ")
    assert exc.status_code == 404
    assert exc.detail == {"error": "not_found", "resource": "symbol", "id": "ZZZZ"}


def test_ingest_run_error_keeps_only_the_first_line():
    error = "connection failed\nDETAIL: statement was SELECT ... api_key=SECRET"
    assert _run(error).error == "connection failed"


def test_ingest_run_error_is_capped_at_200_characters():
    error = "x" * 5000
    assert _run(error).error == "x" * 200


def test_ingest_run_error_none_stays_none():
    assert _run(None).error is None
