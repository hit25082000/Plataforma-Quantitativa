from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import websocket_server
from candle_macd import CandleMacd, TickerState


def _closed_candles(count: int = 40) -> list[float]:
    return [100_000.0 + (i * 10.0) for i in range(count)]


def _renko_closes(brick: float, count: int = 40) -> list[float]:
    return [100_000.0 + (i * brick) for i in range(count)]


class TestIfrSeriesSwitch(unittest.TestCase):
    def test_renko_modes_reload_state_after_30m(self) -> None:
        for mode, brick in (("42r", 42.0), ("16r", 16.0)):
            with self.subTest(mode=mode):
                macd = CandleMacd()
                state = TickerState(
                    closes=_closed_candles(),
                    renko_ref=101_000.0,
                    renko_initialized=True,
                    renko_closes=_renko_closes(42.0),
                )
                macd._states["WINFUT"] = state
                load_calls: list[str] = []

                def fake_load_state(ticker: str, st: TickerState) -> None:
                    load_calls.append(ticker)
                    st.renko_ref = 100_000.0 + (brick * 39)
                    st.renko_initialized = True
                    st.renko_closes = _renko_closes(brick)

                macd._load_state = fake_load_state  # type: ignore[method-assign]

                macd.set_ifr_series("30m")
                self.assertEqual(state.renko_closes, [])

                macd.set_ifr_series(mode)
                snap = macd.warm_snapshot_message("WINFUT")

                self.assertEqual(load_calls, ["WINFUT"])
                self.assertIsNotNone(snap)
                assert snap is not None
                self.assertEqual(snap["ifr_series"], mode)
                self.assertEqual(snap["renko_brick_points"], brick)
                self.assertNotEqual(snap["rsi9"], 50.0)


class _FakeRouter:
    def __init__(self) -> None:
        self.series_calls: list[str] = []
        self.snapshot_tickers: list[str] = []

    def set_ifr_series(self, series: str) -> None:
        self.series_calls.append(series)

    def warm_macd_snapshot(self, ticker: str) -> dict[str, Any]:
        self.snapshot_tickers.append(ticker)
        series = self.series_calls[-1] if self.series_calls else "42r"
        return {
            "topic": "market",
            "type": "macd_signal",
            "ifr_series": series,
            "rsi9": 61.0,
            "rsi18": 62.0,
            "rsi30": 63.0,
        }


class TestWarmMacdEndpoint(unittest.TestCase):
    def test_warm_macd_applies_requested_series(self) -> None:
        previous_router = websocket_server.message_router
        fake_router = _FakeRouter()
        websocket_server.message_router = fake_router  # type: ignore[assignment]
        try:
            client = TestClient(websocket_server.create_app())
            response = client.get("/api/warm-macd?ticker=winfut&series=16r")
        finally:
            websocket_server.message_router = previous_router

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_router.series_calls, ["16r"])
        self.assertEqual(fake_router.snapshot_tickers, ["WINFUT"])
        self.assertEqual(response.json()["ifr_series"], "16r")


if __name__ == "__main__":
    unittest.main()
