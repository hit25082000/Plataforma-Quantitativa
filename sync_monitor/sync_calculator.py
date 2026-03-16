"""Compute variation % since open and in_sync flag (all within band)."""

from typing import TypedDict

from price_fetcher import PricePoint


class SyncResult(TypedDict):
    in_sync: bool
    variations: dict[str, float]


def calculate_sync(
    prices: dict[str, PricePoint],
    band_pct: float,
) -> SyncResult:
    """Compute variation % from open and whether all are within ±band_pct."""
    variations: dict[str, float] = {}
    for ticker, pt in prices.items():
        o = pt.get("open") or 0
        c = pt.get("close") or 0
        if o and o > 0:
            variations[ticker] = round((c - o) / o * 100, 2)
        else:
            variations[ticker] = 0.0

    in_sync = all(abs(v) <= band_pct for v in variations.values()) if variations else False
    return {"in_sync": in_sync, "variations": variations}
