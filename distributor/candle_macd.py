"""Candle aggregation and MACD (30 min) from trades."""

from dataclasses import dataclass, field
import json
from pathlib import Path
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


def _calc_rsi_wilder(closes: list[float], period: int = 14) -> float:
    """RSI Wilder (period). Needs at least period+1 closes. Returns 0-100."""
    if len(closes) < period + 1:
        return 50.0
    last = closes[-(period + 1) :]
    avg_gain = 0.0
    avg_loss = 0.0
    for i in range(1, period + 1):
        change = last[i] - last[i - 1]
        if change > 0:
            avg_gain += change
        else:
            avg_loss += -change
    avg_gain /= period
    avg_loss /= period
    if avg_loss < 1e-10:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


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
        self._ticker: Optional[str] = None
        self._bootstrap_emitted_bucket: Optional[int] = None

    def _state_path(self, ticker: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in ticker.upper())
        return Path(__file__).resolve().parent / "data" / f"candle_macd_{safe}.json"

    def _load_state(self, ticker: str) -> None:
        path = self._state_path(ticker)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            closes = data.get("closes")
            if isinstance(closes, list):
                parsed = [float(v) for v in closes]
                self._closes = parsed[-200:]
            else:
                self._closes = []
        except Exception:
            self._closes = []

    def _save_state(self) -> None:
        if not self._ticker:
            return
        path = self._state_path(self._ticker)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"ticker": self._ticker, "closes": self._closes[-200:]}
        try:
            path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        except Exception:
            # Persist failure must not break real-time flow.
            pass

    def _build_signal(self, ts: str, candle_close: float, closes: list[float], partial: bool = False) -> dict[str, Any]:
        macd_line, signal_line, histogram = _calc_macd(closes)
        direction = "buy" if histogram > 0 else "sell"
        rsi9 = round(_calc_rsi_wilder(closes, 9), 2)
        rsi18 = round(_calc_rsi_wilder(closes, 18), 2)
        rsi30 = round(_calc_rsi_wilder(closes, 30), 2)
        return {
            "topic": "market",
            "type": "macd_signal",
            "value": round(macd_line, 4),
            "signal_line": round(signal_line, 4),
            "histogram": round(histogram, 4),
            "direction": direction,
            "candle_close": candle_close,
            "ts": ts,
            "rsi9": rsi9,
            "rsi18": rsi18,
            "rsi30": rsi30,
            # Backward compatibility during frontend transition.
            "rsi": rsi9,
            "partial": partial,
        }

    def on_trade(self, msg: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Process trade; return macd_signal message on new bucket close."""
        if msg.get("topic") != "market" or msg.get("type") != "trade":
            return None

        ts_str = msg.get("ts") or ""
        ts_ms = _parse_ts(ts_str)
        price = float(msg.get("price") or 0)
        qty = int(msg.get("qty") or 0)
        ticker = str(msg.get("ticker") or "").strip().upper()
        bucket = _bucket_ts(ts_ms, self._period_min)

        if ticker and ticker != self._ticker:
            self._ticker = ticker
            self._candles = []
            self._current_bucket = None
            self._current = None
            self._bootstrap_emitted_bucket = None
            self._load_state(ticker)

        if self._current_bucket is None:
            self._current_bucket = bucket
            self._current = Candle(o=price, h=price, l=price, c=price, v=qty)
            if len(self._closes) >= 26:
                self._bootstrap_emitted_bucket = bucket
                return self._build_signal(ts_str, self._current.c, self._closes + [self._current.c], partial=True)
            return None

        if bucket == self._current_bucket:
            if self._current is not None:
                self._current.h = max(self._current.h, price)
                self._current.l = min(self._current.l, price)
                self._current.c = price
                self._current.v += qty
            if (
                self._current is not None
                and self._bootstrap_emitted_bucket != bucket
                and len(self._closes) >= 26
            ):
                self._bootstrap_emitted_bucket = bucket
                return self._build_signal(ts_str, self._current.c, self._closes + [self._current.c], partial=True)
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
            self._save_state()
            if len(self._closes) >= 26:
                result_msg = self._build_signal(ts_str, self._current.c, self._closes, partial=False)

        self._current_bucket = bucket
        self._current = Candle(o=price, h=price, l=price, c=price, v=qty)
        self._bootstrap_emitted_bucket = None
        return result_msg
