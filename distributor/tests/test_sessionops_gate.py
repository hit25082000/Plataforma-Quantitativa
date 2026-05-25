from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

_DIST_DIR = Path(__file__).resolve().parent.parent
if str(_DIST_DIR) not in sys.path:
    sys.path.insert(0, str(_DIST_DIR))

from sessionops import SessionOpsService


class TestSessionOpsGate(unittest.TestCase):
    def test_gate_fails_when_ws_stale(self) -> None:
        async def _run() -> None:
            td = Path(tempfile.mkdtemp(prefix="sessionops-gate-"))
            svc = SessionOpsService(logs_root=td, component="distributor", build="test")

            async def fake_status() -> dict:
                return {"ok": True}

            async def fake_debug() -> dict:
                return {"ok": True, "axis": {"status": "STABLE"}, "geometry": {"drift_steps": []}}

            report = await svc.run_gate(
                distributor_base_url="http://127.0.0.1:9",
                ocr_status_fetcher=fake_status,
                ocr_debug_fetcher=fake_debug,
                continuity_seconds=0.2,
                max_ws_stale_seconds=0.1,
            )
            self.assertFalse(report["ok"])
            self.assertIn("overlay_ws_stale", report["failures"])

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
