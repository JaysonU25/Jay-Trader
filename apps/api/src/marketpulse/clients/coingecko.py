from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from marketpulse.clients.base import BaseClient


@dataclass(frozen=True)
class CoinSnapshot:
    coin_id: str
    symbol: str
    name: str
    price_usd: Decimal
    market_cap_usd: Decimal
    volume_24h_usd: Decimal
    as_of: date


@dataclass(frozen=True)
class CoinHistoryPoint:
    obs_date: date
    price_usd: Decimal
    market_cap_usd: Decimal
    volume_24h_usd: Decimal


def _dec(value: object) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


def _day(epoch_ms: int) -> date:
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).date()


class CoinGeckoClient(BaseClient):
    source = "coingecko"
    base_url = "https://api.coingecko.com/api/v3"

    async def fetch_top_markets(self, limit: int = 20) -> list[CoinSnapshot]:
        payload = await self.get_json(
            "/coins/markets",
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": str(limit),
                "page": "1",
            },
        )
        return [
            CoinSnapshot(
                coin_id=row["id"],
                symbol=row["symbol"],
                name=row["name"],
                price_usd=_dec(row.get("current_price")),
                market_cap_usd=_dec(row.get("market_cap")),
                volume_24h_usd=_dec(row.get("total_volume")),
                as_of=datetime.fromisoformat(
                    row["last_updated"].replace("Z", "+00:00")
                ).date(),
            )
            for row in payload
        ]

    async def fetch_history(self, coin_id: str) -> list[CoinHistoryPoint]:
        # No `interval` parameter: it is a paid-tier option, and the free tier
        # already returns daily granularity for ranges beyond 90 days.
        payload = await self.get_json(
            f"/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": "max"},
        )

        caps = {ts: value for ts, value in payload.get("market_caps", [])}
        volumes = {ts: value for ts, value in payload.get("total_volumes", [])}

        return [
            CoinHistoryPoint(
                obs_date=_day(ts),
                price_usd=_dec(price),
                market_cap_usd=_dec(caps.get(ts)),
                volume_24h_usd=_dec(volumes.get(ts)),
            )
            for ts, price in payload.get("prices", [])
        ]
