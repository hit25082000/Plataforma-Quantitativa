import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from typing import Any

_DIST_DIR = Path(__file__).resolve().parent.parent
if str(_DIST_DIR) not in sys.path:
    sys.path.insert(0, str(_DIST_DIR))

import profit_ocr_service

_ROOT = Path(__file__).resolve().parents[2]
OVERLAY_UPDATE_SCHEMA_PATH = _ROOT / "docs" / "contracts" / "overlay-update-v1.json"
OVERLAY_UPDATE_FIXTURE_PATH = _ROOT / "docs" / "contracts" / "fixtures" / "overlay-update-demo.json"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise AssertionError(f"{path} did not contain a JSON object")
    return data


class TestProfitOcrService(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("PQ_OCR_TRACE_PATH", None)
        profit_ocr_service.OCR_TRACE_PATH = ""

    def test_build_frame_debug_contains_core_fields(self) -> None:
        profit_ocr_service.axis_manager.status = "STABLE"
        profit_ocr_service.axis_manager.bad_frames = 2
        out = profit_ocr_service._build_frame_debug(
            seq=7,
            window={"left": 1, "top": 2},
            chart={"left": 1, "top": 20, "width": 300, "height": 400},
            labels=[{"value": 100.0, "y_screen": 10.0}, {"value": 120.0, "y_screen": 30.0}],
            diagnostics={"raw_labels": 4, "kept_labels": 3},
            axis_fit={"slope": -0.2, "intercept": 140.0},
            axis={"slope": -0.2, "intercept": 140.0},
            lines=[{"value": 110.0, "y_screen": 22}],
            analysis_sample={"text": "abc"},
            status="ok",
        )

        self.assertEqual(out["seq"], 7)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["labels_count"], 2)
        self.assertEqual(out["axis_status"], "STABLE")
        self.assertEqual(out["bad_frames"], 2)
        self.assertEqual(out["line_count"], 1)
        self.assertIn("render_indicators", out)
        self.assertIn("session_id", out)
        self.assertIn("ts", out)

    def test_append_trace_line_writes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ocr_overlay_trace.jsonl")
            os.environ["PQ_OCR_TRACE_PATH"] = path
            profit_ocr_service.OCR_TRACE_PATH = path
            profit_ocr_service.AUDIT_TRAIL.trace_path = path
            profit_ocr_service.AUDIT_TRAIL._session_header_written = False
            profit_ocr_service._append_trace_line({"seq": 1, "status": "ok"})

            with open(path, "r", encoding="utf-8") as fh:
                rows = [json.loads(line) for line in fh if line.strip()]

        self.assertEqual(rows[0]["event"], "session_start")
        self.assertEqual(rows[1], {"seq": 1, "status": "ok"})

    def test_debug_endpoint_returns_last_frame(self) -> None:
        profit_ocr_service.state["status"] = "ok"
        profit_ocr_service.state["axis_status"] = "STABLE"
        profit_ocr_service.state["axis_source"] = "ocr"
        profit_ocr_service.state["axis_bad_frames"] = 0
        profit_ocr_service.state["axis"] = {"slope": -0.1, "intercept": 120.0}
        profit_ocr_service.state["last_frame"] = {"seq": 3, "status": "ok"}

        body = asyncio.run(profit_ocr_service.get_debug())

        data = body["data"]
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["axis_status"], "STABLE")
        self.assertEqual(data["last_frame"]["seq"], 3)
        self.assertEqual(data["axis"]["intercept"], 120.0)
        self.assertIn("debug_visual", data)

    def test_overlay_update_data_contract_blocks(self) -> None:
        profit_ocr_service.state["status"] = "ok"
        profit_ocr_service.state["targets"] = [{"value": 100.0, "label": "POC"}]
        profit_ocr_service.state["lines"] = [{"value": 100.0, "y_screen": 200}]
        profit_ocr_service.state["axis_status"] = "STABLE"
        profit_ocr_service.state["axis_source"] = "ocr"
        profit_ocr_service.state["axis_bad_frames"] = 2
        profit_ocr_service.state["chart_rect"] = {"top": 10, "height": 500}
        profit_ocr_service.state["y_min"] = 99.0
        profit_ocr_service.state["y_max"] = 101.0

        data = profit_ocr_service._build_overlay_update_data()

        self.assertIn("status", data)
        self.assertIn("structured", data)
        self.assertIn("status", data["structured"])
        self.assertIn("axis", data["structured"])
        self.assertIn("lines", data["structured"])
        self.assertIn("histogram", data["structured"])
        self.assertIn("debug_visual", data["structured"])
        self.assertIn("lines", data)
        self.assertEqual(data["status"], "ok")
        self.assertIsInstance(data["lines"], list)
        self.assertEqual(data["y_min"], 99.0)
        self.assertEqual(data["y_max"], 101.0)
        self.assertEqual(data["axis_status"], "STABLE")
        self.assertEqual(data["axis_source"], "ocr")
        self.assertEqual(data["bad_frames"], 2)
        self.assertIn("ocr_labels", data["structured"]["axis"])
        self.assertIn("regression", data["structured"]["axis"])
        self.assertIn("labels_count", data["structured"]["axis"])
        self.assertIn("confidence", data)
        self.assertIn("residual_px", data)
        self.assertIsInstance(data["overlay_target"], list)
        # Espelhos entre formato legado e bloco estruturado.
        self.assertEqual(data["status"], data["structured"]["status"]["state"])
        self.assertEqual(data["lines"], data["structured"]["lines"]["items"])
        self.assertEqual(data["axis_deltas"], data["structured"]["histogram"]["axis_deltas"])
        self.assertEqual(data["axis_diagnostics"], data["structured"]["histogram"]["axis_diagnostics"])
        self.assertEqual(data["analysis_roi"], data["structured"]["status"]["analysis_roi"])
        self.assertEqual(data["analysis_sample"], data["structured"]["status"]["analysis_sample"])

    def test_overlay_update_fixture_matches_contract_shape(self) -> None:
        schema = _load_json(OVERLAY_UPDATE_SCHEMA_PATH)
        fixture = _load_json(OVERLAY_UPDATE_FIXTURE_PATH)

        self.assertEqual(schema["title"], "overlay_update")
        required = set(schema["required"])
        self.assertTrue(required.issubset(fixture.keys()))

        self.assertIsInstance(fixture["status"], str)
        self.assertIsInstance(fixture["lines"], list)
        self.assertGreaterEqual(len(fixture["lines"]), 1)
        self.assertIn("structured", fixture)
        self.assertIn("status", fixture["structured"])
        self.assertIn("axis", fixture["structured"])
        self.assertIn("lines", fixture["structured"])
        self.assertIn("histogram", fixture["structured"])
        self.assertIn("debug_visual", fixture["structured"])
        self.assertIn("overlay_target", fixture["structured"])

        self.assertIn("state", fixture["structured"]["status"])
        self.assertIn("axis_locked", fixture["structured"]["status"])
        self.assertIn("timestamp", fixture["structured"]["status"])

        self.assertIn("axis_status", fixture["structured"]["axis"])
        self.assertIn("axis_source", fixture["structured"]["axis"])
        self.assertIn("confidence", fixture["structured"]["axis"])
        self.assertIn("residual_px", fixture["structured"]["axis"])
        self.assertIn("max_error_px", fixture["structured"]["axis"])
        self.assertIn("bad_frames", fixture["structured"]["axis"])
        self.assertIn("pending_count", fixture["structured"]["axis"])
        self.assertIn("ocr_labels", fixture["structured"]["axis"])
        self.assertIn("regression", fixture["structured"]["axis"])

        self.assertIn("items", fixture["structured"]["lines"])
        self.assertIsInstance(fixture["structured"]["lines"]["items"], list)
        self.assertGreaterEqual(len(fixture["structured"]["lines"]["items"]), 1)
        self.assertIn("visual_limits", fixture["structured"]["lines"])

        self.assertIn("axis_deltas", fixture["structured"]["histogram"])
        self.assertIn("axis_diagnostics", fixture["structured"]["histogram"])
        self.assertIn("chart_bounds", fixture["structured"]["debug_visual"])

        self.assertIsInstance(fixture["overlay_target"], list)
        self.assertGreaterEqual(len(fixture["overlay_target"]), 1)

        # Espelhos legados para compatibilidade retroativa.
        self.assertEqual(fixture["status"], fixture["structured"]["status"]["state"])
        self.assertEqual(fixture["lines"], fixture["structured"]["lines"]["items"])
        self.assertEqual(fixture["y_min"], fixture["structured"]["lines"]["visual_limits"]["y_min"])
        self.assertEqual(fixture["y_max"], fixture["structured"]["lines"]["visual_limits"]["y_max"])
        self.assertEqual(fixture["axis_deltas"], fixture["structured"]["histogram"]["axis_deltas"])
        self.assertEqual(fixture["axis_diagnostics"], fixture["structured"]["histogram"]["axis_diagnostics"])
        self.assertEqual(fixture["analysis_roi"], fixture["structured"]["status"]["analysis_roi"])
        self.assertEqual(fixture["analysis_sample"], fixture["structured"]["status"]["analysis_sample"])
        self.assertEqual(fixture["ts"], fixture["structured"]["status"]["timestamp"])
        self.assertEqual(fixture["axis_status"], fixture["structured"]["axis"]["axis_status"])
        self.assertEqual(fixture["axis_source"], fixture["structured"]["axis"]["axis_source"])
        self.assertEqual(fixture["confidence"], fixture["structured"]["axis"]["confidence"])
        self.assertEqual(fixture["residual_px"], fixture["structured"]["axis"]["residual_px"])
        self.assertEqual(fixture["max_error_px"], fixture["structured"]["axis"]["max_error_px"])
        self.assertEqual(fixture["bad_frames"], fixture["structured"]["axis"]["bad_frames"])
        self.assertEqual(fixture["pending_count"], fixture["structured"]["axis"]["pending_count"])

    def test_overlay_update_schema_defines_frozen_axis_and_line_contracts(self) -> None:
        schema = _load_json(OVERLAY_UPDATE_SCHEMA_PATH)
        defs = schema["$defs"]

        self.assertIn("axis_label", defs)
        self.assertIn("axis_candidate", defs)
        self.assertIn("stable_axis", defs)
        self.assertIn("overlay_line", defs)

        axis_required = set(defs["axis_candidate"]["required"])
        self.assertTrue({"slope", "intercept", "value_per_px", "confidence", "labels_count", "residual_px", "max_error_px"}.issubset(axis_required))

        line_required = set(defs["overlay_line"]["required"])
        self.assertTrue({"value", "y_screen"}.issubset(line_required))

    def test_overlay_update_schema_requires_dual_mode_fields(self) -> None:
        schema = _load_json(OVERLAY_UPDATE_SCHEMA_PATH)
        required = set(schema["required"])
        self.assertTrue({"status", "lines", "structured"}.issubset(required))
        self.assertTrue({"axis_status", "axis_source", "bad_frames"}.issubset(required))
        structured_required = set(schema["$defs"]["structured_block"]["required"])
        self.assertTrue(
            {"status", "axis", "lines", "histogram", "debug_visual", "overlay_target"}.issubset(
                structured_required
            )
        )

    def test_overlay_update_fixture_supports_structured_only_consumption(self) -> None:
        fixture = _load_json(OVERLAY_UPDATE_FIXTURE_PATH)
        structured_only = fixture["structured"]

        status_state = structured_only["status"]["state"]
        lines_items = structured_only["lines"]["items"]
        y_min = structured_only["lines"]["visual_limits"]["y_min"]
        y_max = structured_only["lines"]["visual_limits"]["y_max"]
        axis_deltas = structured_only["histogram"]["axis_deltas"]
        axis_diag = structured_only["histogram"]["axis_diagnostics"]
        axis_status = structured_only["axis"]["axis_status"]
        axis_source = structured_only["axis"]["axis_source"]
        bad_frames = structured_only["axis"]["bad_frames"]

        self.assertEqual(status_state, fixture["structured"]["status"]["state"])
        self.assertEqual(lines_items, fixture["structured"]["lines"]["items"])
        self.assertEqual(y_min, fixture["structured"]["lines"]["visual_limits"]["y_min"])
        self.assertEqual(y_max, fixture["structured"]["lines"]["visual_limits"]["y_max"])
        self.assertEqual(axis_deltas, fixture["structured"]["histogram"]["axis_deltas"])
        self.assertEqual(axis_diag, fixture["structured"]["histogram"]["axis_diagnostics"])
        self.assertEqual(axis_status, fixture["axis_status"])
        self.assertEqual(axis_source, fixture["axis_source"])
        self.assertEqual(bad_frames, fixture["bad_frames"])

    def test_overlay_update_fixture_supports_legacy_fields_consumption(self) -> None:
        fixture = _load_json(OVERLAY_UPDATE_FIXTURE_PATH)
        legacy = {
            "status": fixture["status"],
            "lines": fixture["lines"],
            "y_min": fixture["y_min"],
            "y_max": fixture["y_max"],
            "axis_deltas": fixture["axis_deltas"],
            "axis_diagnostics": fixture["axis_diagnostics"],
            "axis_status": fixture["axis_status"],
            "axis_source": fixture["axis_source"],
            "bad_frames": fixture["bad_frames"],
            "analysis_roi": fixture["analysis_roi"],
            "analysis_sample": fixture["analysis_sample"],
        }

        self.assertEqual(legacy["status"], fixture["structured"]["status"]["state"])
        self.assertEqual(legacy["lines"], fixture["structured"]["lines"]["items"])
        self.assertEqual(legacy["y_min"], fixture["structured"]["lines"]["visual_limits"]["y_min"])
        self.assertEqual(legacy["y_max"], fixture["structured"]["lines"]["visual_limits"]["y_max"])
        self.assertEqual(legacy["axis_deltas"], fixture["structured"]["histogram"]["axis_deltas"])
        self.assertEqual(
            legacy["axis_diagnostics"],
            fixture["structured"]["histogram"]["axis_diagnostics"],
        )
        self.assertEqual(legacy["axis_status"], fixture["structured"]["axis"]["axis_status"])
        self.assertEqual(legacy["axis_source"], fixture["structured"]["axis"]["axis_source"])
        self.assertEqual(legacy["bad_frames"], fixture["structured"]["axis"]["bad_frames"])
        self.assertEqual(legacy["analysis_roi"], fixture["structured"]["status"]["analysis_roi"])
        self.assertEqual(legacy["analysis_sample"], fixture["structured"]["status"]["analysis_sample"])

    def test_ocr_overlay_alias_endpoints_available(self) -> None:
        profit_ocr_service.state["status"] = "ok"

        debug_body = asyncio.run(profit_ocr_service.get_debug_api())
        status_body = asyncio.run(profit_ocr_service.get_status_api())
        freeze_body = asyncio.run(profit_ocr_service.freeze_axis_api())
        unfreeze_body = asyncio.run(profit_ocr_service.unfreeze_axis_api())
        recalibrate_body = asyncio.run(profit_ocr_service.recalibrate_axis_api())

        self.assertTrue(debug_body["ok"])
        self.assertTrue(status_body["ok"])
        self.assertTrue(freeze_body["ok"])
        self.assertTrue(unfreeze_body["ok"])
        self.assertTrue(recalibrate_body["ok"])
        self.assertEqual(freeze_body["endpoint"], "freeze")
        self.assertEqual(unfreeze_body["endpoint"], "unfreeze")
        self.assertEqual(recalibrate_body["endpoint"], "recalibrate")

    def test_manual_calibration_alias_applies_manual_locked_axis(self) -> None:
        body = profit_ocr_service.ManualAxisBody(
            points=[
                profit_ocr_service.ManualAxisPoint(value=100.0, y_screen=200.0),
                profit_ocr_service.ManualAxisPoint(value=120.0, y_screen=100.0),
            ]
        )
        out = asyncio.run(profit_ocr_service.manual_calibration_api(body))
        self.assertTrue(out["ok"])
        self.assertEqual(out["endpoint"], "manual_calibration")
        self.assertEqual(profit_ocr_service.axis_manager.status, "MANUAL_LOCKED")
        self.assertEqual(profit_ocr_service.state["axis_source"], "manual")

    def test_config_endpoint_standard_response(self) -> None:
        out = asyncio.run(profit_ocr_service.get_config())
        self.assertTrue(out["ok"])
        self.assertEqual(out["endpoint"], "config")
        self.assertGreaterEqual(out["data"]["ws_publish_min_ms"], 100)

    def test_parse_price_label_conservative_for_winfut(self) -> None:
        self.assertEqual(profit_ocr_service.parse_price_label("185.240", "WINFUT"), 185240.0)
        self.assertIsNone(profit_ocr_service.parse_price_label("12.34", "WINFUT"))
        self.assertIsNone(profit_ocr_service.parse_price_label("185243", "WINFUT"))

    def test_sanitize_axis_labels_rejects_non_monotonic_or_tick(self) -> None:
        labels = [
            {"value": 185250.0, "y_screen": 10.0},
            {"value": 185245.0, "y_screen": 30.0},
            {"value": 185247.0, "y_screen": 50.0},
            {"value": 185260.0, "y_screen": 70.0},
        ]
        filtered, diag = profit_ocr_service.sanitize_axis_labels(labels, symbol="WINFUT")
        self.assertGreaterEqual(diag.get("rejected_dedupe_or_tick", 0), 1)
        self.assertGreaterEqual(diag.get("rejected_monotonic", 0), 1)
        self.assertGreaterEqual(len(filtered), 2)

    def test_fit_value_axis_returns_residual_max_error_confidence(self) -> None:
        labels = [
            {"value": 185300.0, "y_screen": 10.0},
            {"value": 185290.0, "y_screen": 20.0},
            {"value": 185280.0, "y_screen": 30.0},
            {"value": 185270.0, "y_screen": 40.0},
            {"value": 185000.0, "y_screen": 41.0},
        ]
        fit = profit_ocr_service.fit_value_axis(labels)
        self.assertIsNotNone(fit)
        assert fit is not None
        self.assertIn("residual_px", fit)
        self.assertIn("max_error_px", fit)
        self.assertIn("confidence", fit)
        self.assertGreaterEqual(fit["confidence"], 0.0)
        self.assertLessEqual(fit["confidence"], 1.0)

    def test_axis_manager_requires_8_frames_for_large_jump(self) -> None:
        mgr = profit_ocr_service.StableAxisManager()
        base_candidate = {
            "slope": -1.0,
            "intercept": 200.0,
            "value_per_px": 1.0,
            "residual_px": 0.4,
            "max_error_px": 1.2,
            "confidence": 0.95,
            "labels_count": 4,
            "inliers_count": 4,
            "tick_valid": True,
            "monotonic_valid": True,
            "value_min": 100.0,
            "value_max": 180.0,
            "y_min": 20.0,
            "y_max": 120.0,
        }
        self.assertIsNotNone(mgr.feed(base_candidate))
        self.assertEqual(mgr.status, "STABLE")

        jump_candidate = dict(base_candidate)
        jump_candidate["intercept"] = 80.0
        for _ in range(7):
            out = mgr.feed(jump_candidate)
            self.assertIsNotNone(out)
            self.assertEqual(mgr.status, "RECALIBRATING")
        out = mgr.feed(jump_candidate)
        self.assertIsNotNone(out)
        self.assertEqual(mgr.status, "STABLE")
        self.assertEqual(mgr.pending_count, 0)

    def test_axis_manager_bad_frames_goes_frozen(self) -> None:
        mgr = profit_ocr_service.StableAxisManager()
        valid = {
            "slope": -1.0,
            "intercept": 200.0,
            "value_per_px": 1.0,
            "residual_px": 0.4,
            "max_error_px": 1.2,
            "confidence": 0.95,
            "labels_count": 4,
            "inliers_count": 4,
            "tick_valid": True,
            "monotonic_valid": True,
            "value_min": 100.0,
            "value_max": 180.0,
            "y_min": 20.0,
            "y_max": 120.0,
        }
        self.assertIsNotNone(mgr.feed(valid))
        invalid = dict(valid)
        invalid["confidence"] = 0.01
        for _ in range(profit_ocr_service.AXIS_MAX_BAD_FRAMES):
            self.assertIsNotNone(mgr.feed(invalid))
        self.assertEqual(mgr.status, "FROZEN")

    def test_axis_manager_isolated_bad_frame_recovers_without_freeze(self) -> None:
        mgr = profit_ocr_service.StableAxisManager()
        valid = {
            "slope": -1.0,
            "intercept": 200.0,
            "value_per_px": 1.0,
            "residual_px": 0.4,
            "max_error_px": 1.2,
            "confidence": 0.95,
            "labels_count": 4,
            "inliers_count": 4,
            "tick_valid": True,
            "monotonic_valid": True,
            "value_min": 100.0,
            "value_max": 180.0,
            "y_min": 20.0,
            "y_max": 120.0,
        }
        baseline = mgr.feed(valid)
        self.assertIsNotNone(baseline)

        bad_frame = dict(valid)
        bad_frame["confidence"] = 0.01
        recovered_from_bad = mgr.feed(bad_frame)
        self.assertIsNotNone(recovered_from_bad)
        self.assertEqual(mgr.status, "SUSPECT")
        self.assertEqual(mgr.bad_frames, 1)

        good_again = mgr.feed(valid)
        self.assertIsNotNone(good_again)
        self.assertEqual(mgr.status, "STABLE")
        self.assertEqual(mgr.bad_frames, 0)

    def test_axis_manager_recalibrating_after_frozen_unfreeze(self) -> None:
        mgr = profit_ocr_service.StableAxisManager()
        valid = {
            "slope": -1.0,
            "intercept": 200.0,
            "value_per_px": 1.0,
            "residual_px": 0.4,
            "max_error_px": 1.2,
            "confidence": 0.95,
            "labels_count": 4,
            "inliers_count": 4,
            "tick_valid": True,
            "monotonic_valid": True,
            "value_min": 100.0,
            "value_max": 180.0,
            "y_min": 20.0,
            "y_max": 120.0,
        }
        self.assertIsNotNone(mgr.feed(valid))

        bad_frame = dict(valid)
        bad_frame["confidence"] = 0.01
        for _ in range(profit_ocr_service.AXIS_MAX_BAD_FRAMES):
            self.assertIsNotNone(mgr.feed(bad_frame))
        self.assertEqual(mgr.status, "FROZEN")

        mgr.unfreeze()
        self.assertEqual(mgr.status, "RECALIBRATING")
        self.assertEqual(mgr.bad_frames, 0)

        big_jump = dict(valid)
        big_jump["intercept"] = 80.0
        for _ in range(7):
            self.assertIsNotNone(mgr.feed(big_jump))
            self.assertEqual(mgr.status, "RECALIBRATING")
        self.assertIsNotNone(mgr.feed(big_jump))
        self.assertEqual(mgr.status, "STABLE")

    def test_apply_line_y_smoothing_deadband_and_ema(self) -> None:
        old_alpha = profit_ocr_service.LINE_Y_SMOOTH_ALPHA
        old_deadband = profit_ocr_service.LINE_Y_DEADBAND_PX
        old_snap = profit_ocr_service.LINE_Y_SNAP_PX
        old_chart = profit_ocr_service.state.get("chart_rect")
        old_smooth = profit_ocr_service.state.get("_line_y_smooth")
        old_key = profit_ocr_service.state.get("_smooth_key")
        try:
            profit_ocr_service.LINE_Y_SMOOTH_ALPHA = 0.5
            profit_ocr_service.LINE_Y_DEADBAND_PX = 1.5
            profit_ocr_service.LINE_Y_SNAP_PX = 50.0
            profit_ocr_service.state["chart_rect"] = {"height": 400}
            profit_ocr_service.state["_line_y_smooth"] = {}
            profit_ocr_service.state["_smooth_key"] = None

            targets = [{"value": 100.0, "label": "POC"}]
            lines = [{"value": 100.0, "label": "POC", "y_screen": 100}]
            profit_ocr_service.apply_line_y_smoothing(lines, targets)
            self.assertEqual(lines[0]["y_screen"], 100)

            # Dentro do deadband: mantém valor suavizado anterior.
            lines = [{"value": 100.0, "label": "POC", "y_screen": 101}]
            profit_ocr_service.apply_line_y_smoothing(lines, targets)
            self.assertEqual(lines[0]["y_screen"], 100)

            # Fora do deadband e abaixo do snap: aplica EMA (0.5 => 103).
            lines = [{"value": 100.0, "label": "POC", "y_screen": 106}]
            profit_ocr_service.apply_line_y_smoothing(lines, targets)
            self.assertEqual(lines[0]["y_screen"], 103)
        finally:
            profit_ocr_service.LINE_Y_SMOOTH_ALPHA = old_alpha
            profit_ocr_service.LINE_Y_DEADBAND_PX = old_deadband
            profit_ocr_service.LINE_Y_SNAP_PX = old_snap
            profit_ocr_service.state["chart_rect"] = old_chart
            if old_smooth is None:
                profit_ocr_service.state.pop("_line_y_smooth", None)
            else:
                profit_ocr_service.state["_line_y_smooth"] = old_smooth
            if old_key is None:
                profit_ocr_service.state.pop("_smooth_key", None)
            else:
                profit_ocr_service.state["_smooth_key"] = old_key

    def test_should_publish_overlay_update_change_and_throttle(self) -> None:
        old_min_ms = profit_ocr_service.WS_PUBLISH_MIN_MS
        old_last_ts = profit_ocr_service.state.get("last_ws_emit_ts")
        old_last_hash = profit_ocr_service.state.get("last_ws_visual_hash")
        try:
            profit_ocr_service.WS_PUBLISH_MIN_MS = 100
            profit_ocr_service.state["last_ws_emit_ts"] = 0
            profit_ocr_service.state["last_ws_visual_hash"] = ""
            payload = {
                "status": "ok",
                "axis": {"slope": -1.0, "intercept": 200.0},
                "lines": [{"value": 100.0, "y_screen": 120}],
                "histogram": {"levels": []},
                "overlay_target": [{"value": 100.0, "label": "POC"}],
            }
            changed_payload = dict(payload)
            changed_payload["lines"] = [{"value": 100.0, "y_screen": 121}]

            with mock.patch.object(profit_ocr_service.time, "time", return_value=1.0):
                self.assertTrue(profit_ocr_service._should_publish_overlay_update(payload))
            with mock.patch.object(profit_ocr_service.time, "time", return_value=1.02):
                self.assertFalse(profit_ocr_service._should_publish_overlay_update(payload))
            with mock.patch.object(profit_ocr_service.time, "time", return_value=1.20):
                self.assertFalse(profit_ocr_service._should_publish_overlay_update(payload))
            with mock.patch.object(profit_ocr_service.time, "time", return_value=1.21):
                self.assertTrue(profit_ocr_service._should_publish_overlay_update(changed_payload))
        finally:
            profit_ocr_service.WS_PUBLISH_MIN_MS = old_min_ms
            profit_ocr_service.state["last_ws_emit_ts"] = old_last_ts
            profit_ocr_service.state["last_ws_visual_hash"] = old_last_hash

    def test_compute_axis_deltas_coalesces_when_compressed(self) -> None:
        labels = [
            {"value": 185300.0, "y_screen": 10.0},
            {"value": 185295.0, "y_screen": 12.0},
            {"value": 185290.0, "y_screen": 14.0},
            {"value": 185285.0, "y_screen": 16.0},
        ]
        out = profit_ocr_service.compute_axis_deltas(labels)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertTrue(out["compressed_scale"])
        self.assertLessEqual(
            len(out["delta_intervals_coalesced"]),
            len(out["delta_intervals"]),
        )

    def test_drop_put_latest_keeps_only_most_recent_item(self) -> None:
        q = asyncio.Queue(maxsize=1)
        profit_ocr_service._drop_put_latest(q, {"seq": 1})
        profit_ocr_service._drop_put_latest(q, {"seq": 2})
        self.assertEqual(q.qsize(), 1)
        item = q.get_nowait()
        self.assertEqual(item["seq"], 2)

    def test_should_skip_render_uses_fingerprint_diff(self) -> None:
        profit_ocr_service.state["last_render_hash"] = ""
        profit_ocr_service.state["last_render_targets_hash"] = "[]"
        frame = {
            "status": "ok",
            "axis_status": "STABLE",
            "axis_source": "ocr",
            "axis": {"slope": -0.1, "intercept": 10.0},
            "chart_rect": {"left": 1, "top": 2, "width": 100, "height": 100},
            "labels": [{"value": 10.0, "y_screen": 10.0}, {"value": 0.0, "y_screen": 20.0}],
        }
        self.assertFalse(profit_ocr_service._should_skip_render(frame))
        self.assertTrue(profit_ocr_service._should_skip_render(frame))


if __name__ == "__main__":
    unittest.main()
