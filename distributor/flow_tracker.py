"""Flow tracker: ranking and flow inversion detection from trades."""

from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

MONITORED_AGENTS = ["UBS", "BTG", "GOLDM"]
WINDOW_MS = 300_000  # 5 min


@dataclass
class TradeEntry:
    agent_buy: str
    agent_sell: str
    qty: int
    is_buy_aggression: bool  # net_aggression > 0 means buy aggression
    ts_ms: float


def _parse_ts(ts: str) -> float:
    """Parse ISO ts to ms since epoch (approximate)."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp() * 1000
    except Exception:
        return 0.0


class FlowTracker:
    def __init__(
        self,
        monitored_agents: Optional[list[str]] = None,
        window_ms: int = WINDOW_MS,
    ) -> None:
        self._monitored = list(monitored_agents or MONITORED_AGENTS)
        self._window_ms = window_ms
        self._trade_log: deque[TradeEntry] = deque()
        self._prev_deltas: dict[str, int] = {}

    def on_trade(self, msg: dict[str, Any]) -> list[dict[str, Any]]:
        """Process trade; return list of flow_inversion messages (if any)."""
        topic = msg.get("topic")
        if topic != "market" or msg.get("type") != "trade":
            return []

        ts_str = msg.get("ts") or ""
        ts_ms = _parse_ts(ts_str)
        qty = int(msg.get("qty") or 0)
        net_aggression = int(msg.get("net_aggression") or 0)
        buy_agent = (msg.get("buy_agent_name") or msg.get("buy_agent_short_name") or "").strip()
        sell_agent = (msg.get("sell_agent_name") or msg.get("sell_agent_short_name") or "").strip()

        self._trade_log.append(
            TradeEntry(
                agent_buy=buy_agent,
                agent_sell=sell_agent,
                qty=qty,
                is_buy_aggression=net_aggression > 0,
                ts_ms=ts_ms,
            )
        )

        # Prune old entries
        while self._trade_log and ts_ms - self._trade_log[0].ts_ms > self._window_ms:
            self._trade_log.popleft()

        # Compute deltas per monitored agent (buy aggression - sell aggression)
        deltas: dict[str, int] = {}
        for name in self._monitored:
            delta = 0
            for e in self._trade_log:
                if ts_ms - e.ts_ms > self._window_ms:
                    continue
                if e.agent_buy == name and e.is_buy_aggression:
                    delta += e.qty
                if e.agent_sell == name and not e.is_buy_aggression:
                    delta -= e.qty
            deltas[name] = delta

        # Detect inversions
        out: list[dict[str, Any]] = []
        for name, curr in deltas.items():
            prev = self._prev_deltas.get(name)
            if prev is not None and (prev > 0) != (curr > 0) and (prev != 0 or curr != 0):
                out.append({
                    "topic": "market",
                    "type": "flow_inversion",
                    "agent_name": name,
                    "previous_delta": prev,
                    "current_delta": curr,
                    "ts": ts_str,
                })
        self._prev_deltas = deltas
        return out
