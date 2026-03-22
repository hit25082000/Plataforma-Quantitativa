"""Agente 007: estado em tempo real (regras determinísticas) + snapshot para chat."""

from __future__ import annotations

import json
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Literal, Optional

from config import (
    AGENT007_BREAKOUT_COOLDOWN_MS,
    AGENT007_BROADCAST_MIN_MS,
    AGENT007_VWAP_EPSILON_PCT,
    AGENT007_WEIS_MODE,
)

Signal = Literal["green", "red", "neutral"]
WeisSide = Literal["buy", "sell", "unknown"]
PriceVs = Literal["above", "below", "at"]
WeisMode = Literal["proxy", "ocr", "manual"]


def _parse_ts_ms(ts: str) -> float:
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp() * 1000
    except Exception:
        return 0.0


@dataclass
class WeisWaveProvider:
    """Fase 1: proxy MACD + confirmação por net_aggression. OCR/manual: atualizar _manual_side."""

    mode: WeisMode = "proxy"
    _last_macd_direction: Optional[str] = None
    _manual_side: WeisSide = "unknown"

    def on_macd(self, msg: Dict[str, Any]) -> None:
        d = msg.get("direction")
        if d in ("buy", "sell"):
            self._last_macd_direction = d

    def set_manual_side(self, side: str) -> None:
        s = str(side).lower().strip()
        if s in ("buy", "sell", "unknown"):
            self._manual_side = s  # type: ignore[assignment]

    def side_from_trade(self, net_aggression: int) -> WeisSide:
        if self.mode == "manual":
            return self._manual_side
        if self.mode == "ocr":
            # Reservado: OCR alimenta via set_manual_side ou futuro handler
            return self._manual_side if self._manual_side != "unknown" else "unknown"
        # proxy
        if self._last_macd_direction == "buy":
            return "buy" if net_aggression > 0 else "unknown"
        if self._last_macd_direction == "sell":
            return "sell" if net_aggression < 0 else "unknown"
        if net_aggression > 0:
            return "buy"
        if net_aggression < 0:
            return "sell"
        return "unknown"


@dataclass
class Agent007Engine:
    """Máquina de estado por ticker; emite mensagens WS com throttle."""

    weis: WeisWaveProvider = field(default_factory=WeisWaveProvider)
    _ticker: str = ""
    _last_price: float = 0.0
    _vwap: float = 0.0
    _last_broadcast_mono: float = 0.0
    _last_state_hash: Optional[str] = None
    _vwap_compare_side: int = 0  # -1 below, 0 at, 1 above
    _last_breakout_up_ms: float = 0.0
    _last_breakout_down_ms: float = 0.0
    _agg_samples: Deque[tuple[float, int]] = field(default_factory=deque)
    _inversion_ts: Deque[float] = field(default_factory=deque)
    _recent_inversions: List[Dict[str, Any]] = field(default_factory=list)
    _alerts: List[Dict[str, Any]] = field(default_factory=list)
    _urgency_smoothed: float = 0.0
    _last_weis_side: WeisSide = "unknown"
    _last_price_vs: PriceVs = "at"
    _last_signal: Signal = "neutral"
    _last_entry_buy_valid: bool = True
    _last_entry_filter_reason: Optional[str] = None

    def __post_init__(self) -> None:
        self.weis.mode = AGENT007_WEIS_MODE  # type: ignore[assignment]

    def reset(self) -> None:
        self._ticker = ""
        self._last_price = 0.0
        self._vwap = 0.0
        self._last_broadcast_mono = 0.0
        self._last_state_hash = None
        self._vwap_compare_side = 0
        self._last_breakout_up_ms = 0.0
        self._last_breakout_down_ms = 0.0
        self._agg_samples.clear()
        self._inversion_ts.clear()
        self._recent_inversions.clear()
        self._alerts.clear()
        self._urgency_smoothed = 0.0
        self._last_weis_side = "unknown"
        self._last_price_vs = "at"
        self._last_signal = "neutral"
        self._last_entry_buy_valid = True
        self._last_entry_filter_reason = None
        self.weis._last_macd_direction = None
        self.weis._manual_side = "unknown"

    def set_manual_weis(self, side: str) -> None:
        if AGENT007_WEIS_MODE != "manual":
            return
        self.weis.set_manual_side(side)

    def on_macd(self, msg: Dict[str, Any]) -> None:
        self.weis.on_macd(msg)

    def on_flow_inversion(self, msg: Dict[str, Any]) -> None:
        ts_str = msg.get("ts") or ""
        ts_ms = _parse_ts_ms(ts_str)
        now = ts_ms or (time.monotonic() * 1000)
        self._inversion_ts.append(now)
        self._prune_deques(now)
        inv = {
            "agent_name": msg.get("agent_name"),
            "previous_delta": msg.get("previous_delta"),
            "current_delta": msg.get("current_delta"),
            "ts": ts_str,
        }
        self._recent_inversions.insert(0, inv)
        self._recent_inversions = self._recent_inversions[:5]

    def on_trade(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if msg.get("topic") != "market" or msg.get("type") != "trade":
            return None

        ticker = str(msg.get("ticker") or "")
        if self._ticker and ticker and ticker != self._ticker:
            self.reset()
        self._ticker = ticker

        price = float(msg.get("price") or 0)
        vwap = float(msg.get("vwap") or 0)
        net_agg = int(msg.get("net_aggression") or 0)
        ts_str = msg.get("ts") or ""

        self._last_price = price
        self._vwap = vwap if vwap > 0 else self._vwap

        ts_ms = _parse_ts_ms(ts_str) or (time.monotonic() * 1000)
        self._agg_samples.append((ts_ms, net_agg))
        self._prune_deques(ts_ms)

        weis_side = self.weis.side_from_trade(net_agg)
        price_vs, compare_side = self._price_vs_vwap(price, self._vwap)
        self._check_crossover(compare_side, ts_ms, ts_str)

        entry_buy_valid = True
        entry_reason: Optional[str] = None
        if weis_side == "buy" and price_vs == "below":
            entry_buy_valid = False
            entry_reason = "Compra Weis abaixo do médio (T&T) — possível defesa de varejo"

        signal = self._compute_signal(price_vs, weis_side)

        raw_urgency = self._compute_urgency(price, self._vwap, ts_ms)
        # histerese simples
        self._urgency_smoothed = self._urgency_smoothed * 0.85 + raw_urgency * 0.15

        self._last_weis_side = weis_side
        self._last_price_vs = price_vs
        self._last_signal = signal
        self._last_entry_buy_valid = entry_buy_valid
        self._last_entry_filter_reason = entry_reason

        state = {
            "topic": "agent007",
            "type": "state",
            "ticker": ticker,
            "last_price": price,
            "vwap": self._vwap,
            "urgency_0_100": int(round(min(100, max(0, self._urgency_smoothed)))),
            "signal": signal,
            "weis_side": weis_side,
            "weis_mode": self.weis.mode,
            "price_vs_vwap": price_vs,
            "entry_buy_valid": entry_buy_valid,
            "entry_filter_reason": entry_reason,
            "recent_inversions": list(self._recent_inversions[:3]),
            "alerts": list(self._alerts[-5:]),
            "ts": ts_str,
        }

        self._vwap_compare_side = compare_side
        return state

    def _prune_deques(self, now_ms: float) -> None:
        while self._agg_samples and now_ms - self._agg_samples[0][0] > 30_000:
            self._agg_samples.popleft()
        while self._inversion_ts and now_ms - self._inversion_ts[0] > 60_000:
            self._inversion_ts.popleft()

    def _price_vs_vwap(self, price: float, vwap: float) -> tuple[PriceVs, int]:
        if vwap <= 0 or price <= 0:
            return "at", 0
        eps = max(1e-12, vwap * (AGENT007_VWAP_EPSILON_PCT / 100.0))
        if price > vwap + eps:
            return "above", 1
        if price < vwap - eps:
            return "below", -1
        return "at", 0

    def _check_crossover(self, new_side: int, ts_ms: float, ts_str: str) -> None:
        old = self._vwap_compare_side
        if old == 0 and new_side != 0:
            # primeira leitura útil
            return
        if new_side == old:
            return
        # cruza para cima: estava abaixo ou no médio, agora acima
        if new_side == 1 and old <= 0:
            if ts_ms - self._last_breakout_up_ms >= AGENT007_BREAKOUT_COOLDOWN_MS:
                self._last_breakout_up_ms = ts_ms
                self._push_alert(
                    "breakout_up",
                    "Ágora entrou no fumo! (preço cruzou acima do médio T&T)",
                    ts_str,
                )
        elif new_side == -1 and old >= 0:
            if ts_ms - self._last_breakout_down_ms >= AGENT007_BREAKOUT_COOLDOWN_MS:
                self._last_breakout_down_ms = ts_ms
                self._push_alert(
                    "breakout_down",
                    "Preço cruzou abaixo do médio T&T",
                    ts_str,
                )

    def _push_alert(self, kind: str, text: str, ts: str) -> None:
        self._alerts.append({"kind": kind, "text": text, "ts": ts})
        self._alerts = self._alerts[-10:]

    def _compute_signal(self, price_vs: PriceVs, weis: WeisSide) -> Signal:
        if weis == "unknown":
            return "neutral"
        if price_vs == "above" and weis == "buy":
            return "green"
        if price_vs == "below" and weis == "sell":
            return "red"
        return "neutral"

    def _compute_urgency(self, price: float, vwap: float, now_ms: float) -> float:
        score = 0.0
        # Inversões últimos 60s
        inv_n = len(self._inversion_ts)
        score += min(45.0, inv_n * 15.0)

        # Distância ao médio (%)
        if vwap > 0 and price > 0:
            dist_pct = abs(price - vwap) / vwap * 100.0
            score += min(25.0, dist_pct * 8.0)

        # Variação de agressão acumulada na janela 30s
        if len(self._agg_samples) >= 2:
            total = sum(a for _, a in self._agg_samples)
            n = len(self._agg_samples)
            mean = total / n
            var = sum((a - mean) ** 2 for _, a in self._agg_samples) / n
            churn = math.sqrt(var)
            score += min(30.0, churn / 50.0 * 30.0)

        return min(100.0, score)

    def should_broadcast(self, state: Dict[str, Any]) -> bool:
        now = time.monotonic() * 1000
        # Preço/VWAP mudam todo trade — o frontend já recebe trades; aqui só
        # reemitimos quando a lógica (sinal, filtro, alertas, urgência) muda ou throttle.
        alerts = state.get("alerts") or []
        alerts_sig = [f'{a.get("kind","")}:{a.get("ts","")}' for a in alerts[-5:]]
        urg = int(state.get("urgency_0_100") or 0)
        h = json.dumps(
            {
                "urgency_bucket": urg // 5,
                "signal": state.get("signal"),
                "weis_side": state.get("weis_side"),
                "price_vs_vwap": state.get("price_vs_vwap"),
                "entry_buy_valid": state.get("entry_buy_valid"),
                "entry_filter_reason": state.get("entry_filter_reason"),
                "alerts_sig": alerts_sig,
            },
            sort_keys=True,
        )
        changed = h != self._last_state_hash
        self._last_state_hash = h
        if changed:
            self._last_broadcast_mono = now
            return True
        if now - self._last_broadcast_mono >= AGENT007_BROADCAST_MIN_MS:
            self._last_broadcast_mono = now
            return True
        return False

    def get_snapshot(self) -> Dict[str, Any]:
        """Snapshot para endpoint de chat (último estado após trades)."""
        return {
            "ticker": self._ticker,
            "last_price": self._last_price,
            "vwap": self._vwap,
            "urgency_0_100": int(round(min(100, max(0, self._urgency_smoothed)))),
            "signal": self._last_signal,
            "weis_side": self._last_weis_side,
            "weis_mode": self.weis.mode,
            "price_vs_vwap": self._last_price_vs,
            "entry_buy_valid": self._last_entry_buy_valid,
            "entry_filter_reason": self._last_entry_filter_reason,
            "recent_inversions": self._recent_inversions[:5],
            "alerts": self._alerts[-5:],
            "macd_direction": self.weis._last_macd_direction,
        }
