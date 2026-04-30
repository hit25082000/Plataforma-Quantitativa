"""Candle aggregation and MACD (30 min) + IFR intrabar a partir de trades."""

from dataclasses import dataclass, field
import csv
import json
import math
from pathlib import Path
import time
from typing import Any, Optional

PERIOD_MIN = 30
# Limite de frequência de macd_signal parcial por ticker (evita saturar o WebSocket).
MIN_PARTIAL_MACD_INTERVAL_MS = 100.0
# Alinhado ao Renko do Profit (ex.: WINFUT 42R) e ao engine rule5 (R5_RENKO_SIZE = 42).
DEFAULT_RENKO_BRICK_POINTS = 42.0
# Série do IFR/RSI em macd_signal: Renko (42r/16r) ou candles de 30 min (30m).
IFR_SERIES_42R = "42r"
IFR_SERIES_16R = "16r"
IFR_SERIES_30M = "30m"


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
    # Renko (fechamentos de tijolo) — série usada para IFR/RSI, como no Profit em gráfico R.
    renko_ref: Optional[float] = None
    renko_initialized: bool = False
    renko_closes: list[float] = field(default_factory=list)


def _ema(values: list[float], period: int) -> float:
    if not values or period <= 0:
        return 0.0
    k = 2.0 / (period + 1)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val


def _calc_rsi_wilder(closes: list[float], period: int = 14) -> float:
    """RSI Wilder clássico (smoothing) no último valor da série. Retorna 0-100."""
    n = len(closes)
    if n < period + 1:
        return 50.0
    avg_gain = 0.0
    avg_loss = 0.0
    for i in range(1, period + 1):
        ch = closes[i] - closes[i - 1]
        if ch > 0:
            avg_gain += ch
        else:
            avg_loss += -ch
    avg_gain /= period
    avg_loss /= period
    for i in range(period + 1, n):
        ch = closes[i] - closes[i - 1]
        g = ch if ch > 0 else 0.0
        l = -ch if ch < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss < 1e-10:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _safe_rsi_display(x: float, default: float = 50.0) -> float:
    """Garante número finito no JSON (evita NaN/null que quebram o IFR no frontend)."""
    if not math.isfinite(x):
        return default
    return round(float(x), 2)


def _calc_macd(closes: list[float]) -> tuple[float, float, float]:
    """Returns (macd_line, signal_line, histogram)."""
    if len(closes) < 26:
        return (0.0, 0.0, 0.0)
    k12 = 2.0 / (12 + 1)
    k26 = 2.0 / (26 + 1)
    k9 = 2.0 / (9 + 1)

    ema12 = closes[0]
    ema26 = closes[0]
    macd_vals: list[float] = []
    signal_line = 0.0
    signal_seeded = False

    for idx, close in enumerate(closes):
        if idx > 0:
            ema12 = close * k12 + ema12 * (1 - k12)
            ema26 = close * k26 + ema26 * (1 - k26)
        macd = ema12 - ema26
        if idx >= 11:
            macd_vals.append(macd)
            if not signal_seeded:
                signal_line = macd
                signal_seeded = True
            else:
                signal_line = macd * k9 + signal_line * (1 - k9)

    macd_line = macd_vals[-1] if macd_vals else 0.0
    if not macd_vals:
        return (0.0, 0.0, 0.0)
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


class CandleMacd:
    def __init__(
        self,
        period_min: int = PERIOD_MIN,
        renko_brick_points: float = DEFAULT_RENKO_BRICK_POINTS,
    ) -> None:
        self._period_min = period_min
        self._ifr_series = IFR_SERIES_42R
        self._renko_brick_points = float(renko_brick_points)
        self._states: dict[str, TickerState] = {}
        self._last_partial_emit_ms: dict[str, float] = {}

    def set_ifr_series(self, series: str) -> None:
        """Define série do IFR: 42r, 16r ou 30m (fechamentos de candle de PERIOD_MIN)."""
        s = (series or "").strip().lower()
        if s in ("42r", "42"):
            new_series, new_brick = IFR_SERIES_42R, 42.0
        elif s in ("16r", "16"):
            new_series, new_brick = IFR_SERIES_16R, 16.0
        elif s in ("30m", "30min", "30_min", "30_minutos", "30 min", "30minutos"):
            new_series = IFR_SERIES_30M
            new_brick = self._renko_brick_points
        else:
            return
        same_mode = new_series == self._ifr_series and (
            new_series == IFR_SERIES_30M or abs(self._renko_brick_points - new_brick) < 1e-9
        )
        self._ifr_series = new_series
        if new_series != IFR_SERIES_30M:
            self._renko_brick_points = new_brick
        if not same_mode:
            for ticker, st in self._states.items():
                st.renko_ref = None
                st.renko_initialized = False
                st.renko_closes = []
                if new_series != IFR_SERIES_30M:
                    current_closes = st.closes
                    self._load_state(ticker, st)
                    if len(current_closes) > len(st.closes):
                        st.closes = current_closes[-200:]

    def set_renko_brick_points(self, points: float) -> None:
        """Compat: 16 ou 42 pontos Renko."""
        p = int(float(points))
        if p == 16:
            self.set_ifr_series(IFR_SERIES_16R)
        elif p == 42:
            self.set_ifr_series(IFR_SERIES_42R)

    def renko_brick_points(self) -> float:
        return self._renko_brick_points

    def ifr_series(self) -> str:
        return self._ifr_series

    def _rsi_closes(self, state: TickerState, macd_closes: list[float]) -> list[float]:
        if self._ifr_series == IFR_SERIES_30M:
            return macd_closes
        return state.renko_closes

    def _rsi_closes_intrabar(
        self, state: TickerState, macd_c: list[float], last_price: float
    ) -> list[float]:
        """RSI em tempo quase real: 30m usa candle em formação; Renko usa tijolos + último preço."""
        if self._ifr_series == IFR_SERIES_30M:
            return macd_c
        if not state.renko_closes:
            return [last_price]
        return [*state.renko_closes, last_price]

    def _throttle_partial_emit(self, ticker: str) -> bool:
        """True se pode emitir outro macd_signal parcial agora."""
        now_ms = time.monotonic() * 1000.0
        last = self._last_partial_emit_ms.get(ticker, 0.0)
        if now_ms - last < MIN_PARTIAL_MACD_INTERVAL_MS:
            return False
        self._last_partial_emit_ms[ticker] = now_ms
        return True

    def _can_emit_macd_signal(self, state: TickerState) -> bool:
        """9 fechamentos de 30m (MACD + IFR 30m) ou tijolos Renko suficientes para RSI[9] (10+ fechamentos)."""
        if len(state.closes) >= 9:
            return True
        if self._ifr_series != IFR_SERIES_30M and len(state.renko_closes) >= 10:
            return True
        return False

    def _apply_renko_trade(self, state: TickerState, price: float) -> None:
        """Atualiza série Renko a partir do preço do trade (mesma lógica do engine rule5)."""
        if self._ifr_series == IFR_SERIES_30M:
            return
        brick = self._renko_brick_points
        if not state.renko_initialized:
            state.renko_ref = price
            state.renko_initialized = True
            return
        ref = state.renko_ref
        if ref is None:
            state.renko_ref = price
            return
        delta = price - ref
        bricks = int(abs(delta) / brick)
        if bricks <= 0:
            return
        direction = 1.0 if delta > 0 else -1.0
        for _ in range(bricks):
            ref = ref + direction * brick
            state.renko_closes.append(ref)
        state.renko_ref = ref
        max_r = 600
        if len(state.renko_closes) > max_r:
            state.renko_closes = state.renko_closes[-max_r:]

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

    def _bootstrap_renko_from_stats(
        self,
        ticker: str,
        max_bricks: int = 600,
        max_trades: int = 50_000,
    ) -> tuple[list[float], Optional[float], bool]:
        """Reconstrói tijolos Renko a partir de trades nos CSVs de stats (ordem cronológica)."""
        if self._ifr_series == IFR_SERIES_30M:
            return [], None, False
        logs_dir = Path(__file__).resolve().parent / "logs"
        if not logs_dir.exists():
            return [], None, False
        trades: list[tuple[float, float]] = []
        for path in sorted(logs_dir.glob("stats_*.csv"), key=lambda p: p.name):
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
                        trades.append((ts_ms, price))
            except Exception:
                continue
        if not trades:
            return [], None, False
        trades.sort(key=lambda x: x[0])
        trades = trades[-max_trades:]
        brick = self._renko_brick_points
        renko_ref: Optional[float] = None
        renko_initialized = False
        renko_closes: list[float] = []
        for _, price in trades:
            if not renko_initialized:
                renko_ref = price
                renko_initialized = True
                continue
            ref = renko_ref
            if ref is None:
                renko_ref = price
                continue
            delta = price - ref
            bricks = int(abs(delta) / brick)
            if bricks > 0:
                direction = 1.0 if delta > 0 else -1.0
                for _ in range(bricks):
                    ref = ref + direction * brick
                    renko_closes.append(ref)
                renko_ref = ref
            if len(renko_closes) > max_bricks:
                renko_closes = renko_closes[-max_bricks:]
        return renko_closes[-max_bricks:], renko_ref, renko_initialized

    def warm_snapshot_message(self, ticker: str) -> Optional[dict[str, Any]]:
        """Último MACD/IFR derivado só de estado persistido/bootstrap (sem trade ao vivo)."""
        t = ticker.strip().upper()
        if not t:
            return None
        state = self._states.get(t)
        if state is None:
            state = TickerState()
            self._load_state(t, state)
            self._states[t] = state
        if not self._can_emit_macd_signal(state):
            return None
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if len(state.closes) >= 2:
            macd_c = state.closes
            close = state.closes[-1]
        elif len(state.renko_closes) >= 2:
            macd_c = state.renko_closes[-200:]
            close = state.renko_closes[-1]
        else:
            return None
        rsi_c = self._rsi_closes(state, macd_c)
        # Fechamentos já consolidados (closes / renko_closes) — não é candle em formação.
        # partial=False evita no frontend substituir este snapshot pelo primeiro macd parcial ao vivo
        # e perder RSI até o próximo fechamento.
        return self._build_signal(ts, close, macd_c, rsi_c, partial=False)

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
            saved_brick = data.get("renko_brick_points")
            brick_ok = (
                self._ifr_series != IFR_SERIES_30M
                and isinstance(saved_brick, (int, float))
                and abs(float(saved_brick) - self._renko_brick_points) < 1e-6
            )
            if brick_ok:
                rc = data.get("renko_closes")
                if isinstance(rc, list):
                    state.renko_closes = [float(v) for v in rc][-600:]
                rr = data.get("renko_ref")
                if isinstance(rr, (int, float)):
                    state.renko_ref = float(rr)
                else:
                    state.renko_ref = None
                state.renko_initialized = bool(data.get("renko_initialized", False))
            else:
                state.renko_ref = None
                state.renko_initialized = False
                state.renko_closes = []
        except Exception:
            state.closes = []
            state.renko_ref = None
            state.renko_initialized = False
            state.renko_closes = []
        if self._ifr_series == IFR_SERIES_30M:
            state.renko_ref = None
            state.renko_initialized = False
            state.renko_closes = []
        if len(state.closes) < 31:
            stats_closes = self._bootstrap_closes_from_stats(ticker, 200)
            if len(stats_closes) > len(state.closes):
                state.closes = stats_closes
        if self._ifr_series != IFR_SERIES_30M:
            br_closes, br_ref, br_init = self._bootstrap_renko_from_stats(ticker)
            if len(br_closes) > len(state.renko_closes):
                state.renko_closes = br_closes
                state.renko_ref = br_ref
                state.renko_initialized = br_init

    def _save_state(self, ticker: str, state: TickerState) -> None:
        path = self._state_path(ticker)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ticker": ticker,
            "closes": state.closes[-200:],
            "ifr_series": self._ifr_series,
            "renko_brick_points": self._renko_brick_points,
            "renko_ref": state.renko_ref,
            "renko_initialized": state.renko_initialized,
            "renko_closes": state.renko_closes[-600:],
        }
        try:
            path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        except Exception:
            # Persist failure must not break real-time flow.
            pass

    def _build_signal(
        self,
        ts: str,
        candle_close: float,
        macd_closes: list[float],
        rsi_closes: list[float],
        partial: bool = False,
    ) -> dict[str, Any]:
        macd_line, signal_line, histogram = _calc_macd(macd_closes)
        macd_line = float(macd_line) if math.isfinite(macd_line) else 0.0
        signal_line = float(signal_line) if math.isfinite(signal_line) else 0.0
        histogram = float(histogram) if math.isfinite(histogram) else 0.0
        direction = "buy" if histogram > 0 else "sell"
        rsi9 = _safe_rsi_display(_calc_rsi_wilder(rsi_closes, 9))
        rsi18 = _safe_rsi_display(_calc_rsi_wilder(rsi_closes, 18))
        rsi30 = _safe_rsi_display(_calc_rsi_wilder(rsi_closes, 30))
        out: dict[str, Any] = {
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
            "ifr_series": self._ifr_series,
            # Backward compatibility during frontend transition.
            "rsi": rsi9,
            "partial": partial,
        }
        if self._ifr_series == IFR_SERIES_30M:
            out["renko_brick_points"] = None
        else:
            out["renko_brick_points"] = self._renko_brick_points
        return out

    def on_trade(self, msg: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Process trade; return macd_signal em fechamento de bucket e parciais intrabar (throttle)."""
        if msg.get("topic") != "market" or msg.get("type") != "trade":
            return None

        ts_str = msg.get("ts") or ""
        ts_ms = _parse_ts(ts_str)
        if ts_ms <= 0:
            return None
        price = float(msg.get("price") or 0)
        qty = int(msg.get("qty") or 0)
        ticker = str(msg.get("ticker") or "").strip().upper()
        if not ticker:
            return None
        bucket = _bucket_ts(ts_ms, self._period_min)

        state = self._states.get(ticker)
        if state is None:
            state = TickerState()
            self._load_state(ticker, state)
            self._states[ticker] = state

        self._apply_renko_trade(state, price)

        if state.current_bucket is None:
            state.current_bucket = bucket
            state.current = Candle(o=price, h=price, l=price, c=price, v=qty)
            if self._can_emit_macd_signal(state) and state.current is not None:
                if not self._throttle_partial_emit(ticker):
                    return None
                macd_c = state.closes + [state.current.c]
                rsi_c = self._rsi_closes_intrabar(
                    state, macd_c, state.current.c
                )
                return self._build_signal(
                    ts_str,
                    state.current.c,
                    macd_c,
                    rsi_c,
                    partial=True,
                )
            return None

        if bucket == state.current_bucket:
            if state.current is not None:
                state.current.h = max(state.current.h, price)
                state.current.l = min(state.current.l, price)
                state.current.c = price
                state.current.v += qty
            if (
                state.current is not None
                and self._can_emit_macd_signal(state)
                and self._throttle_partial_emit(ticker)
            ):
                macd_c = state.closes + [state.current.c]
                rsi_c = self._rsi_closes_intrabar(
                    state, macd_c, state.current.c
                )
                return self._build_signal(
                    ts_str,
                    state.current.c,
                    macd_c,
                    rsi_c,
                    partial=True,
                )
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
            if self._can_emit_macd_signal(state):
                result_msg = self._build_signal(
                    ts_str,
                    state.current.c,
                    state.closes,
                    self._rsi_closes(state, state.closes),
                    partial=False,
                )

        state.current_bucket = bucket
        state.current = Candle(o=price, h=price, l=price, c=price, v=qty)
        return result_msg
