"""Candle aggregation and MACD (30 min) from trades."""

from dataclasses import dataclass, field
import csv
import json
from pathlib import Path
import time
from typing import Any, Optional

PERIOD_MIN = 30
DEBUG_LOG_PATH = Path(__file__).resolve().parents[1] / "debug-407c7f.log"
DEBUG_SESSION_ID = "407c7f"


@dataclass
class Candle:
    o: float
    h: float
    l: float
    c: float
    v: int


@dataclass
class TickerState:
    candles: list[Candle] = field(default_factory=list)
    current_bucket: Optional[int] = None
    current: Optional[Candle] = None
    closes: list[float] = field(default_factory=list)
    bootstrap_emitted_bucket: Optional[int] = None


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


def _parse_ts(ts: Any) -> float:
    if isinstance(ts, (int, float)):
        val = float(ts)
        return val if val > 1e12 else val * 1000.0
    if isinstance(ts, str):
        s = ts.strip()
        if not s:
            return 0.0
        try:
            val = float(s)
            return val if val > 1e12 else val * 1000.0
        except Exception:
            pass
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.timestamp() * 1000
        except Exception:
            return 0.0
    return 0.0


def _debug_log(run_id: str, hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    try:
        payload = {
            "sessionId": DEBUG_SESSION_ID,
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass


class CandleMacd:
    def __init__(self, period_min: int = PERIOD_MIN) -> None:
        self._period_min = period_min
        self._states: dict[str, TickerState] = {}

    def _state_path(self, ticker: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in ticker.upper())
        return Path(__file__).resolve().parent / "data" / f"candle_macd_{safe}.json"

    def _bootstrap_closes_from_stats(self, ticker: str, max_closes: int = 200) -> list[float]:
        logs_dir = Path(__file__).resolve().parent / "logs"
        if not logs_dir.exists():
            return []
        files = sorted(logs_dir.glob("stats_*.csv"), key=lambda p: p.name, reverse=True)
        # read latest files first and aggregate by 30m bucket
        bucket_to_price: dict[int, float] = {}
        for path in files:
            try:
                with path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get("topic") != "market" or row.get("type") != "trade":
                            continue
                        if (row.get("ticker") or "").strip().upper() != ticker:
                            continue
                        ts = row.get("ts") or ""
                        ts_ms = _parse_ts(ts)
                        if ts_ms <= 0:
                            continue
                        try:
                            price = float(row.get("price") or 0.0)
                        except Exception:
                            continue
                        bucket = _bucket_ts(ts_ms, self._period_min)
                        # keep latest trade price seen in bucket while iterating chronological file
                        bucket_to_price[bucket] = price
            except Exception:
                continue
        if not bucket_to_price:
            return []
        closes = [bucket_to_price[b] for b in sorted(bucket_to_price.keys())]
        return closes[-max_closes:]

    def _load_state(self, ticker: str, state: TickerState) -> None:
        path = self._state_path(ticker)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            closes = data.get("closes")
            if isinstance(closes, list):
                parsed = [float(v) for v in closes]
                state.closes = parsed[-200:]
            else:
                state.closes = []
        except Exception:
            state.closes = []
        if len(state.closes) < 31:
            stats_closes = self._bootstrap_closes_from_stats(ticker, 200)
            if len(stats_closes) > len(state.closes):
                state.closes = stats_closes
            _debug_log(
                "post-fix",
                "H5",
                "distributor/candle_macd.py:_load_state",
                "bootstrap_from_stats",
                {"ticker": ticker, "state_closes_after_bootstrap": len(state.closes)},
            )

    def _save_state(self, ticker: str, state: TickerState) -> None:
        path = self._state_path(ticker)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"ticker": ticker, "closes": state.closes[-200:]}
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
        if ts_ms <= 0:
            _debug_log(
                "pre-fix",
                "H1",
                "distributor/candle_macd.py:on_trade",
                "trade_discarded_invalid_ts",
                {"ts": ts_str, "ticker": msg.get("ticker"), "type": type(ts_str).__name__},
            )
            return None
        price = float(msg.get("price") or 0)
        qty = int(msg.get("qty") or 0)
        ticker = str(msg.get("ticker") or "").strip().upper()
        if not ticker:
            _debug_log(
                "pre-fix",
                "H4",
                "distributor/candle_macd.py:on_trade",
                "trade_discarded_missing_ticker",
                {"ts": ts_str},
            )
            return None
        bucket = _bucket_ts(ts_ms, self._period_min)

        state = self._states.get(ticker)
        if state is None:
            state = TickerState()
            self._load_state(ticker, state)
            self._states[ticker] = state
            _debug_log(
                "pre-fix",
                "H4",
                "distributor/candle_macd.py:on_trade",
                "ticker_state_initialized",
                {"ticker": ticker, "loaded_closes": len(state.closes)},
            )

        if state.current_bucket is None:
            state.current_bucket = bucket
            state.current = Candle(o=price, h=price, l=price, c=price, v=qty)
            if len(state.closes) >= 9 and state.current is not None:
                state.bootstrap_emitted_bucket = bucket
                _debug_log(
                    "pre-fix",
                    "H1",
                    "distributor/candle_macd.py:on_trade",
                    "emitting_partial_macd_signal",
                    {"ticker": ticker, "bucket": bucket, "closes": len(state.closes)},
                )
                return self._build_signal(ts_str, state.current.c, state.closes + [state.current.c], partial=True)
            return None

        if bucket == state.current_bucket:
            if state.current is not None:
                state.current.h = max(state.current.h, price)
                state.current.l = min(state.current.l, price)
                state.current.c = price
                state.current.v += qty
            if (
                state.current is not None
                and state.bootstrap_emitted_bucket != bucket
                and len(state.closes) >= 9
            ):
                state.bootstrap_emitted_bucket = bucket
                _debug_log(
                    "pre-fix",
                    "H1",
                    "distributor/candle_macd.py:on_trade",
                    "emitting_partial_macd_signal_same_bucket",
                    {"ticker": ticker, "bucket": bucket, "closes": len(state.closes)},
                )
                return self._build_signal(ts_str, state.current.c, state.closes + [state.current.c], partial=True)
            return None

        # New bucket: close previous, emit MACD if we have enough data
        result_msg: Optional[dict[str, Any]] = None
        if state.current is not None:
            state.candles.append(state.current)
            state.closes.append(state.current.c)
            max_candles = 200
            if len(state.candles) > max_candles:
                state.candles = state.candles[-max_candles:]
                state.closes = state.closes[-max_candles:]
            self._save_state(ticker, state)
            if len(state.closes) >= 9:
                _debug_log(
                    "pre-fix",
                    "H1",
                    "distributor/candle_macd.py:on_trade",
                    "emitting_closed_bucket_signal",
                    {"ticker": ticker, "bucket": state.current_bucket, "closes": len(state.closes)},
                )
                result_msg = self._build_signal(ts_str, state.current.c, state.closes, partial=False)
            else:
                _debug_log(
                    "pre-fix",
                    "H1",
                    "distributor/candle_macd.py:on_trade",
                    "not_enough_closes_for_signal",
                    {"ticker": ticker, "closes": len(state.closes)},
                )

        state.current_bucket = bucket
        state.current = Candle(o=price, h=price, l=price, c=price, v=qty)
        state.bootstrap_emitted_bucket = None
        return result_msg
