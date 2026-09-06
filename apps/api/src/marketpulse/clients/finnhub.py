from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx

from marketpulse.clients.base import BaseClient
from marketpulse.core.ratelimit import TokenBucket


@dataclass(frozen=True)
class NewsItem:
    symbol: str
    published_at: datetime
    headline: str
    source: str | None
    url: str
    summary: str | None
    image_url: str | None


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    report_date: date
    hour: str | None
    eps_estimate: Decimal | None
    eps_actual: Decimal | None
    revenue_estimate: int | None
    revenue_actual: int | None


@dataclass(frozen=True)
class RatingSnapshot:
    symbol: str
    period: date
    strong_buy: int | None
    buy: int | None
    hold: int | None
    sell: int | None
    strong_sell: int | None


def _blank_to_none(value: str | None) -> str | None:
    return value or None


def _dec_or_none(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _int_or_none(value: object) -> int | None:
    return None if value is None else int(value)


class FinnhubClient(BaseClient):
    source = "finnhub"
    base_url = "https://finnhub.io/api/v1"

    def __init__(self, http: httpx.AsyncClient, api_key: str, limiter: TokenBucket) -> None:
        super().__init__(http=http, limiter=limiter)
        self._api_key = api_key

    def _auth_params(self) -> dict[str, str]:
        return {"token": self._api_key}

    async def fetch_news(self, symbol: str, start: date, end: date) -> list[NewsItem]:
        payload = await self.get_json(
            "/company-news",
            params={"symbol": symbol, "from": start.isoformat(), "to": end.isoformat()},
        )
        return [
            NewsItem(
                symbol=symbol,
                published_at=datetime.fromtimestamp(row["datetime"], tz=timezone.utc),
                headline=row["headline"],
                source=_blank_to_none(row.get("source")),
                url=row["url"],
                summary=_blank_to_none(row.get("summary")),
                image_url=_blank_to_none(row.get("image")),
            )
            for row in payload
            if row.get("url")
        ]

    async def fetch_earnings(self, start: date, end: date) -> list[EarningsEvent]:
        payload = await self.get_json(
            "/calendar/earnings",
            params={"from": start.isoformat(), "to": end.isoformat()},
        )
        return [
            EarningsEvent(
                symbol=row["symbol"],
                report_date=date.fromisoformat(row["date"]),
                hour=_blank_to_none(row.get("hour")),
                eps_estimate=_dec_or_none(row.get("epsEstimate")),
                eps_actual=_dec_or_none(row.get("epsActual")),
                revenue_estimate=_int_or_none(row.get("revenueEstimate")),
                revenue_actual=_int_or_none(row.get("revenueActual")),
            )
            for row in payload.get("earningsCalendar", [])
        ]

    async def fetch_ratings(self, symbol: str) -> list[RatingSnapshot]:
        payload = await self.get_json("/stock/recommendation", params={"symbol": symbol})
        return [
            RatingSnapshot(
                symbol=row["symbol"],
                period=date.fromisoformat(row["period"]),
                strong_buy=_int_or_none(row.get("strongBuy")),
                buy=_int_or_none(row.get("buy")),
                hold=_int_or_none(row.get("hold")),
                sell=_int_or_none(row.get("sell")),
                strong_sell=_int_or_none(row.get("strongSell")),
            )
            for row in payload
        ]
