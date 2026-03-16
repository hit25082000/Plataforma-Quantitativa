"""Fetch open and last price for configured tickers via external API."""

import logging
from typing import TypedDict

logger = logging.getLogger(__name__)


class PricePoint(TypedDict):
    open: float
    close: float


def fetch_prices(tickers: list[str]) -> dict[str, PricePoint]:
    """Return dict {ticker: {open, close}}. Missing/failed tickers are omitted."""
    result: dict[str, PricePoint] = {}
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed; returning empty prices")
        return result

    try:
        symbols = [f"{t}.SA" for t in tickers]
        data = yf.download(
            symbols,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
            interval="1d",
            period="5d",
        )
        if data is None or data.empty:
            logger.debug("yfinance returned no data for %s", symbols)
            return result

        if len(tickers) == 1:
            sym = f"{tickers[0]}.SA"
            o, c = None, None
            # Flat columns (single ticker: Open, Close)
            if "Open" in data.columns and "Close" in data.columns:
                o, c = data["Open"], data["Close"]
            # MultiIndex columns (sym, "Open") / (sym, "Close")
            elif hasattr(data.columns, "levels") and sym in data.columns.get_level_values(0):
                if (sym, "Open") in data.columns and (sym, "Close") in data.columns:
                    o, c = data[(sym, "Open")], data[(sym, "Close")]
                elif hasattr(data[sym], "__getitem__"):
                    o = data[sym]["Open"] if "Open" in data[sym].columns else None
                    c = data[sym]["Close"] if "Close" in data[sym].columns else None
            if o is not None and c is not None and len(data) > 0:
                try:
                    result[tickers[0]] = {
                        "open": float(o.iloc[-1]),
                        "close": float(c.iloc[-1]),
                    }
                except (TypeError, IndexError, KeyError) as e:
                    logger.warning("Single-ticker extract failed for %s: %s", tickers[0], e)
            else:
                # Fallback: Ticker API (more reliable for single symbol in some environments)
                try:
                    t = yf.Ticker(sym)
                    hist = t.history(period="5d", interval="1d", auto_adjust=True)
                    if hist is not None and not hist.empty and "Open" in hist.columns and "Close" in hist.columns:
                        result[tickers[0]] = {
                            "open": float(hist["Open"].iloc[-1]),
                            "close": float(hist["Close"].iloc[-1]),
                        }
                        logger.debug("Single-ticker %s: got price via Ticker fallback", tickers[0])
                    else:
                        logger.debug("Single-ticker %s: Open/Close not found (columns: %s)", tickers[0], list(data.columns))
                except Exception as e:
                    logger.warning("Ticker fallback failed for %s: %s", tickers[0], e)
            return result

        for t in tickers:
            sym = f"{t}.SA"
            try:
                if hasattr(data.columns, "levels") and sym in data.columns.get_level_values(0):
                    open_ser = data[sym]["Open"]
                    close_ser = data[sym]["Close"]
                else:
                    open_ser = data["Open"] if "Open" in data.columns else None
                    close_ser = data["Close"] if "Close" in data.columns else None
                if open_ser is not None and close_ser is not None and len(open_ser) > 0:
                    result[t] = {
                        "open": float(open_ser.iloc[-1]),
                        "close": float(close_ser.iloc[-1]),
                    }
            except (KeyError, TypeError, IndexError):
                continue
    except Exception as e:
        logger.exception("fetch_prices failed: %s", e)
    return result
