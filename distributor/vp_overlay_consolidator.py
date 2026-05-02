"""Consolida volume_profile + tape_intelligence em um único payload `vp_overlay`."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _payload_identity_hash(payload: dict[str, Any]) -> str:
    trimmed = {}
    for k, v in payload.items():
        if k in ("sequence", "updated_at", "demo", "axis"):
            continue
        if k == "health" and isinstance(v, dict):
            health = {
                hk: hv
                for hk, hv in v.items()
                if hk not in ("axis_stale_ms", "last_trade_age_ms", "ocr_confidence")
            }
            trimmed[k] = health
            continue
        if k == "top_player_avg_lines" and isinstance(v, list):
            compact = []
            for row in v:
                if isinstance(row, dict):
                    compact.append(
                        {
                            kk: vv
                            for kk, vv in row.items()
                            if kk not in ("y", "y_screen", "axis", "updated_at")
                        }
                    )
                else:
                    compact.append(row)
            trimmed[k] = compact
            continue
        trimmed[k] = v
    return hashlib.sha256(json.dumps(trimmed, sort_keys=True, default=str).encode()).hexdigest()


def _critical_fingerprint(vp: dict[str, Any], tape: dict[str, Any]) -> str:
    """Âncoras + holders + top avg — mudança força publish mesmo sob throttle (DIST-02)."""
    top_avg = tape.get("top_player_avg_lines")
    top_s = json.dumps(top_avg, sort_keys=True, default=str) if top_avg is not None else ""
    parts = (
        _f(vp.get("poc")),
        _f(vp.get("val")),
        _f(vp.get("vah")),
        _i(tape.get("poc_player")),
        _i(tape.get("val_buyer")),
        _i(tape.get("vah_seller")),
        str(tape.get("val_holder_state") or ""),
        str(tape.get("vah_holder_state") or ""),
        top_s,
    )
    return "|".join(str(p) for p in parts)


def _critical_fingerprint_from_overlay_payload(payload: dict[str, Any]) -> str:
    """Fingerprint alinhado a `build_vp_overlay_payload` para demo/API inject."""
    poc = payload.get("poc") if isinstance(payload.get("poc"), dict) else {}
    val = payload.get("val") if isinstance(payload.get("val"), dict) else {}
    vah = payload.get("vah") if isinstance(payload.get("vah"), dict) else {}
    vp = {"poc": _f(poc.get("price")), "val": _f(val.get("price")), "vah": _f(vah.get("price"))}
    tape = {
        "poc_player": _i(poc.get("player_id")),
        "val_buyer": _i(val.get("player_id")),
        "vah_seller": _i(vah.get("player_id")),
        "val_holder_state": str(val.get("holder", {}).get("state") or "") if isinstance(val.get("holder"), dict) else "",
        "vah_holder_state": str(vah.get("holder", {}).get("state") or "") if isinstance(vah.get("holder"), dict) else "",
        "top_player_avg_lines": payload.get("top_player_avg_lines"),
    }
    return _critical_fingerprint(vp, tape)


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _i(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _scope_from_vp(vp: dict[str, Any]) -> str:
    p = str(vp.get("period") or "session").strip().lower()
    if p in ("day", "week", "manual", "session"):
        return p
    return "session"


def _overlay_age_state(age_ms: Optional[int]) -> str:
    if age_ms is None:
        return "missing"
    if age_ms > 3000:
        return "stale"
    return "fresh"


def _find_top3_row(tape: dict[str, Any], key: str, player_id: int) -> Optional[dict[str, Any]]:
    rows = tape.get(key)
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and _i(row.get("player"), 0) == player_id:
            return row
    return None


def _holder_poc(tape: dict[str, Any]) -> dict[str, Any]:
    pid = _i(tape.get("poc_player"), 0)
    if pid <= 0:
        return {"method": "unconfirmed", "state": "unconfirmed", "contracts": 0, "participation_pct": 0.0}
    row = _find_top3_row(tape, "poc_top3", pid)
    contracts = _i(row.get("total_vol"), 0) if row else 0
    tot = sum(_i(r.get("total_vol"), 0) for r in (tape.get("poc_top3") or []) if isinstance(r, dict))
    pct = 100.0 * float(contracts) / float(tot) if tot > 0 else 0.0
    return {"method": "total_volume", "state": "ok", "contracts": contracts, "participation_pct": pct}


def _holder_val(tape: dict[str, Any]) -> dict[str, Any]:
    pid = _i(tape.get("val_buyer"), 0)
    st = str(tape.get("val_holder_state") or "ok")
    if st not in ("ok", "low_confidence", "unconfirmed"):
        st = "ok"
    if pid <= 0:
        return {"method": "unconfirmed", "state": "unconfirmed", "contracts": 0, "participation_pct": 0.0}
    row = _find_top3_row(tape, "val_top3", pid)
    contracts = _i(row.get("buy_absorption"), 0) if row else 0
    tot = sum(_i(r.get("buy_absorption"), 0) for r in (tape.get("val_top3") or []) if isinstance(r, dict))
    pct = 100.0 * float(contracts) / float(tot) if tot > 0 else 0.0
    return {"method": "passive_buy_absorption", "state": st, "contracts": contracts, "participation_pct": pct}


def _holder_vah(tape: dict[str, Any]) -> dict[str, Any]:
    pid = _i(tape.get("vah_seller"), 0)
    st = str(tape.get("vah_holder_state") or "ok")
    if st not in ("ok", "low_confidence", "unconfirmed"):
        st = "ok"
    if pid <= 0:
        return {"method": "unconfirmed", "state": "unconfirmed", "contracts": 0, "participation_pct": 0.0}
    row = _find_top3_row(tape, "vah_top3", pid)
    contracts = _i(row.get("sell_absorption"), 0) if row else 0
    tot = sum(_i(r.get("sell_absorption"), 0) for r in (tape.get("vah_top3") or []) if isinstance(r, dict))
    pct = 100.0 * float(contracts) / float(tot) if tot > 0 else 0.0
    return {"method": "passive_sell_absorption", "state": st, "contracts": contracts, "participation_pct": pct}


def build_vp_overlay_payload(
    *,
    vp: dict[str, Any],
    tape: dict[str, Any],
    sequence: int,
    demo: bool = False,
) -> dict[str, Any]:
    raw_ticker = str(vp.get("raw_ticker") or tape.get("raw_ticker") or vp.get("ticker") or tape.get("ticker") or "").strip()
    ticker = raw_ticker.upper()
    ts = time.time()
    poc_p = _f(vp.get("poc"), _f(tape.get("poc_price")))
    val_p = _f(vp.get("val"), _f(tape.get("val_price")))
    vah_p = _f(vp.get("vah"), _f(tape.get("vah_price")))
    poc_id = _i(tape.get("poc_player"), 0)
    val_id = _i(tape.get("val_buyer"), 0)
    vah_id = _i(tape.get("vah_seller"), 0)
    poc_label = f"POC {poc_p:.0f}" + (f" — #{poc_id}" if poc_id else "")
    val_label = f"VAL {val_p:.0f}" + (f" — #{val_id}" if val_id else "")
    vah_label = f"VAH {vah_p:.0f}" + (f" — #{vah_id}" if vah_id else "")

    levels_raw = vp.get("levels") or []
    levels_out: list[dict[str, Any]] = []
    if isinstance(levels_raw, list):
        for row in levels_raw:
            if not isinstance(row, dict):
                continue
            levels_out.append(
                {
                    "price": _f(row.get("price")),
                    "total_vol": _i(row.get("total_vol"), 0),
                    "bid_vol": _i(row.get("bid_vol"), 0),
                    "ask_vol": _i(row.get("ask_vol"), 0),
                    "pct_of_max": _f(row.get("pct_of_max"), 0.0),
                }
            )

    top_avg = tape.get("top_player_avg_lines")
    if not isinstance(top_avg, list):
        top_avg = []

    health_status = "ok"
    if not levels_out:
        health_status = "missing_vp"
    elif not tape.get("timestamp"):
        health_status = "missing_tape"

    last_trade_age_ms = 0
    ts_trade = tape.get("timestamp")
    if ts_trade is not None:
        try:
            tsf = float(ts_trade)
            last_trade_age_ms = max(0, int(time.time() * 1000.0 - tsf))
        except (TypeError, ValueError):
            last_trade_age_ms = 0

    out: dict[str, Any] = {
        "topic": "market",
        "type": "vp_overlay",
        "version": 1,
        "symbol": ticker,
        "raw_ticker": raw_ticker,
        "scope": _scope_from_vp(vp),
        "sequence": int(sequence),
        "updated_at": ts,
        "poc": {
            "price": poc_p,
            "player_id": poc_id,
            "label": poc_label,
            "holder": _holder_poc(tape),
            "line_color": "#ff8c00",
        },
        "val": {
            "price": val_p,
            "player_id": val_id,
            "label": val_label,
            "holder": _holder_val(tape),
            "line_color": "#e53935",
        },
        "vah": {
            "price": vah_p,
            "player_id": vah_id,
            "label": vah_label,
            "holder": _holder_vah(tape),
            "line_color": "#e53935",
        },
        "levels": levels_out,
        "top_player_avg_lines": top_avg,
        "display": {
            "overlay_enabled": True,
            "poc_visible": True,
            "val_vah_visible": True,
            "labels_visible": True,
            "histogram_visible": True,
            "top_avg_visible": True,
            "stretch_lines": False,
            "max_avg_lines": 6,
            "max_histogram_width_px": 220,
            "max_visible_histogram_levels": 400,
        },
        "health": {
            "data_status": health_status,
            "axis_stale_ms": 0,
            "last_trade_age_ms": last_trade_age_ms,
            "last_overlay_publish_age_ms": 0,
            "last_overlay_publish_age_sec": 0.0,
            "overlay_age_state": _overlay_age_state(0),
            "ocr_confidence": 0.0,
        },
    }
    if demo:
        out["demo"] = True
    return out


class VpOverlayConsolidator:
    """Cache por ticker, throttle temporal e coalescing de hash."""

    def __init__(self, publish_interval_ms: int = 125) -> None:
        self._publish_interval_ms = max(0, int(publish_interval_ms))
        self._vp: dict[str, dict[str, Any]] = {}
        self._tape: dict[str, dict[str, Any]] = {}
        self._seq: dict[str, int] = {}
        self._last_emit_mono: dict[str, float] = {}
        self._last_hash: dict[str, str] = {}
        self._last_payload: dict[str, dict[str, Any]] = {}
        self._last_critical_fp: dict[str, str] = {}
        self._emit_count = 0
        self._skipped_same_hash = 0

    def metrics(self) -> dict[str, int]:
        return {
            "vp_overlay_emit_count": self._emit_count,
            "vp_overlay_skipped_same_hash": self._skipped_same_hash,
        }

    def debug_state(self, symbol: str) -> dict[str, Any]:
        k = symbol.strip().upper()
        age_sec = None
        age_ms = None
        t0 = self._last_emit_mono.get(k)
        if t0 is not None:
            age_sec = round(time.monotonic() - t0, 3)
            age_ms = int(round((time.monotonic() - t0) * 1000.0))
        last_payload = self._last_payload.get(k)
        health = last_payload.get("health") if isinstance(last_payload, dict) else {}
        if not isinstance(health, dict):
            health = {}
        return {
            "symbol": k,
            "has_vp_cache": k in self._vp,
            "has_tape_cache": k in self._tape,
            "vp_cache_size": len(self._vp),
            "tape_cache_size": len(self._tape),
            "sequence": self._seq.get(k, 0),
            "last_overlay_publish_age_sec": age_sec,
            "last_overlay_publish_age_ms": age_ms,
            "overlay_age_state": _overlay_age_state(age_ms),
            "last_trade_age_ms": health.get("last_trade_age_ms"),
            "ocr_confidence": health.get("ocr_confidence"),
            "data_status": health.get("data_status"),
            "vp_overlay_emit_count": self._emit_count,
            "vp_overlay_skipped_same_hash": self._skipped_same_hash,
        }

    def last_payload(self, symbol: str) -> Optional[dict[str, Any]]:
        return self._last_payload.get(symbol.strip().upper())

    def reset(self, symbol: Optional[str] = None) -> None:
        if symbol:
            k = symbol.strip().upper()
            self._vp.pop(k, None)
            self._tape.pop(k, None)
            self._seq.pop(k, None)
            self._last_emit_mono.pop(k, None)
            self._last_hash.pop(k, None)
            self._last_payload.pop(k, None)
            self._last_critical_fp.pop(k, None)
        else:
            self._vp.clear()
            self._tape.clear()
            self._seq.clear()
            self._last_emit_mono.clear()
            self._last_hash.clear()
            self._last_payload.clear()
            self._last_critical_fp.clear()

    def inject_demo(self, payload: dict[str, Any]) -> str:
        sym = str(payload.get("symbol") or "").strip().upper()
        if not sym:
            sym = "WINFUT"
        self._seq[sym] = int(payload.get("sequence") or 0) + 1
        payload = dict(payload)
        payload["symbol"] = sym
        payload["sequence"] = self._seq[sym]
        payload["updated_at"] = time.time()
        self._last_payload[sym] = payload
        self._last_hash[sym] = _payload_identity_hash(payload)
        self._last_critical_fp[sym] = _critical_fingerprint_from_overlay_payload(payload)
        return sym

    def feed_market_message(self, msg: dict[str, Any]) -> Optional[dict[str, Any]]:
        mtype = str(msg.get("type") or "")
        if mtype not in ("volume_profile", "tape_intelligence"):
            return None
        ticker = str(msg.get("ticker") or "").strip().upper()
        if not ticker:
            return None
        now = time.monotonic()
        if mtype == "volume_profile":
            self._vp[ticker] = msg
        else:
            self._tape[ticker] = msg

        vp = self._vp.get(ticker)
        tape = self._tape.get(ticker)
        if vp is None or tape is None:
            return None

        fp_now = _critical_fingerprint(vp, tape)
        prev_fp = self._last_critical_fp.get(ticker)
        critical_changed = prev_fp is not None and fp_now != prev_fp

        last_t = self._last_emit_mono.get(ticker, 0.0)
        within_throttle = (
            self._publish_interval_ms > 0
            and (now - last_t) * 1000.0 < self._publish_interval_ms
        )
        if within_throttle and not critical_changed:
            return None

        next_seq = self._seq.get(ticker, 0) + 1
        built = build_vp_overlay_payload(vp=vp, tape=tape, sequence=next_seq, demo=bool(msg.get("demo")))
        h = _payload_identity_hash(built)
        if self._last_hash.get(ticker) == h:
            self._skipped_same_hash += 1
            return None
        self._seq[ticker] = next_seq
        self._last_hash[ticker] = h
        self._last_emit_mono[ticker] = now
        self._last_payload[ticker] = built
        self._emit_count += 1
        self._last_critical_fp[ticker] = fp_now
        logger.debug("[vp_overlay] emit symbol=%s seq=%s", ticker, self._seq[ticker])
        return built
