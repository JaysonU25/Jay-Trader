from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from marketpulse.clients.base import ApiError, BaseClient
from marketpulse.core.ratelimit import TokenBucket


@dataclass(frozen=True)
class FredSeriesMeta:
    series_id: str
    title: str
    units: str
    frequency: str


@dataclass(frozen=True)
class FredObservation:
    obs_date: date
    value: Decimal | None


class FredClient(BaseClient):
    source = "fred"
    base_url = "https://api.stlouisfed.org/fred"

    def __init__(self, http: httpx.AsyncClient, api_key: str, limiter: TokenBucket) -> None:
        super().__init__(http=http, limiter=limiter)
        self._api_key = api_key

    def _auth_params(self) -> dict[str, str]:
        return {"api_key": self._api_key, "file_type": "json"}

    async def fetch_series_meta(self, series_id: str) -> FredSeriesMeta:
        payload = await self.get_json("/series", params={"series_id": series_id})
        entries = payload.get("seriess") or []
        if not entries:
            raise ApiError(f"fred: no metadata for series {series_id}")
        entry = entries[0]
        return FredSeriesMeta(
            series_id=entry["id"],
            title=entry["title"],
            units=entry.get("units", ""),
            frequency=entry.get("frequency_short", ""),
        )

    async def fetch_observations(
        self, series_id: str, start: date | None = None
    ) -> list[FredObservation]:
        params: dict[str, str] = {"series_id": series_id}
        if start is not None:
            params["observation_start"] = start.isoformat()

        payload = await self.get_json("/series/observations", params=params)
        return [
            FredObservation(date.fromisoformat(row["date"]), _to_decimal(row["value"]))
            for row in payload.get("observations", [])
        ]


def _to_decimal(raw: str) -> Decimal | None:
    """FRED writes a missing observation as '.'."""
    if raw in (".", "", None):
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None
