"""
Enriquece volume_profile / tape_intelligence com Y em coordenada de tela a partir
do /status do profit_ocr_service (eixo híbrido, mesmo modelo do overlay).
Ativo por defeito; desligar: VP_ENRICH_OCR=0
"""

from __future__ import annotations

import copy
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

import logging

logger = logging.getLogger(__name__)

OCR_STATUS_URL = (os.environ.get("PQ_OCR_STATUS_URL") or "http://127.0.0.1:5558/status").strip()
_CACHE_TS_MS: float = 0.0
_CACHE_PACK: Optional[tuple[list[dict[str, float]], dict[str, float], Any]] = None
_STATUS_BODY_MS: float = 0.0
_STATUS_BODY: Optional[dict[str, Any]] = None
_STATUS_FAIL_MS: float = 0.0
_STATUS_FAIL_LOG_MS: float = 0.0
_STALE_MAX_MS = 3000.0
_FRESH_MAX_MS = 150.0
_FAIL_RETRY_MS = 3000.0


def _enrich_enabled() -> bool:
    v = (os.environ.get("VP_ENRICH_OCR") or "1").strip().lower()
    return v not in ("0", "false", "off", "no")


def _value_to_y_hybrid(
    value: float,
    labels: list[dict[str, float]],
    axis: dict[str, float],
) -> Optional[int]:
    if len(labels) >= 2:
        by_val = sorted(labels, key=lambda x: float(x["value"]))
        for i in range(len(by_val) - 1):
            lo, hi = by_val[i], by_val[i + 1]
            if float(hi["value"]) == float(lo["value"]):
                continue
            if float(lo["value"]) <= value <= float(hi["value"]):
                t = (value - float(lo["value"])) / (float(hi["value"]) - float(lo["value"]))
                y = float(lo["y_screen"]) + t * (float(hi["y_screen"]) - float(lo["y_screen"]))
                return int(round(y))
    slope = float(axis["slope"])
    intercept = float(axis["intercept"])
    if abs(slope) < 1e-12:
        return None
    yf = (value - intercept) / slope
    return int(round(yf))


def _log_ocr_axis_failure(reason: str, data: Optional[dict[str, Any]]) -> None:
    payload: dict[str, Any] = {"reason": reason}
    if data:
        payload["chart_rect"] = data.get("chart_rect")
        payload["axis_labels"] = data.get("axis_labels")
        payload["axis"] = data.get("axis")
        payload["axis_diagnostics"] = data.get("axis_diagnostics")
        payload["status"] = data.get("status")
    logger.warning("vp_ocr_enrich axis pack failed: %s", json.dumps(payload, ensure_ascii=False))


def _fetch_ocr_status_body() -> Optional[dict[str, Any]]:
    """Corpo JSON de /status; cache curto; em falha HTTP mantém último corpo válido até _STALE_MAX_MS."""
    global _STATUS_BODY_MS, _STATUS_BODY, _STATUS_FAIL_MS, _STATUS_FAIL_LOG_MS
    now = time.monotonic() * 1000.0
    if _STATUS_BODY is not None and now - _STATUS_BODY_MS < _FRESH_MAX_MS:
        return _STATUS_BODY
    if _STATUS_FAIL_MS > 0.0 and now - _STATUS_FAIL_MS < _FAIL_RETRY_MS:
        if _STATUS_BODY is not None and now - _STATUS_BODY_MS < _STALE_MAX_MS:
            return _STATUS_BODY
        return None
    data: Optional[dict[str, Any]] = None
    try:
        req = urllib.request.Request(OCR_STATUS_URL, method="GET")
        with urllib.request.urlopen(req, timeout=0.8) as r:
            raw = r.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
        data = parsed if isinstance(parsed, dict) else None
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, ValueError) as ex:
        _STATUS_FAIL_MS = now
        if now - _STATUS_FAIL_LOG_MS >= _FAIL_RETRY_MS:
            _STATUS_FAIL_LOG_MS = now
            logger.warning(
                "vp_ocr_enrich status fetch failed: %s",
                json.dumps({"reason": f"request_or_parse:{type(ex).__name__}"}, ensure_ascii=False),
            )
        data = None

    if data is not None:
        _STATUS_BODY = data
        _STATUS_BODY_MS = now
        _STATUS_FAIL_MS = 0.0
        return _STATUS_BODY
    if _STATUS_BODY is not None and now - _STATUS_BODY_MS < _STALE_MAX_MS:
        return _STATUS_BODY
    return None


def _chart_bounds_from_rect(rect: Any) -> Optional[dict[str, float]]:
    if not isinstance(rect, dict):
        return None
    try:
        l = float(rect["left"])
        t = float(rect["top"])
        w = float(rect["width"])
        h = float(rect["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return {"left": l, "top": t, "right": l + w, "bottom": t + h}


def _ocr_confidence_from_status(body: dict[str, Any]) -> float:
    st = str(body.get("status") or "")
    if st == "ok":
        diag = body.get("axis_diagnostics") if isinstance(body.get("axis_diagnostics"), dict) else {}
        kept = float(diag.get("kept_labels") or 0)
        raw = float(diag.get("raw_labels") or 0)
        denom = raw if raw > 0 else max(kept, 1.0)
        ratio = min(1.0, kept / denom)
        base = 0.42 + 0.5 * ratio
        if kept >= 5:
            base = min(1.0, base + 0.06)
        return min(1.0, max(0.0, base))
    if st == "window_not_found":
        return 0.0
    if st.startswith("ocr_insufficient") or st.startswith("ocr_axis"):
        return 0.12
    return 0.22


def _axis_contract_status(body: dict[str, Any]) -> str:
    st = str(body.get("status") or "")
    if st == "ok":
        return "ok"
    if st == "window_not_found":
        return "window_not_found"
    if "fit_failed" in st or "insufficient" in st:
        return "axis_not_found"
    return "low_confidence"


def _enrich_vp_overlay_screen_y(out: dict[str, Any]) -> None:
    """Preenche `y` em poc/val/vah e em `levels` usando o mesmo pack híbrido que VP/Tape."""
    pack = _get_axis_pack()
    if pack is None:
        return
    labels, axis, _rect = pack
    for key in ("poc", "val", "vah"):
        node = out.get(key)
        if not isinstance(node, dict):
            continue
        p = node.get("price")
        if not isinstance(p, (int, float)):
            try:
                p = float(p)
            except (TypeError, ValueError):
                continue
        y = _value_to_y_hybrid(float(p), labels, axis)
        if y is not None:
            node["y"] = int(y)
    levs = out.get("levels")
    if isinstance(levs, list):
        for row in levs:
            if not isinstance(row, dict) or "price" not in row:
                continue
            try:
                pr = float(row["price"])
            except (TypeError, ValueError):
                continue
            y = _value_to_y_hybrid(pr, labels, axis)
            if y is not None:
                row["y"] = int(y)


def enrich_vp_overlay_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Preenche health (OCR, stale), bloco axis e coordenadas Y de overlay a partir de /status."""
    if not _enrich_enabled():
        return payload
    if str(payload.get("type", "")) != "vp_overlay":
        return payload
    body = _fetch_ocr_status_body()
    if body is None:
        pack = _get_axis_pack()
        if pack is None:
            return payload
        out = copy.deepcopy(payload)
        _enrich_vp_overlay_screen_y(out)
        return out
    out = copy.deepcopy(payload)
    h_in = out.get("health")
    h: dict[str, Any] = dict(h_in) if isinstance(h_in, dict) else {}
    now = time.time()
    lu = float(body.get("last_update") or 0.0)
    axis_stale_ms = max(0, int((now - lu) * 1000.0)) if lu > 0.0 else 0
    conf = _ocr_confidence_from_status(body)
    h["axis_stale_ms"] = axis_stale_ms
    h["ocr_confidence"] = round(conf, 4)
    ds = str(h.get("data_status") or "ok")
    ocr_st = str(body.get("status") or "")
    if ds not in ("missing_vp", "missing_tape") and ocr_st != "ok":
        if axis_stale_ms > 12000:
            h["data_status"] = "stale"
        elif axis_stale_ms > 4000:
            h["data_status"] = "degraded"
    out["health"] = h

    axis_in = body.get("axis")
    if isinstance(axis_in, dict):
        try:
            slope = float(axis_in["slope"])
            intercept = float(axis_in["intercept"])
        except (KeyError, TypeError, ValueError):
            _enrich_vp_overlay_screen_y(out)
            return out
        ym = body.get("y_min")
        yx = body.get("y_max")
        pm = float(ym) if isinstance(ym, (int, float)) else None
        px = float(yx) if isinstance(yx, (int, float)) else None
        out["axis"] = {
            "slope": slope,
            "intercept": intercept,
            "confidence": round(conf, 4),
            "status": _axis_contract_status(body),
            "chart_bounds": _chart_bounds_from_rect(body.get("chart_rect")),
        }
        if pm is not None:
            out["axis"]["price_min"] = pm
        if px is not None:
            out["axis"]["price_max"] = px
    _enrich_vp_overlay_screen_y(out)
    return out


def _get_axis_pack() -> Optional[tuple[list[dict[str, float]], dict[str, float], Any]]:
    """Labels + ajuste linear; cache com TTL curto; em falha rede usa cache stale."""
    global _CACHE_TS_MS, _CACHE_PACK
    now = time.monotonic() * 1000.0
    if _CACHE_PACK is not None and now - _CACHE_TS_MS < _FRESH_MAX_MS:
        return _CACHE_PACK
    data = _fetch_ocr_status_body()

    if data is not None and data.get("status") == "ok":
        labels = data.get("axis_labels")
        axis = data.get("axis")
        if isinstance(labels, list) and len(labels) >= 2 and isinstance(axis, dict):
            try:
                lab_out: list[dict[str, float]] = []
                for lb in labels:
                    if not isinstance(lb, dict):
                        continue
                    lab_out.append(
                        {"value": float(lb["value"]), "y_screen": float(lb["y_screen"])}
                    )
                if len(lab_out) < 2:
                    raise ValueError("insufficient")
                ax_out = {
                    "slope": float(axis["slope"]),
                    "intercept": float(axis["intercept"]),
                    "value_per_px": float(axis.get("value_per_px", abs(float(axis["slope"])))),
                }
                rect = data.get("chart_rect")
                _CACHE_PACK = (lab_out, ax_out, rect)
                _CACHE_TS_MS = now
                return _CACHE_PACK
            except (KeyError, TypeError, ValueError):
                _log_ocr_axis_failure("axis_labels_parse_error", data)
        else:
            _log_ocr_axis_failure("axis_labels_or_axis_invalid", data)
    elif data is not None:
        _log_ocr_axis_failure("status_not_ok", data)

    if _CACHE_PACK is not None and now - _CACHE_TS_MS < _STALE_MAX_MS:
        return _CACHE_PACK
    return None


def enrich_vp_ti_message(msg: dict[str, Any]) -> dict[str, Any]:
    if not _enrich_enabled():
        return msg
    t = str(msg.get("type", ""))
    if t not in ("volume_profile", "tape_intelligence"):
        return msg
    pack = _get_axis_pack()
    if pack is None:
        return msg
    labels, axis, _rect = pack
    out: dict[str, Any] = copy.deepcopy(msg)
    if t == "volume_profile":
        for pk, yk in (("poc", "poc_y"), ("vah", "vah_y"), ("val", "val_y")):
            p = out.get(pk)
            if isinstance(p, (int, float)):
                y = _value_to_y_hybrid(float(p), labels, axis)
                if y is not None:
                    out[yk] = y
        levs = out.get("levels")
        if isinstance(levs, list):
            for row in levs:
                if not isinstance(row, dict) or "price" not in row:
                    continue
                try:
                    p = float(row["price"])
                except (TypeError, ValueError):
                    continue
                y = _value_to_y_hybrid(p, labels, axis)
                if y is not None:
                    row["y"] = y
    else:
        for pk, yk in (
            ("poc_price", "poc_y"),
            ("vah_price", "vah_y"),
            ("val_price", "val_y"),
        ):
            p = out.get(pk)
            if isinstance(p, (int, float)):
                y = _value_to_y_hybrid(float(p), labels, axis)
                if y is not None:
                    out[yk] = y
    return out
