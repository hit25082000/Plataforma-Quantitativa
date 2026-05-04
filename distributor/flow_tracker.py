"""Flow tracker: ranking and flow inversion detection from trades."""

from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

MONITORED_AGENTS = ["UBS", "BTG", "GOLDM"]
WINDOW_MS = 300_000  # 5 min


@dataclass
class TradeEntry:
    contributions: dict[str, int]
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
        self._current_deltas: dict[str, int] = {name: 0 for name in self._monitored}

    def on_trade(self, msg: dict[str, Any]) -> list[dict[str, Any]]:
        """Process trade; return list of flow_inversion messages (if any)."""
        topic = msg.get("topic")
        if topic != "market" or msg.get("type") != "trade":
            return []

        ts_str = msg.get("ts") or ""
        ts_ms = _parse_ts(ts_str)
        qty = int(msg.get("qty") or 0)
        net_aggression = int(msg.get("net_aggression") or 0)
        buy_agent = (msg.get("buy_agent_short_name") or msg.get("buy_agent_name") or "").strip()
        sell_agent = (msg.get("sell_agent_short_name") or msg.get("sell_agent_name") or "").strip()

        trade_contrib: dict[str, int] = {}
        if net_aggression > 0 and buy_agent in self._current_deltas:
            trade_contrib[buy_agent] = trade_contrib.get(buy_agent, 0) + qty
        elif net_aggression < 0 and sell_agent in self._current_deltas:
            trade_contrib[sell_agent] = trade_contrib.get(sell_agent, 0) - qty

        if trade_contrib:
            for agent, delta in trade_contrib.items():
                self._current_deltas[agent] += delta
        self._trade_log.append(TradeEntry(contributions=trade_contrib, ts_ms=ts_ms))

        # Prune old entries
        while self._trade_log and ts_ms - self._trade_log[0].ts_ms > self._window_ms:
            old = self._trade_log.popleft()
            for agent, delta in old.contributions.items():
                if agent in self._current_deltas:
                    self._current_deltas[agent] -= delta

        deltas = dict(self._current_deltas)

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
