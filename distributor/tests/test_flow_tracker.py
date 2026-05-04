"""FlowTracker: sigla da corretora tem prioridade sobre nome longo / placeholder."""

from __future__ import annotations

import unittest

from flow_tracker import FlowTracker


class TestFlowTrackerBrokerSigla(unittest.TestCase):
    def test_flow_inversion_agent_name_uses_short_not_hash_name(self) -> None:
        ft = FlowTracker(monitored_agents=["UBS"], window_ms=300_000)
        ft.on_trade(
            {
                "topic": "market",
                "type": "trade",
                "ts": "2026-05-04T14:00:00.000Z",
                "qty": 100,
                "net_aggression": 50,
                "buy_agent_name": "#12",
                "buy_agent_short_name": "UBS",
                "sell_agent_short_name": "OTH",
            }
        )
        invs = ft.on_trade(
            {
                "topic": "market",
                "type": "trade",
                "ts": "2026-05-04T14:00:01.000Z",
                "qty": 200,
                "net_aggression": -200,
                "buy_agent_short_name": "OTH",
                "sell_agent_name": "#99",
                "sell_agent_short_name": "UBS",
            }
        )
        ubs = [i for i in invs if i.get("type") == "flow_inversion" and i.get("agent_name") == "UBS"]
        self.assertTrue(ubs, "esperado inversão na chave UBS (sigla), não em #12/#99")


if __name__ == "__main__":
    unittest.main()
