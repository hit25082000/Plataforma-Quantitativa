import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from typing import Any
from PIL import Image

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
        profit_ocr_service.state["axis_status"] = "STABLE"
        profit_ocr_service.state["axis_source"] = "ocr"
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
        self.assertEqual(rows[1]["seq"], 1)
        self.assertEqual(rows[1]["status"], "ok")
        self.assertIn("session_id", rows[1])
        self.assertIn("render_indicators", rows[1])

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
        self.assertIsInstance(data["debug_visual"], dict)

    def test_overlay_update_data_contract_blocks(self) -> None:
        profit_ocr_service.state["status"] = "ok"
        profit_ocr_service.state["targets"] = [
            {"value": 100.0, "label": "POC"},
            {"value": 100.0, "label": "POC"},
            {"value": 101.0, "label": "VAH"},
        ]
        profit_ocr_service.state["lines"] = [{"value": 100.0, "y_screen": 200}]
        profit_ocr_service.state["axis_status"] = "STABLE"
        profit_ocr_service.state["axis_source"] = "ocr"
        profit_ocr_service.state["axis_bad_frames"] = 2
        profit_ocr_service.state["chart_rect"] = {"top": 10, "height": 500}
        profit_ocr_service.state["y_min"] = 99.0
        profit_ocr_service.state["y_max"] = 101.0

        data = profit_ocr_service._build_overlay_update_data()

        self.assertIn("status", data)
        self.assertIn("blocks", data)
        self.assertIn("structured", data)
        self.assertIn("status", data["structured"])
        self.assertIn("axis", data["structured"])
        self.assertIn("lines", data["structured"])
        self.assertIn("histogram", data["structured"])
        self.assertIn("debug_visual", data["structured"])
        self.assertIn("status", data["blocks"])
        self.assertIn("axis", data["blocks"])
        self.assertIn("lines", data["blocks"])
        self.assertIn("histogram", data["blocks"])
        self.assertIn("lines", data)
        self.assertEqual(data["status"], "ok")
        self.assertIsInstance(data["lines"], list)
        self.assertEqual(data["y_min"], 99.0)
        self.assertEqual(data["y_max"], 101.0)
        self.assertEqual(data["axis_status"], "STABLE")
        self.assertEqual(data["axis_source"], "ocr")
        self.assertEqual(data["source"], "ocr")
        self.assertEqual(data["bad_frames"], 2)
        self.assertEqual(data["pending_frames"], data["pending_count"])
        self.assertIn("ocr_labels", data["structured"]["axis"])
        self.assertIn("regression", data["structured"]["axis"])
        self.assertIn("labels_count", data["structured"]["axis"])
        self.assertIn("source", data["structured"]["axis"])
        self.assertIn("pending_frames", data["structured"]["axis"])
        self.assertIn("confidence", data)
        self.assertIn("residual_px", data)
        self.assertIsInstance(data["overlay_target"], list)
        self.assertEqual(len(data["overlay_target"]), 2)
        self.assertIn("max_targets_per_frame", data["structured"]["lines"]["visual_limits"])
        self.assertIn("max_lines_per_frame", data["structured"]["lines"]["visual_limits"])
        self.assertIn("max_axis_labels", data["structured"]["lines"]["visual_limits"])
        # Espelhos entre formato legado e bloco estruturado.
        self.assertEqual(data["status"], data["structured"]["status"]["state"])
        self.assertEqual(data["lines"], data["structured"]["lines"]["items"])
        self.assertEqual(data["axis_deltas"], data["structured"]["histogram"]["axis_deltas"])
        self.assertEqual(data["axis_diagnostics"], data["structured"]["histogram"]["axis_diagnostics"])
        self.assertEqual(data["analysis_roi"], data["structured"]["status"]["analysis_roi"])
        self.assertEqual(data["analysis_sample"], data["structured"]["status"]["analysis_sample"])
        self.assertEqual(data["blocks"], data["structured"])

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
        if "blocks" not in fixture:
            fixture["blocks"] = fixture["structured"]
        self.assertIn("blocks", fixture)
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
        visual_limits = fixture["structured"]["lines"]["visual_limits"]
        if "max_targets_per_frame" in visual_limits:
            self.assertIn("max_lines_per_frame", visual_limits)
            self.assertIn("max_axis_labels", visual_limits)

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
        if "source" in fixture and "source" in fixture["structured"]["axis"]:
            self.assertEqual(fixture["source"], fixture["structured"]["axis"]["source"])
        self.assertEqual(fixture["confidence"], fixture["structured"]["axis"]["confidence"])
        self.assertEqual(fixture["residual_px"], fixture["structured"]["axis"]["residual_px"])
        self.assertEqual(fixture["max_error_px"], fixture["structured"]["axis"]["max_error_px"])
        self.assertEqual(fixture["bad_frames"], fixture["structured"]["axis"]["bad_frames"])
        self.assertEqual(fixture["pending_count"], fixture["structured"]["axis"]["pending_count"])
        if "pending_frames" in fixture and "pending_frames" in fixture["structured"]["axis"]:
            self.assertEqual(fixture["pending_frames"], fixture["structured"]["axis"]["pending_frames"])
        self.assertEqual(fixture["blocks"], fixture["structured"])

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

    def test_overlay_update_runtime_payload_keeps_contract_aliases(self) -> None:
        profit_ocr_service.state["status"] = "ok"
        profit_ocr_service.state["targets"] = [{"value": 100.0, "label": "POC"}]
        profit_ocr_service.state["lines"] = [{"value": 100.0, "y_screen": 200}]
        profit_ocr_service.state["axis_status"] = "STABLE"
        profit_ocr_service.state["axis_source"] = "ocr"
        profit_ocr_service.state["axis_bad_frames"] = 1
        profit_ocr_service.state["axis_pending_count"] = 3
        profit_ocr_service.state["axis_labels"] = None

        payload = profit_ocr_service._build_overlay_update_data()
        axis = payload["structured"]["axis"]

        self.assertEqual(payload["source"], payload["axis_source"])
        self.assertEqual(payload["pending_frames"], payload["pending_count"])
        self.assertEqual(axis["source"], axis["axis_source"])
        self.assertEqual(axis["pending_frames"], axis["pending_count"])
        self.assertIsInstance(axis["axis_labels"], list)
        self.assertIsInstance(axis["ocr_labels"], list)

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

    def test_manual_unlock_alias_restores_automatic_axis_mode(self) -> None:
        body = profit_ocr_service.ManualAxisBody(
            points=[
                profit_ocr_service.ManualAxisPoint(value=100.0, y_screen=200.0),
                profit_ocr_service.ManualAxisPoint(value=120.0, y_screen=100.0),
            ]
        )
        asyncio.run(profit_ocr_service.manual_calibration_api(body))

        out = asyncio.run(profit_ocr_service.manual_unlock_axis_api())

        self.assertTrue(out["ok"])
        self.assertEqual(out["endpoint"], "manual_unlock")
        self.assertEqual(profit_ocr_service.axis_manager.manual_locked, False)
        self.assertIn(
            profit_ocr_service.axis_manager.status,
            {"RECALIBRATING", "CALIBRATING"},
        )
        self.assertEqual(profit_ocr_service.state["axis_source"], "none")

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

    def test_axis_manager_requires_confirmation_frames_for_jump(self) -> None:
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
        self.assertIsNone(mgr.feed(base_candidate))
        self.assertIsNotNone(mgr.feed(base_candidate))
        self.assertEqual(mgr.status, "STABLE")

        jump_candidate = dict(base_candidate)
        jump_candidate["intercept"] = 175.0
        for _ in range(2):
            out = mgr.feed(jump_candidate)
            self.assertIsNotNone(out)
            self.assertEqual(mgr.status, "CALIBRATING")
        out = mgr.feed(jump_candidate)
        self.assertIsNotNone(out)
        self.assertEqual(mgr.status, "STABLE")
        self.assertEqual(mgr.pending_count, 0)

    def test_axis_manager_requires_initial_confirm_frames(self) -> None:
        mgr = profit_ocr_service.StableAxisManager()
        candidate = {
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
        first = mgr.feed(candidate)
        self.assertIsNone(first)
        self.assertEqual(mgr.status, "CALIBRATING")
        self.assertEqual(mgr.initial_confirm_count, 1)
        second = mgr.feed(candidate)
        self.assertIsNotNone(second)
        self.assertEqual(mgr.status, "STABLE")
        self.assertEqual(mgr.initial_confirm_count, 0)

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
        self.assertIsNone(mgr.feed(valid))
        self.assertIsNotNone(mgr.feed(valid))
        invalid = dict(valid)
        invalid["confidence"] = 0.01
        mgr.last_stable_ts_monotonic = 0.0
        with mock.patch.object(
            profit_ocr_service.time,
            "monotonic",
            return_value=profit_ocr_service.AXIS_STABLE_HOLD_SECS + 0.5,
        ):
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
        self.assertIsNone(mgr.feed(valid))
        baseline = mgr.feed(valid)
        self.assertIsNotNone(baseline)

        bad_frame = dict(valid)
        bad_frame["confidence"] = 0.01
        mgr.last_stable_ts_monotonic = 0.0
        with mock.patch.object(
            profit_ocr_service.time,
            "monotonic",
            return_value=profit_ocr_service.AXIS_STABLE_HOLD_SECS + 0.5,
        ):
            recovered_from_bad = mgr.feed(bad_frame)
        self.assertIsNotNone(recovered_from_bad)
        self.assertEqual(mgr.status, "FROZEN")
        self.assertEqual(mgr.bad_frames, 1)

        good_again = mgr.feed(valid)
        self.assertIsNotNone(good_again)
        self.assertEqual(mgr.status, "CALIBRATING")
        self.assertEqual(mgr.bad_frames, 0)
        self.assertIsNotNone(mgr.feed(valid))
        self.assertEqual(mgr.status, "CALIBRATING")
        self.assertIsNotNone(mgr.feed(valid))
        self.assertEqual(mgr.status, "STABLE")

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
        self.assertIsNone(mgr.feed(valid))
        self.assertIsNotNone(mgr.feed(valid))

        bad_frame = dict(valid)
        bad_frame["confidence"] = 0.01
        mgr.last_stable_ts_monotonic = 0.0
        with mock.patch.object(
            profit_ocr_service.time,
            "monotonic",
            return_value=profit_ocr_service.AXIS_STABLE_HOLD_SECS + 0.5,
        ):
            for _ in range(profit_ocr_service.AXIS_MAX_BAD_FRAMES):
                self.assertIsNotNone(mgr.feed(bad_frame))
        self.assertEqual(mgr.status, "FROZEN")

        mgr.unfreeze()
        self.assertEqual(mgr.status, "CALIBRATING")
        self.assertEqual(mgr.bad_frames, 0)

        big_jump = dict(valid)
        big_jump["intercept"] = 175.0
        for _ in range(2):
            self.assertIsNotNone(mgr.feed(big_jump))
            self.assertEqual(mgr.status, "CALIBRATING")
        self.assertIsNotNone(mgr.feed(big_jump))
        self.assertEqual(mgr.status, "STABLE")

    def test_is_candidate_valid_rejects_tick_when_applicable(self) -> None:
        candidate = {
            "labels_count": 4,
            "tick_size": 5.0,
            "tick_valid": False,
            "monotonic_valid": True,
            "confidence": 0.99,
            "residual_px": 0.1,
            "max_error_px": 0.3,
        }
        self.assertFalse(profit_ocr_service.is_candidate_valid(candidate))

    def test_is_candidate_valid_allows_tick_when_not_applicable(self) -> None:
        candidate = {
            "labels_count": 4,
            "tick_size": 0.0,
            "tick_valid": False,
            "monotonic_valid": True,
            "confidence": 0.99,
            "residual_px": 0.1,
            "max_error_px": 0.3,
            "value_min": 100.0,
            "value_max": 180.0,
            "y_min": 20.0,
            "y_max": 120.0,
        }
        self.assertTrue(profit_ocr_service.is_candidate_valid(candidate))

    def test_is_candidate_valid_requires_minimum_labels_and_monotonic(self) -> None:
        low_labels_candidate = {
            "labels_count": max(1, profit_ocr_service.AXIS_MIN_LABELS - 1),
            "tick_size": 5.0,
            "tick_valid": True,
            "monotonic_valid": True,
            "confidence": 0.99,
            "residual_px": 0.1,
            "max_error_px": 0.3,
            "value_min": 100.0,
            "value_max": 180.0,
            "y_min": 20.0,
            "y_max": 120.0,
        }
        self.assertFalse(profit_ocr_service.is_candidate_valid(low_labels_candidate))

        many_labels_candidate = dict(low_labels_candidate)
        many_labels_candidate["labels_count"] = profit_ocr_service.AXIS_MIN_LABELS
        many_labels_candidate["monotonic_valid"] = False
        self.assertFalse(profit_ocr_service.is_candidate_valid(many_labels_candidate))

    def test_is_candidate_valid_accepts_threshold_boundaries(self) -> None:
        candidate = {
            "labels_count": 4,
            "tick_size": 5.0,
            "tick_valid": True,
            "monotonic_valid": True,
            "confidence": profit_ocr_service.AXIS_MIN_CONFIDENCE,
            "residual_px": profit_ocr_service.AXIS_MAX_RESIDUAL_PX,
            "max_error_px": profit_ocr_service.AXIS_MAX_ERROR_PX,
            "value_min": 100.0,
            "value_max": 180.0,
            "y_min": 20.0,
            "y_max": 120.0,
        }
        self.assertTrue(profit_ocr_service.is_candidate_valid(candidate))

    def test_is_candidate_valid_rejects_threshold_overflow(self) -> None:
        base = {
            "labels_count": 3,
            "tick_size": 5.0,
            "tick_valid": True,
            "monotonic_valid": True,
            "confidence": 0.95,
            "residual_px": 0.1,
            "max_error_px": 0.2,
        }
        low_confidence = dict(base)
        low_confidence["confidence"] = profit_ocr_service.AXIS_MIN_CONFIDENCE - 1e-9
        self.assertFalse(profit_ocr_service.is_candidate_valid(low_confidence))

        high_residual = dict(base)
        high_residual["residual_px"] = profit_ocr_service.AXIS_MAX_RESIDUAL_PX + 1e-9
        self.assertFalse(profit_ocr_service.is_candidate_valid(high_residual))

        high_max_error = dict(base)
        high_max_error["max_error_px"] = profit_ocr_service.AXIS_MAX_ERROR_PX + 1e-9
        self.assertFalse(profit_ocr_service.is_candidate_valid(high_max_error))

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

    def test_status_endpoint_is_lightweight_for_polling(self) -> None:
        profit_ocr_service.state["status"] = "ok"
        profit_ocr_service.state["axis_status"] = "STABLE"
        profit_ocr_service.state["axis_source"] = "ocr"
        profit_ocr_service.state["axis_bad_frames"] = 1
        profit_ocr_service.state["axis_pending_count"] = 0
        profit_ocr_service.state["axis_confidence"] = 0.9
        profit_ocr_service.state["axis_residual_px"] = 0.2
        profit_ocr_service.state["axis_max_error_px"] = 1.1
        profit_ocr_service.state["frame_seq"] = 42
        profit_ocr_service.state["lines"] = [{"value": 100.0, "y_screen": 120}]
        profit_ocr_service.state["targets"] = [{"value": 100.0, "label": "POC"}]
        profit_ocr_service.state["last_update"] = 123.0

        body = asyncio.run(profit_ocr_service.get_status())
        data = body["data"]

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["axis_status"], "STABLE")
        self.assertEqual(data["lines_count"], 1)
        self.assertEqual(data["targets_count"], 1)
        self.assertIn("uptime_sec", data)
        self.assertIn("session_axis_telemetry_tail", data)
        self.assertNotIn("overlay_update", data)
        self.assertNotIn("lines", data)

    def test_status_endpoint_remains_light_even_with_heavy_state(self) -> None:
        profit_ocr_service.state["status"] = "ok"
        profit_ocr_service.state["axis_status"] = "STABLE"
        profit_ocr_service.state["axis_source"] = "ocr"
        profit_ocr_service.state["axis_labels"] = [{"value": 1.0, "y_screen": 2.0}] * 50
        profit_ocr_service.state["axis_pending_candidate"] = {"confidence": 0.8}
        profit_ocr_service.state["analysis_sample"] = {"blob": "x" * 5000}
        profit_ocr_service.state["last_frame"] = {"payload": "x" * 5000}

        body = asyncio.run(profit_ocr_service.get_status())
        data = body["data"]

        self.assertNotIn("axis_labels", data)
        self.assertNotIn("axis_pending_candidate", data)
        self.assertNotIn("analysis_sample", data)
        self.assertNotIn("last_frame", data)

    def test_status_endpoint_normalizes_axis_contract_fields(self) -> None:
        profit_ocr_service.state["status"] = None
        profit_ocr_service.state["axis_status"] = None
        profit_ocr_service.state["axis_source"] = "unexpected"
        profit_ocr_service.axis_manager.status = "SUSPECT"

        body = asyncio.run(profit_ocr_service.get_status())
        data = body["data"]

        self.assertEqual(data["status"], "")
        self.assertEqual(data["axis_status"], "SUSPECT")
        self.assertEqual(data["axis_source"], "none")

    def test_reset_axis_quality_metrics_zeros_all_values(self) -> None:
        profit_ocr_service.state["axis_confidence"] = 0.9
        profit_ocr_service.state["axis_residual_px"] = 1.7
        profit_ocr_service.state["axis_max_error_px"] = 3.2

        profit_ocr_service._reset_axis_quality_metrics()

        self.assertEqual(profit_ocr_service.state["axis_confidence"], 0.0)
        self.assertEqual(profit_ocr_service.state["axis_residual_px"], 0.0)
        self.assertEqual(profit_ocr_service.state["axis_max_error_px"], 0.0)

    def test_append_trace_line_injects_render_indicators_from_state(self) -> None:
        old_lines = profit_ocr_service.state.get("lines")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "ocr_overlay_trace.jsonl")
                os.environ["PQ_OCR_TRACE_PATH"] = path
                profit_ocr_service.OCR_TRACE_PATH = path
                profit_ocr_service.AUDIT_TRAIL.trace_path = path
                profit_ocr_service.AUDIT_TRAIL._session_header_written = False
                profit_ocr_service.state["lines"] = [
                    {"status": "visible", "out_of_bounds": False},
                    {"status": "hidden", "out_of_bounds": True},
                ]
                profit_ocr_service._append_trace_line({"seq": 10})

                with open(path, "r", encoding="utf-8") as fh:
                    rows = [json.loads(line) for line in fh if line.strip()]

            frame = rows[1]
            self.assertEqual(frame["session_id"], profit_ocr_service.TRACE_SESSION_ID)
            indicators = frame["render_indicators"]
            self.assertEqual(indicators["line_count_total"], 2)
            self.assertEqual(indicators["line_count_visible"], 1)
            self.assertEqual(indicators["line_count_out_of_bounds"], 1)
        finally:
            profit_ocr_service.state["lines"] = old_lines

    def test_build_render_context_holds_lines_during_axis_warmup(self) -> None:
        old_lines = profit_ocr_service.state.get("lines")
        old_axis_status = profit_ocr_service.state.get("axis_status")
        try:
            profit_ocr_service.state["lines"] = [{"value": 100.0, "y_screen": 100}]
            profit_ocr_service.state["axis_status"] = "CALIBRATING"
            out = profit_ocr_service._build_render_context(
                {
                    "status": "ocr_axis_warming",
                    "chart_rect": {"left": 0, "top": 0, "width": 100, "height": 100},
                    "axis": {"slope": -1.0, "intercept": 100.0},
                }
            )
            self.assertEqual(out["lines"], [{"value": 100.0, "y_screen": 100}])
            self.assertTrue(str(out.get("status") or "").startswith("render_hold_"))
        finally:
            profit_ocr_service.state["lines"] = old_lines
            profit_ocr_service.state["axis_status"] = old_axis_status

    def test_axis_manager_transitions_to_no_axis_after_timeout(self) -> None:
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
        self.assertIsNone(mgr.feed(valid))
        self.assertIsNotNone(mgr.feed(valid))
        mgr.last_stable_ts_monotonic = 0.0
        with mock.patch.object(profit_ocr_service.time, "monotonic", return_value=profit_ocr_service.AXIS_FROZEN_HOLD_SECS + 0.5):
            out = mgr.feed(None)
        self.assertIsNotNone(out)
        self.assertEqual(mgr.status, "DEGRADED")

    def test_status_light_includes_axis_error_and_last_good_age(self) -> None:
        old_ts = profit_ocr_service.axis_manager.last_stable_ts_monotonic
        try:
            profit_ocr_service.state["axis_error_code"] = "NO_VALID_PRICE_LABELS"
            profit_ocr_service.state["axis_error_message"] = "OCR returned text but no valid price labels"
            profit_ocr_service.axis_manager.last_stable_ts_monotonic = 0.0
            with mock.patch.object(profit_ocr_service.time, "monotonic", return_value=1.2):
                data = profit_ocr_service._build_status_light_data()
            self.assertEqual(data["axis_error_code"], "NO_VALID_PRICE_LABELS")
            self.assertIn("valid price labels", data["axis_error_message"])
            self.assertIsInstance(data["last_good_axis_age_ms"], int)
        finally:
            profit_ocr_service.axis_manager.last_stable_ts_monotonic = old_ts

    def test_debug_dump_endpoint_creates_expected_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dbg = {
                "profit_window_found": True,
                "profit_hwnd": 1234,
                "dpi_scale": 1.25,
                "monitor_id": "monitor-1",
                "monitor_bounds": {"x": 0, "y": 0, "width": 1920, "height": 1080},
                "profit_bounds": {"x": 0, "y": 0, "width": 800, "height": 600},
                "chart_crop": {"x": 0, "y": 90, "width": 800, "height": 500},
                "axis_crop": {"x": 700, "y": 90, "width": 100, "height": 500},
                "raw_ocr_text": "185.240 185.235 185.230",
                "parsed_labels": [185240.0, 185235.0, 185230.0],
                "rejected_labels": [],
                "capture_mode": "hwnd_printwindow",
                "labels_raw": [{"value": 185240.0, "y_screen": 100.0}],
            }
            fake_full = Image.new("RGB", (1200, 800), "black")
            fake_win = Image.new("RGB", (800, 600), "black")
            with mock.patch.object(profit_ocr_service, "_debug_dump_dir", return_value=Path(tmp)), \
                mock.patch.object(profit_ocr_service, "_capture_debug_images", return_value=dbg), \
                mock.patch.object(profit_ocr_service, "_capture_full_screen_image", return_value=fake_full), \
                mock.patch.object(
                    profit_ocr_service,
                    "resolve_profit_window",
                    return_value={"hwnd": 1234, "left": 0, "top": 0, "width": 800, "height": 600},
                ), \
                mock.patch.object(profit_ocr_service, "capture_profit_window", return_value=(fake_win, "hwnd_printwindow")):
                body = asyncio.run(profit_ocr_service.debug_dump())

            self.assertTrue(body["ok"])
            for f in [
                "full_screen.png",
                "profit_window_crop.png",
                "chart_crop.png",
                "axis_crop_raw.png",
                "axis_crop_processed.png",
                "ocr_result.json",
                "axis_fit.json",
            ]:
                self.assertTrue((Path(tmp) / f).exists(), f"missing artifact: {f}")


if __name__ == "__main__":
    unittest.main()
