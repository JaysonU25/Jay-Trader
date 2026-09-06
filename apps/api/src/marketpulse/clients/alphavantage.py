from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import httpx

from marketpulse.clients.base import ApiError, BaseClient, RateLimitedError
from marketpulse.core.ratelimit import TokenBucket

_SERIES_KEY = "Time Series (Daily)"


@dataclass(frozen=True)
class DailyBar:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class AlphaVantageClient(BaseClient):
    source = "alphavantage"
    base_url = "https://www.alphavantage.co"

    def __init__(self, http: httpx.AsyncClient, api_key: str, limiter: TokenBucket) -> None:
        super().__init__(http=http, limiter=limiter)
        self._api_key = api_key

    def _auth_params(self) -> dict[str, str]:
        return {"apikey": self._api_key}

    async def fetch_daily(self, symbol: str, full: bool = False) -> list[DailyBar]:
        payload = await self.get_json(
            "/query",
            params={
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": "full" if full else "compact",
            },
        )

        # Alpha Vantage answers a throttled request with HTTP 200 and a prose body.
        if "Note" in payload or "Information" in payload:
            raise RateLimitedError(
                f"alphavantage: {payload.get('Note') or payload.get('Information')}"
            )
        if "Error Message" in payload:
            raise ApiError(f"alphavantage: {payload['Error Message']}")
        if _SERIES_KEY not in payload:
            raise ApiError(f"alphavantage: unexpected payload keys {sorted(payload)}")

        bars = [
            DailyBar(
                trade_date=date.fromisoformat(day),
                open=Decimal(row["1. open"]),
                high=Decimal(row["2. high"]),
                low=Decimal(row["3. low"]),
                close=Decimal(row["4. close"]),
                volume=int(row["5. volume"]),
            )
            for day, row in payload[_SERIES_KEY].items()
        ]
        bars.sort(key=lambda bar: bar.trade_date)
        return bars
