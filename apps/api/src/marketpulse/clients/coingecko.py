from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from marketpulse.clients.base import BaseClient

# The public API's hard ceiling on historical range. See fetch_history.
HISTORY_DAYS = 365


@dataclass(frozen=True)
class CoinSnapshot:
    coin_id: str
    symbol: str
    name: str
    price_usd: Decimal | None
    market_cap_usd: Decimal | None
    volume_24h_usd: Decimal | None
    as_of: date


@dataclass(frozen=True)
class CoinHistoryPoint:
    obs_date: date
    price_usd: Decimal | None
    market_cap_usd: Decimal | None
    volume_24h_usd: Decimal | None


def _dec(value: object) -> Decimal | None:
    """Missing stays missing.

    Spec 4.1 makes `observation.value` nullable precisely so a gap renders as a
    gap. Coercing an absent market cap to 0 would draw a crash to zero on the
    chart, so absence maps to NULL exactly as the FRED path does.
    """
    return None if value is None else Decimal(str(value))


def _day(epoch_ms: int) -> date:
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).date()


def _value_at(rows: list, index: int) -> object:
    """The value half of `rows[index]`, or None if the array is short."""
    if index >= len(rows):
        return None
    entry = rows[index]
    return entry[1] if len(entry) > 1 else None


class CoinGeckoClient(BaseClient):
    source = "coingecko"
    base_url = "https://api.coingecko.com/api/v3"

    def __init__(self, http, limiter, api_key: str | None = None, **kwargs) -> None:
        super().__init__(http, limiter, **kwargs)
        self._api_key = api_key

    def _auth_params(self) -> dict[str, str]:
        """Demo-plan key, sent as a query parameter.

        `/coins/markets` still answers anonymously, so the daily snapshot works
        without this; `/coins/{id}/market_chart` does not, and returns 401. A
        Pro key would need the `pro-api.coingecko.com` host and the
        `x_cg_pro_api_key` name instead, so this stays demo-only on purpose.
        """
        return {"x_cg_demo_api_key": self._api_key} if self._api_key else {}

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
        #
        # `days=365`, not `days=max`. Anything longer is refused with a 401 and
        # error_code 10012: "Public API users are limited to querying historical
        # data within the past 365 days." That status code reads like an auth
        # failure and is not one — a demo key does not lift the limit, only a
        # paid plan does. Crypto history is therefore one year deep, unlike FX
        # and FRED.
        payload = await self.get_json(
            f"/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": str(HISTORY_DAYS)},
        )

        # The three arrays are parallel: entry i of each describes the same
        # sample. They are joined by index, not by timestamp equality -- the
        # vendor does not guarantee identical epoch-millisecond stamps across
        # them, and an exact-match join that misses would quietly write zeros
        # for every market cap and volume in the backfill.
        prices = payload.get("prices") or []
        caps = payload.get("market_caps") or []
        volumes = payload.get("total_volumes") or []

        return [
            CoinHistoryPoint(
                obs_date=_day(entry[0]),
                price_usd=_dec(_value_at(prices, index)),
                market_cap_usd=_dec(_value_at(caps, index)),
                volume_24h_usd=_dec(_value_at(volumes, index)),
            )
            for index, entry in enumerate(prices)
        ]
