"""
Serviço OCR para o Overlay do gráfico Profit.

Fonte canónica: distributor/profit_ocr_service.py.
Réplica para o bundle Tauri: scripts/sync-profit-ocr-to-tauri-resources.ps1
(invocado por run-dev.ps1 e build-installer.ps1) → app/src-tauri/resources/.
"""

import asyncio
import contextlib
import json
import math
import os
import re
import sys
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

try:
    import ctypes
    from ctypes import wintypes

    import mss
    import pytesseract
    import uvicorn
    import win32gui
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from PIL import Image, ImageEnhance
    from pydantic import BaseModel
except ImportError as e:
    print(f"[OCR] Dependência ausente: {e}")
    print("Execute: pip install -r requirements_ocr.txt")
    sys.exit(1)


def _enable_dpi_awareness() -> None:
    """Per-monitor DPI evita desalinhamento entre GetWindowRect (lógico) e captura mss (físico) em 2+ telas."""
    try:
        user32 = ctypes.windll.user32
        ctx = ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            if user32.SetProcessDpiAwarenessContext(ctx):
                return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _logical_rect_to_physical(hwnd: int, l: int, t: int, r: int, b: int) -> tuple[int, int, int, int]:
    user32 = ctypes.windll.user32
    if hasattr(user32, "LogicalToPhysicalPoint"):
        pt_lo = wintypes.POINT(l, t)
        pt_hi = wintypes.POINT(r, b)
        user32.LogicalToPhysicalPoint(hwnd, ctypes.byref(pt_lo))
        user32.LogicalToPhysicalPoint(hwnd, ctypes.byref(pt_hi))
        return pt_lo.x, pt_lo.y, pt_hi.x, pt_hi.y
    return l, t, r, b


_enable_dpi_awareness()


def configure_tesseract_cmd() -> None:
    """
    Resolve o executavel do Tesseract sem depender do PATH da sessao.
    Prioriza TESSERACT_CMD e depois caminhos padrao do Windows.
    """
    candidates = []
    env_cmd = os.environ.get("TESSERACT_CMD", "").strip()
    if env_cmd:
        candidates.append(env_cmd)

    candidates.extend(
        [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
    )

    for cmd in candidates:
        if os.path.isfile(cmd):
            pytesseract.pytesseract.tesseract_cmd = cmd
            return


# Porta dedicada: 5557 é usada pelo sync_monitor (ZMQ PUB); evitar conflito TCP.
# Sobrescrever com PQ_OCR_PORT (alinhar Tauri + frontend: docs/PORTS.md).
OCR_PORT = int(os.environ.get("PQ_OCR_PORT", "5558"))
try:
    REFRESH_MS = int(os.environ.get("PQ_OCR_REFRESH_MS", "280"))
except ValueError:
    REFRESH_MS = 280
REFRESH_MS = max(120, min(800, REFRESH_MS))
WINDOW_SCAN_INTERVAL_MS = 1200
Y_AXIS_FRAC = 0.14
TOOLBAR_H = int(os.environ.get("PQ_OVERLAY_TOOLBAR_H", "90"))
AXIS_BOTTOM_CROP_PX = int(os.environ.get("PQ_OVERLAY_AXIS_BOTTOM_CROP_PX", "42"))
try:
    MIN_CONF = int(os.environ.get("PQ_OCR_MIN_CONF", "20"))
except ValueError:
    MIN_CONF = 20
# Primeiros segundos: não assustar com "0 labels" enquanto CPU/Tesseract aquecem (PC lento / 1ª captura).
try:
    AXIS_WARMUP_SECS = float(os.environ.get("PQ_OCR_AXIS_WARMUP_SECS", "30"))
except ValueError:
    AXIS_WARMUP_SECS = 30.0
# Suavização das linhas do overlay (0 = desligado; ~0.7 = mais responsivo).
try:
    LINE_Y_SMOOTH_ALPHA = float(os.environ.get("PQ_OVERLAY_LINE_SMOOTH_ALPHA", "0.72"))
except ValueError:
    LINE_Y_SMOOTH_ALPHA = 0.72
# Salto em px entre Y medido e EMA: ignora EMA e “cola” ao valor atual (eixo a convergir).
try:
    LINE_Y_SNAP_PX = float(os.environ.get("PQ_OVERLAY_LINE_Y_SNAP_PX", "22"))
except ValueError:
    LINE_Y_SNAP_PX = 22.0
try:
    AXIS_BLEND_BETA = float(os.environ.get("PQ_OCR_AXIS_BLEND_BETA", "0.52"))
except ValueError:
    AXIS_BLEND_BETA = 0.52
AXIS_BLEND_BETA = min(1.0, max(0.01, AXIS_BLEND_BETA))
COLORS = ["#00FF88", "#FF4444", "#FFB800", "#00CCFF", "#FF88FF", "#FFFFFF"]


def line_color_for_label(label: str, idx: int) -> str:
    """Verde: líder de compra; vermelho: líder de venda; roxo: UBS; demais: paleta."""
    s = (label or "").strip().lower()
    if s == "ubs":
        return "#A855F7"
    if "vendedor" in s or ("venda" in s and "compra" not in s):
        return "#FF4444"
    if "comprador" in s or "compra" in s:
        return "#00FF88"
    return COLORS[idx % len(COLORS)]

state: Dict[str, Any] = {
    "targets": [],
    "positions": [],
    "chart_rect": None,
    "y_min": None,
    "y_max": None,
    "lines": [],
    "status": "searching",
    "last_update": 0.0,
    "dpi_scale": 1.0,
    # Região opcional só para leitura/verificação (não altera o cálculo das linhas).
    "analysis_roi": None,
    "analysis_sample": None,
    "axis_deltas": None,
    "axis_diagnostics": None,
}
clients: List[WebSocket] = []
service_started_at = time.monotonic()
first_ok_logged = False

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    configure_tesseract_cmd()
    state["dpi_scale"] = get_dpi_scale()
    task = asyncio.create_task(ocr_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Profit OCR Service", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class OverlayTargetIn(BaseModel):
    value: float
    label: str = ""


class PositionsUpdate(BaseModel):
    """Novos clientes enviam targets; legado envia apenas positions."""

    targets: Optional[List[OverlayTargetIn]] = None
    positions: Optional[List[float]] = None


class AnalysisRoiRect(BaseModel):
    left: int
    top: int
    width: int
    height: int


class AnalysisRoiBody(BaseModel):
    """Retângulo em pixels físicos de ecrã (mss). `rect: null` limpa."""

    rect: Optional[AnalysisRoiRect] = None


def _targets_from_ws_message(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = msg.get("targets")
    if isinstance(raw, list) and raw:
        out: List[Dict[str, Any]] = []
        for t in raw:
            if isinstance(t, dict) and "value" in t:
                out.append(
                    {
                        "value": float(t["value"]),
                        "label": str(t.get("label") or ""),
                    }
                )
        return out
    pos = msg.get("positions")
    if isinstance(pos, list):
        return [{"value": float(p), "label": ""} for p in pos]
    return []


def _apply_targets(targets: List[Dict[str, Any]]) -> None:
    state["targets"] = targets
    state["positions"] = [t["value"] for t in targets]


def get_dpi_scale() -> float:
    try:
        user32 = ctypes.windll.user32
        dc = user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)
        user32.ReleaseDC(0, dc)
        return dpi / 96.0
    except Exception:
        return 1.0


def find_profit_window() -> Optional[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []

    def _cb(hwnd: int, _unused: Any):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).lower()
        if "profit" in title or "nelogica" in title:
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            l, t, r, b = _logical_rect_to_physical(hwnd, l, t, r, b)
            found.append(
                {
                    "hwnd": hwnd,
                    "title": win32gui.GetWindowText(hwnd),
                    "left": l,
                    "top": t,
                    "right": r,
                    "bottom": b,
                    "width": r - l,
                    "height": b - t,
                }
            )

    win32gui.EnumWindows(_cb, None)
    if not found:
        return None
    return max(found, key=lambda w: w["width"] * w["height"])


def resolve_profit_window(now_monotonic: float) -> Optional[Dict[str, Any]]:
    """Usa cache de hwnd/rect entre ciclos para evitar EnumWindows constante."""
    cached = state.get("window_cache")
    if isinstance(cached, dict):
        hwnd = cached.get("hwnd")
        if isinstance(hwnd, int):
            try:
                if win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd):
                    l, t, r, b = win32gui.GetWindowRect(hwnd)
                    l, t, r, b = _logical_rect_to_physical(hwnd, l, t, r, b)
                    if r > l and b > t:
                        cached["left"] = l
                        cached["top"] = t
                        cached["right"] = r
                        cached["bottom"] = b
                        cached["width"] = r - l
                        cached["height"] = b - t
                        cached["title"] = win32gui.GetWindowText(hwnd)
                        state["window_cache"] = cached
                        return cached
            except Exception:
                state["window_cache"] = None

    last_scan = float(state.get("last_window_scan", 0.0))
    if (now_monotonic - last_scan) * 1000.0 < WINDOW_SCAN_INTERVAL_MS:
        return None

    state["last_window_scan"] = now_monotonic
    window = find_profit_window()
    state["window_cache"] = window
    return window


def capture_region(left: int, top: int, width: int, height: int) -> Image.Image:
    with mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def preprocess(img: Image.Image, threshold: int = 140, contrast: float = 2.5) -> tuple[Image.Image, int]:
    img = img.convert("L")
    scale = 3
    img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    img = img.point(lambda x: 0 if x < threshold else 255, "1")
    return img, scale


def parse_number(text: str) -> Optional[float]:
    text = text.strip().replace(" ", "")
    if not text:
        return None
    text = re.sub(r"[^\d.,-]", "", text)
    if not text:
        return None
    try:
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "." in text and "," not in text:
            # BR comum no Profit: 185.240 (pontos) = 185240, nao 185.24
            dot_parts = text.split(".")
            if len(dot_parts) > 1 and all(len(p) == 3 for p in dot_parts[1:]):
                text = "".join(dot_parts)
        elif "," in text:
            text = text.replace(",", ".")
        return float(text)
    except ValueError:
        return None


def extract_y_axis(chart: Dict[str, Any]) -> List[Dict[str, float]]:
    ax_w = max(70, int(chart["width"] * Y_AXIS_FRAC))
    left = chart["left"] + chart["width"] - ax_w
    top = chart["top"]
    width = ax_w
    height = max(80, chart["height"] - AXIS_BOTTOM_CROP_PX)

    raw = capture_region(left, top, width, height)

    # Passo 1 rapido; passos extras apenas quando o baseline nao for suficiente.
    passes = [
        {"threshold": 140, "contrast": 2.5, "psm": 6},
        {"threshold": 120, "contrast": 3.0, "psm": 6},
        {"threshold": 165, "contrast": 2.1, "psm": 11},
        # Temas escuros / contraste baixo (outro monitor ou escala de texto)
        {"threshold": 100, "contrast": 3.2, "psm": 6},
        {"threshold": 85, "contrast": 3.5, "psm": 11},
    ]

    labels: List[Dict[str, float]] = []

    def _run_pass(p: Dict[str, float]) -> None:
        proc, scale = preprocess(raw, threshold=p["threshold"], contrast=p["contrast"])
        cfg = f"--psm {p['psm']} --oem 3 -c tessedit_char_whitelist=0123456789.,-+"
        data = pytesseract.image_to_data(proc, config=cfg, output_type=pytesseract.Output.DICT)
        for i, word in enumerate(data["text"]):
            word = word.strip()
            conf = int(data["conf"][i]) if str(data["conf"][i]).strip() else -1
            if conf < MIN_CONF or not word:
                continue
            val = parse_number(word)
            if val is None:
                continue
            y_orig = (data["top"][i] + data["height"][i] / 2) / scale
            y_screen = top + y_orig
            labels.append({"value": float(val), "y_screen": float(y_screen)})

    _run_pass(passes[0])
    if len(labels) < 2:
        for p in passes[1:]:
            _run_pass(p)
            if len(labels) >= 2:
                break

    labels.sort(key=lambda x: x["y_screen"])
    deduped: List[Dict[str, float]] = []
    for lb in labels:
        if deduped and abs(lb["y_screen"] - deduped[-1]["y_screen"]) < 6:
            continue
        deduped.append(lb)

    # Remove outliers extremos (ex.: "179500" vindo de "179.500"/"00s").
    if deduped:
        abs_vals = sorted(abs(lb["value"]) for lb in deduped)
        med = abs_vals[len(abs_vals) // 2]
        max_abs_allowed = max(5000.0, med * 20.0 + 50.0)
        if med >= 1000:
            min_abs_allowed = med * 0.2
        else:
            min_abs_allowed = 0.0
        filtered = [
            lb
            for lb in deduped
            if min_abs_allowed <= abs(lb["value"]) <= max_abs_allowed
        ]
    else:
        filtered = []

    return filtered


def value_to_y(value: float, labels: List[Dict[str, float]]) -> Optional[int]:
    if len(labels) < 2:
        return None

    by_val = sorted(labels, key=lambda x: x["value"])
    for i in range(len(by_val) - 1):
        lo, hi = by_val[i], by_val[i + 1]
        if lo["value"] == hi["value"]:
            continue
        if min(lo["value"], hi["value"]) <= value <= max(lo["value"], hi["value"]):
            t = (value - lo["value"]) / (hi["value"] - lo["value"])
            return int(lo["y_screen"] + t * (hi["y_screen"] - lo["y_screen"]))

    lo, hi = (by_val[0], by_val[1]) if value < by_val[0]["value"] else (by_val[-2], by_val[-1])
    v_range = hi["value"] - lo["value"]
    if abs(v_range) < 1e-9:
        return None
    t = (value - lo["value"]) / v_range
    return int(lo["y_screen"] + t * (hi["y_screen"] - lo["y_screen"]))


def fit_value_axis(labels: List[Dict[str, float]]) -> Optional[Dict[str, float]]:
    """
    Ajuste robusto value = m*y + b (Theil-Sen simplificado).
    Retorna tambem gap aproximado em valor por pixel.
    """
    if len(labels) < 2:
        return None

    slopes: List[float] = []
    n = len(labels)
    for i in range(n):
        yi = labels[i]["y_screen"]
        vi = labels[i]["value"]
        for j in range(i + 1, n):
            yj = labels[j]["y_screen"]
            vj = labels[j]["value"]
            dy = yj - yi
            if abs(dy) < 5:
                continue
            slopes.append((vj - vi) / dy)

    if not slopes:
        return None

    negative_slopes = sorted(s for s in slopes if s < 0)
    all_slopes = sorted(slopes)
    # Eixo Y do Profit tipicamente decresce com y crescente.
    slope = (
        negative_slopes[len(negative_slopes) // 2]
        if len(negative_slopes) >= max(3, len(all_slopes) // 4)
        else all_slopes[len(all_slopes) // 2]
    )
    if abs(slope) < 1e-9:
        return None

    intercepts = sorted(lb["value"] - slope * lb["y_screen"] for lb in labels)
    intercept = intercepts[len(intercepts) // 2]
    value_per_px = abs(slope)
    return {"slope": slope, "intercept": intercept, "value_per_px": value_per_px}


def sanitize_axis_labels(labels: List[Dict[str, float]]) -> tuple[List[Dict[str, float]], Dict[str, Any]]:
    """
    Mantém labels coerentes com um eixo de preço monotónico.
    1) monotonicidade (y crescente -> value decrescente)
    2) rejeição de outlier por value/px via mediana + MAD
    """
    if len(labels) < 2:
        return labels, {"raw_labels": len(labels), "kept_labels": len(labels), "rejected": 0}

    by_y = sorted(labels, key=lambda x: x["y_screen"])
    kept = [by_y[0]]
    monotonic_rejects = 0
    for lb in by_y[1:]:
        prev = kept[-1]
        dy = lb["y_screen"] - prev["y_screen"]
        dv = lb["value"] - prev["value"]
        if dy <= 2:
            monotonic_rejects += 1
            continue
        if dv >= 0:
            monotonic_rejects += 1
            continue
        kept.append(lb)

    if len(kept) < 2:
        return by_y[:2], {
            "raw_labels": len(labels),
            "kept_labels": min(2, len(by_y)),
            "rejected": len(labels) - min(2, len(by_y)),
            "rejected_monotonic": monotonic_rejects,
            "rejected_slope_outlier": 0,
        }

    seg_slopes: List[float] = []
    for i in range(1, len(kept)):
        dy = kept[i]["y_screen"] - kept[i - 1]["y_screen"]
        dv = kept[i]["value"] - kept[i - 1]["value"]
        if dy > 0 and dv < 0:
            seg_slopes.append(abs(dv / dy))

    if not seg_slopes:
        return kept, {
            "raw_labels": len(labels),
            "kept_labels": len(kept),
            "rejected": len(labels) - len(kept),
            "rejected_monotonic": monotonic_rejects,
            "rejected_slope_outlier": 0,
        }

    sorted_slopes = sorted(seg_slopes)
    median = sorted_slopes[len(sorted_slopes) // 2]
    deviations = sorted(abs(x - median) for x in sorted_slopes)
    mad = deviations[len(deviations) // 2]
    tolerance = max(0.02, mad * 2.8, median * 0.35)

    filtered = [kept[0]]
    slope_rejects = 0
    for i in range(1, len(kept)):
        prev = filtered[-1]
        cur = kept[i]
        dy = cur["y_screen"] - prev["y_screen"]
        dv = cur["value"] - prev["value"]
        if dy <= 0 or dv >= 0:
            slope_rejects += 1
            continue
        slope = abs(dv / dy)
        if abs(slope - median) > tolerance:
            slope_rejects += 1
            continue
        filtered.append(cur)

    if len(filtered) < 2:
        filtered = kept[:2]

    return filtered, {
        "raw_labels": len(labels),
        "kept_labels": len(filtered),
        "rejected": len(labels) - len(filtered),
        "rejected_monotonic": monotonic_rejects,
        "rejected_slope_outlier": slope_rejects,
        "segment_slope_median": median,
        "segment_slope_mad": mad,
    }


def compute_axis_deltas(labels: List[Dict[str, float]]) -> Optional[Dict[str, Any]]:
    if len(labels) < 2:
        return None
    by_y = sorted(labels, key=lambda x: x["y_screen"])
    first = by_y[0]
    last = by_y[-1]
    intervals: List[Dict[str, float]] = []
    for i in range(1, len(by_y)):
        prev = by_y[i - 1]
        cur = by_y[i]
        value_delta = float(cur["value"] - prev["value"])
        y_delta = float(cur["y_screen"] - prev["y_screen"])
        value_per_px_segment = abs(value_delta / y_delta) if abs(y_delta) > 1e-9 else math.inf
        intervals.append(
            {
                "i": i - 1,
                "value_delta": value_delta,
                "y_delta": y_delta,
                "value_per_px_segment": value_per_px_segment,
            }
        )
    return {
        "delta_first_last_value": float(last["value"] - first["value"]),
        "delta_first_last_y": float(last["y_screen"] - first["y_screen"]),
        "delta_intervals": intervals,
        "labels_count": len(by_y),
    }


def blend_axis_with_hysteresis(new_axis: Dict[str, float]) -> Dict[str, float]:
    prev = state.get("_axis_ema")
    if not isinstance(prev, dict):
        state["_axis_ema"] = new_axis
        state["_axis_jump_count"] = 0
        return new_axis

    prev_slope = float(prev.get("slope", 0.0))
    prev_intercept = float(prev.get("intercept", 0.0))
    slope_rel_jump = abs(new_axis["slope"] - prev_slope) / max(abs(prev_slope), 1e-9)
    intercept_jump = abs(new_axis["intercept"] - prev_intercept)
    jump_limit = max(6.0, float(prev.get("value_per_px", 0.0)) * 8.0)
    jump_detected = slope_rel_jump > 0.10 or intercept_jump > jump_limit

    if jump_detected:
        state["_axis_jump_count"] = int(state.get("_axis_jump_count", 0)) + 1
        beta = min(0.14, AXIS_BLEND_BETA)
    else:
        state["_axis_jump_count"] = 0
        beta = AXIS_BLEND_BETA

    blended = {
        "slope": prev_slope * (1.0 - beta) + new_axis["slope"] * beta,
        "intercept": prev_intercept * (1.0 - beta) + new_axis["intercept"] * beta,
    }
    blended["value_per_px"] = abs(blended["slope"])
    state["_axis_ema"] = blended
    return blended


def value_to_y_hybrid(value: float, labels: List[Dict[str, float]], axis: Dict[str, float]) -> int:
    if len(labels) >= 2:
        by_val = sorted(labels, key=lambda x: x["value"])
        for i in range(len(by_val) - 1):
            lo, hi = by_val[i], by_val[i + 1]
            if hi["value"] == lo["value"]:
                continue
            if lo["value"] <= value <= hi["value"]:
                t = (value - lo["value"]) / (hi["value"] - lo["value"])
                return int(round(lo["y_screen"] + t * (hi["y_screen"] - lo["y_screen"])))
    yf = (value - axis["intercept"]) / axis["slope"]
    return int(round(yf))


def extract_analysis_sample(rect: Dict[str, Any]) -> Dict[str, Any]:
    """
    OCR numa região definida pelo utilizador (painéis, legendas, etc.).
    Não participa no ajuste do eixo nem nas posições das linhas do overlay.
    """
    left = int(rect["left"])
    top = int(rect["top"])
    w = max(1, int(rect["width"]))
    h = max(1, int(rect["height"]))
    img = capture_region(left, top, w, h)
    gray = img.convert("L")
    gray = ImageEnhance.Contrast(gray).enhance(2.3)
    cfg = "--psm 6 --oem 3"
    try:
        text = pytesseract.image_to_string(gray, config=cfg).strip()
        err_tex = ""
    except Exception as tex_exc:
        text = ""
        err_tex = str(tex_exc)
    numbers: List[float] = []
    seen: set = set()
    try:
        data = pytesseract.image_to_data(
            gray, config=cfg, output_type=pytesseract.Output.DICT
        )
        for i, word in enumerate(data["text"]):
            word = (word or "").strip()
            if not word:
                continue
            conf = int(data["conf"][i]) if str(data["conf"][i]).strip() else -1
            if conf < 10:
                continue
            val = parse_number(word)
            if val is None:
                continue
            key = round(val, 4)
            if key not in seen:
                seen.add(key)
                numbers.append(float(val))
    except Exception:
        pass
    out: Dict[str, Any] = {
        "text": text[:4000],
        "numbers": numbers[:80],
        "ts": time.time(),
    }
    if err_tex:
        out["tesseract_error"] = err_tex[:500]
    return out


def apply_line_y_smoothing(
    lines: List[Dict[str, Any]], targets: List[Dict[str, Any]]
) -> None:
    """EMA em y_screen para reduzir jitter; salta EMA se o Y novo divergir muito (eixo OCR a estabilizar)."""
    if LINE_Y_SMOOTH_ALPHA <= 0 or not lines:
        return
    tk = tuple(
        (round(float(t.get("value", 0)), 4), str(t.get("label") or ""))
        for t in targets
    )
    if state.get("_smooth_key") != tk:
        state["_line_y_smooth"] = {}
        state["_smooth_key"] = tk
    ema: Dict[int, float] = state.setdefault("_line_y_smooth", {})
    alpha = min(1.0, max(0.01, LINE_Y_SMOOTH_ALPHA))
    chart = state.get("chart_rect") if isinstance(state.get("chart_rect"), dict) else {}
    ch = float(chart.get("height") or 0)
    snap_px = max(float(LINE_Y_SNAP_PX), (ch * 0.025) if ch > 0 else float(LINE_Y_SNAP_PX))
    for idx, ln in enumerate(lines):
        y = float(ln["y_screen"])
        prev = ema.get(idx)
        if prev is None:
            ema[idx] = y
        elif abs(y - prev) >= snap_px:
            ema[idx] = y
        else:
            ema[idx] = alpha * y + (1.0 - alpha) * prev
        ln["y_screen"] = int(round(ema[idx]))


async def ocr_loop():
    global first_ok_logged
    while True:
        t0 = time.monotonic()
        try:
            window = resolve_profit_window(t0)
            if not window:
                state["status"] = "window_not_found"
                state["lines"] = []
            else:
                chart = {
                    "left": window["left"],
                    "top": window["top"] + TOOLBAR_H,
                    "width": window["width"],
                    "height": window["height"] - TOOLBAR_H,
                }
                state["chart_rect"] = chart
                labels_raw = extract_y_axis(chart)
                labels, diagnostics = sanitize_axis_labels(labels_raw)
                state["axis_diagnostics"] = diagnostics

                if len(labels) >= 2:
                    state["axis_deltas"] = compute_axis_deltas(labels)
                    axis_fit = fit_value_axis(labels)
                    axis = blend_axis_with_hysteresis(axis_fit) if axis_fit is not None else None
                    if axis is None:
                        state["status"] = "ocr_axis_fit_failed"
                        state["lines"] = []
                    else:
                        vals = [lb["value"] for lb in labels]
                        v_axis_min = min(vals)
                        v_axis_max = max(vals)
                        state["y_min"] = v_axis_min
                        state["y_max"] = v_axis_max
                        state["status"] = "ok"
                        if not first_ok_logged:
                            first_ok_logged = True
                            elapsed_ms = int((time.monotonic() - service_started_at) * 1000)
                            print(f"[overlay-latency] ocr_first_ok elapsed_ms={elapsed_ms}")
                        lines = []
                        chart_top = float(chart["top"])
                        chart_bottom = float(chart["top"] + chart["height"])
                        for idx, t in enumerate(state["targets"]):
                            pos = float(t["value"])
                            y_screen = value_to_y_hybrid(pos, labels, axis)
                            # Preço fora do intervalo visível no eixo OCR: não usar y híbrido
                            # (oscila com blend_axis_with_hysteresis) + clamp geométrico — fixa na borda
                            # estável. Eixo Profit: y cresce para baixo, valor decresce (topo = maior preço).
                            if pos > v_axis_max:
                                clamped_y = int(round(chart_top))
                                oob = True
                            elif pos < v_axis_min:
                                clamped_y = int(round(chart_bottom))
                                oob = True
                            else:
                                clamped_y = int(
                                    round(max(chart_top, min(float(y_screen), chart_bottom)))
                                )
                                oob = float(y_screen) != float(clamped_y)
                            lbl = str(t.get("label") or "")
                            lines.append(
                                {
                                    "value": pos,
                                    "y_screen": clamped_y,
                                    "color": line_color_for_label(lbl, idx),
                                    "chart_left": window["left"],
                                    "chart_right": window["right"],
                                    "label": lbl,
                                    "out_of_bounds": oob,
                                }
                            )
                        apply_line_y_smoothing(lines, state["targets"])
                        state["lines"] = lines
                else:
                    state["axis_deltas"] = None
                    elapsed_svc = time.monotonic() - service_started_at
                    if len(labels) == 0 and elapsed_svc < AXIS_WARMUP_SECS:
                        state["status"] = "ocr_axis_warming"
                    else:
                        state["status"] = f"ocr_insufficient_labels:{len(labels)}"
                    state["lines"] = []
        except Exception as exc:
            state["status"] = f"error: {exc}"
            state["lines"] = []

        state["last_update"] = time.time()

        analysis_sample: Optional[Dict[str, Any]] = None
        roi = state.get("analysis_roi")
        if isinstance(roi, dict) and int(roi.get("width", 0)) >= 4 and int(roi.get("height", 0)) >= 4:
            try:
                analysis_sample = extract_analysis_sample(roi)
            except Exception as analy_exc:
                analysis_sample = {
                    "text": "",
                    "numbers": [],
                    "error": str(analy_exc)[:500],
                    "ts": time.time(),
                }
            state["analysis_sample"] = analysis_sample
        else:
            state["analysis_sample"] = None

        if clients:
            payload = json.dumps(
                {
                    "type": "overlay_update",
                    "data": {
                        "lines": state["lines"],
                        "status": state["status"],
                        "y_min": state["y_min"],
                        "y_max": state["y_max"],
                        "chart_rect": state["chart_rect"],
                        "axis_deltas": state.get("axis_deltas"),
                        "axis_diagnostics": state.get("axis_diagnostics"),
                        "analysis_roi": state.get("analysis_roi"),
                        "analysis_sample": analysis_sample,
                        "ts": state["last_update"],
                    },
                }
            )
            dead: List[WebSocket] = []
            for ws in clients:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                if ws in clients:
                    clients.remove(ws)

        elapsed = time.monotonic() - t0
        await asyncio.sleep(max(0.0, REFRESH_MS / 1000 - elapsed))


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    await websocket.send_text(
        json.dumps(
            {
                "type": "overlay_update",
                "data": {
                    "lines": state["lines"],
                    "status": state["status"],
                    "y_min": state["y_min"],
                    "y_max": state["y_max"],
                    "axis_deltas": state.get("axis_deltas"),
                    "axis_diagnostics": state.get("axis_diagnostics"),
                    "analysis_roi": state.get("analysis_roi"),
                    "analysis_sample": state.get("analysis_sample"),
                },
            }
        )
    )
    try:
        async for raw in websocket.iter_text():
            msg = json.loads(raw)
            if msg.get("type") == "set_positions":
                _apply_targets(_targets_from_ws_message(msg))
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in clients:
            clients.remove(websocket)


@app.post("/positions")
async def set_positions(body: PositionsUpdate):
    if body.targets is not None:
        _apply_targets(
            [{"value": t.value, "label": t.label} for t in body.targets]
        )
    elif body.positions is not None:
        _apply_targets(
            [{"value": float(p), "label": ""} for p in body.positions]
        )
    return {"ok": True, "targets": state["targets"], "positions": state["positions"]}


@app.post("/analysis_roi")
async def set_analysis_roi(body: AnalysisRoiBody):
    if body.rect is None:
        state["analysis_roi"] = None
        state["analysis_sample"] = None
    else:
        state["analysis_roi"] = {
            "left": int(body.rect.left),
            "top": int(body.rect.top),
            "width": max(1, int(body.rect.width)),
            "height": max(1, int(body.rect.height)),
        }
    return {"ok": True, "analysis_roi": state["analysis_roi"]}


@app.get("/status")
async def get_status():
    return {
        "status": state["status"],
        "targets": state["targets"],
        "positions": state["positions"],
        "lines": state["lines"],
        "y_min": state["y_min"],
        "y_max": state["y_max"],
        "axis_deltas": state.get("axis_deltas"),
        "axis_diagnostics": state.get("axis_diagnostics"),
        "dpi_scale": state["dpi_scale"],
        "last_update": state["last_update"],
        "analysis_roi": state.get("analysis_roi"),
        "analysis_sample": state.get("analysis_sample"),
    }


if __name__ == "__main__":
    configure_tesseract_cmd()
    print(f"[OCR] Iniciando serviço OCR na porta {OCR_PORT}...")
    uvicorn.run(app, host="127.0.0.1", port=OCR_PORT, log_level="warning")
