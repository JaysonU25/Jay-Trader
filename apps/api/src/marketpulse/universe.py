from datetime import date

EQUITIES: tuple[str, ...] = (
    "SPY", "QQQ", "DIA", "IWM",
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META",
    "GLD", "VOO", "XOM", "JNJ", "WMT",
)

FRED_SERIES: tuple[str, ...] = (
    "DFF", "DGS10", "DGS2", "T10Y2Y",
    "CPIAUCSL", "PCEPI", "UNRATE", "PAYEMS", "GDPC1",
    "M2SL", "VIXCLS", "MORTGAGE30US", "INDPRO", "HOUST", "UMCSENT",
)

# FRED series id -> category used in the `series` table.
FRED_CATEGORY: dict[str, str] = {
    "DFF": "rates", "DGS10": "rates", "DGS2": "rates", "T10Y2Y": "rates",
    "MORTGAGE30US": "rates", "VIXCLS": "rates",
    "CPIAUCSL": "inflation", "PCEPI": "inflation",
    "UNRATE": "labor", "PAYEMS": "labor",
    "GDPC1": "growth", "M2SL": "growth", "INDPRO": "growth",
    "HOUST": "growth", "UMCSENT": "growth",
}

CRYPTO_LIMIT: int = 20

FX_BASE: str = "EUR"
FX_START: date = date(1999, 1, 4)  # first ECB reference rate date
