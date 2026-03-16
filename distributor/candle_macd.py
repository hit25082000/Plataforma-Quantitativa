"""Candle aggregation and MACD (30 min) from trades."""

from dataclasses import dataclass, field
from typing import Any, Optional

PERIOD_MIN = 30


@dataclass
class Candle:
    o: float
    h: float
    l: float
    c: float
    v: int


def _ema(values: list[float], period: int) -> float:
    if not values or period <= 0:
        return 0.0
    k = 2.0 / (period + 1)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val


def _calc_macd(closes: list[float]) -> tuple[float, float, float]:
    """Returns (macd_line, signal_line, histogram)."""
    if len(closes) < 26:
        return (0.0, 0.0, 0.0)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = ema12 - ema26
    # Signal = EMA(9) of MACD values over time
    macd_vals = []
    for i in range(12, len(closes) + 1):
        e12 = _ema(closes[:i], 12)
        e26 = _ema(closes[:i], 26)
        macd_vals.append(e12 - e26)
    signal_line = _ema(macd_vals, 9) if len(macd_vals) >= 9 else macd_line
    histogram = macd_line - signal_line
    return (macd_line, signal_line, histogram)


def _bucket_ts(ts_ms: float, period_min: int) -> int:
    """Bucket timestamp to period_min (e.g. 30) minute boundary (ms)."""
    ms_per_bucket = period_min * 60 * 1000
    return int(ts_ms // ms_per_bucket) * ms_per_bucket


def _parse_ts(ts: str) -> float:
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp() * 1000
    except Exception:
        return 0.0


class CandleMacd:
    def __init__(self, period_min: int = PERIOD_MIN) -> None:
        self._period_min = period_min
        self._candles: list[Candle] = []
        self._current_bucket: Optional[int] = None
        self._current: Optional[Candle] = None
        self._closes: list[float] = []

    def on_trade(self, msg: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Process trade; return macd_signal message on new bucket close."""
        if msg.get("topic") != "market" or msg.get("type") != "trade":
            return None

        ts_str = msg.get("ts") or ""
        ts_ms = _parse_ts(ts_str)
        price = float(msg.get("price") or 0)
        qty = int(msg.get("qty") or 0)
        bucket = _bucket_ts(ts_ms, self._period_min)

        if self._current_bucket is None:
            self._current_bucket = bucket
            self._current = Candle(o=price, h=price, l=price, c=price, v=qty)
            return None

        if bucket == self._current_bucket:
            if self._current is not None:
                self._current.h = max(self._current.h, price)
                self._current.l = min(self._current.l, price)
                self._current.c = price
                self._current.v += qty
            return None

        # New bucket: close previous, emit MACD if we have enough data
        result_msg: Optional[dict[str, Any]] = None
        if self._current is not None:
            self._candles.append(self._current)
            self._closes.append(self._current.c)
            max_candles = 200
            if len(self._candles) > max_candles:
                self._candles = self._candles[-max_candles:]
                self._closes = self._closes[-max_candles:]
            if len(self._closes) >= 26:
                macd_line, signal_line, histogram = _calc_macd(self._closes)
                direction = "buy" if histogram > 0 else "sell"
                result_msg = {
                    "topic": "market",
                    "type": "macd_signal",
                    "value": round(macd_line, 4),
                    "signal_line": round(signal_line, 4),
                    "histogram": round(histogram, 4),
                    "direction": direction,
                    "candle_close": self._current.c,
                    "ts": ts_str,
                }

        self._current_bucket = bucket
        self._current = Candle(o=price, h=price, l=price, c=price, v=qty)
        return result_msg
