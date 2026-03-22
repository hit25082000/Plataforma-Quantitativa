"""Testes do Agente 007 (regras determinísticas)."""

import unittest

from agent_007 import Agent007Engine, WeisWaveProvider


class TestAgent007Engine(unittest.TestCase):
    def setUp(self) -> None:
        self.e = Agent007Engine()

    def test_entry_filter_weis_buy_below_vwap(self) -> None:
        self.e.weis._last_macd_direction = "buy"
        st = self.e.on_trade(
            {
                "topic": "market",
                "type": "trade",
                "ticker": "X",
                "price": 99.0,
                "qty": 1,
                "net_aggression": 5,
                "vwap": 100.0,
                "ts": "2026-01-01T12:00:01.000",
            },
        )
        assert st is not None
        self.assertFalse(st["entry_buy_valid"])
        self.assertIn("varejo", st["entry_filter_reason"] or "")

    def test_green_signal(self) -> None:
        self.e.weis._last_macd_direction = "buy"
        st = self.e.on_trade(
            {
                "topic": "market",
                "type": "trade",
                "ticker": "X",
                "price": 101.0,
                "qty": 1,
                "net_aggression": 3,
                "vwap": 100.0,
                "ts": "2026-01-01T12:00:02.000",
            },
        )
        assert st is not None
        self.assertEqual(st["signal"], "green")
        self.assertEqual(st["weis_side"], "buy")

    def test_red_signal(self) -> None:
        self.e.weis._last_macd_direction = "sell"
        st = self.e.on_trade(
            {
                "topic": "market",
                "type": "trade",
                "ticker": "X",
                "price": 99.0,
                "qty": 1,
                "net_aggression": -2,
                "vwap": 100.0,
                "ts": "2026-01-01T12:00:03.000",
            },
        )
        assert st is not None
        self.assertEqual(st["signal"], "red")

    def test_ticker_switch_resets(self) -> None:
        self.e.on_trade(
            {
                "topic": "market",
                "type": "trade",
                "ticker": "A",
                "price": 100.0,
                "qty": 1,
                "net_aggression": 1,
                "vwap": 100.0,
                "ts": "2026-01-01T12:00:00.000",
            },
        )
        self.assertEqual(self.e._ticker, "A")
        self.e.on_trade(
            {
                "topic": "market",
                "type": "trade",
                "ticker": "B",
                "price": 50.0,
                "qty": 1,
                "net_aggression": 0,
                "vwap": 50.0,
                "ts": "2026-01-01T12:00:01.000",
            },
        )
        self.assertEqual(self.e._ticker, "B")

    def test_weis_proxy_conflict_unknown(self) -> None:
        self.e.weis._last_macd_direction = "buy"
        st = self.e.on_trade(
            {
                "topic": "market",
                "type": "trade",
                "ticker": "X",
                "price": 101.0,
                "qty": 1,
                "net_aggression": -5,
                "vwap": 100.0,
                "ts": "2026-01-01T12:00:04.000",
            },
        )
        assert st is not None
        self.assertEqual(st["weis_side"], "unknown")


class TestWeisWaveProvider(unittest.TestCase):
    def test_manual_side(self) -> None:
        w = WeisWaveProvider(mode="manual")
        w.set_manual_side("sell")
        self.assertEqual(w.side_from_trade(99), "sell")


if __name__ == "__main__":
    unittest.main()
