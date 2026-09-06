from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from marketpulse.clients.base import BaseClient


@dataclass(frozen=True)
class FxRate:
    base: str
    quote: str
    obs_date: date
    rate: Decimal


class FrankfurterClient(BaseClient):
    source = "frankfurter"
    base_url = "https://api.frankfurter.dev/v1"

    async def fetch_timeseries(self, start: date, base: str = "EUR") -> list[FxRate]:
        payload = await self.get_json(f"/{start.isoformat()}..", params={"base": base})
        resolved_base = payload.get("base", base)

        rates: list[FxRate] = []
        for day, quotes in payload.get("rates", {}).items():
            obs_date = date.fromisoformat(day)
            for quote, value in quotes.items():
                rates.append(
                    FxRate(
                        base=resolved_base,
                        quote=quote,
                        obs_date=obs_date,
                        rate=Decimal(str(value)),
                    )
                )
        return rates
