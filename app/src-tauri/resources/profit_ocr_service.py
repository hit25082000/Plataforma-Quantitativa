"""
Serviço OCR para o Overlay do gráfico Profit.
"""

import asyncio
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

try:
    import ctypes
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
OCR_PORT = 5558
REFRESH_MS = 400
Y_AXIS_FRAC = 0.14
TOOLBAR_H = 90
AXIS_BOTTOM_CROP_PX = 42
MIN_CONF = 22
COLORS = ["#00FF88", "#FF4444", "#FFB800", "#00CCFF", "#FF88FF", "#FFFFFF"]

state: Dict[str, Any] = {
    "positions": [],
    "chart_rect": None,
    "y_min": None,
    "y_max": None,
    "lines": [],
    "status": "searching",
    "last_update": 0.0,
    "dpi_scale": 1.0,
}
clients: List[WebSocket] = []

app = FastAPI(title="Profit OCR Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class PositionsUpdate(BaseModel):
    positions: List[float]


def get_dpi_scale() -> float:
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
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

    # Multiplos passes para aumentar chance de leitura em temas/fontes diferentes.
    passes = [
        {"threshold": 140, "contrast": 2.5, "psm": 6},
        {"threshold": 120, "contrast": 3.0, "psm": 6},
        {"threshold": 165, "contrast": 2.1, "psm": 11},
    ]

    labels: List[Dict[str, float]] = []
    for p in passes:
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


async def ocr_loop():
    while True:
        t0 = time.monotonic()
        try:
            window = find_profit_window()
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
                labels = extract_y_axis(chart)

                if len(labels) >= 2:
                    axis = fit_value_axis(labels)
                    if axis is None:
                        state["status"] = "ocr_axis_fit_failed"
                        state["lines"] = []
                    else:
                        vals = [lb["value"] for lb in labels]
                        state["y_min"] = min(vals)
                        state["y_max"] = max(vals)
                        state["status"] = "ok"
                        lines = []
                        for idx, pos in enumerate(state["positions"]):
                            yf = (float(pos) - axis["intercept"]) / axis["slope"]
                            y_screen = int(round(yf))
                            if chart["top"] <= y_screen <= chart["top"] + chart["height"]:
                                lines.append(
                                    {
                                        "value": float(pos),
                                        "y_screen": y_screen,
                                        "color": COLORS[idx % len(COLORS)],
                                        "chart_left": window["left"],
                                        "chart_right": window["right"],
                                    }
                                )
                        state["lines"] = lines
                else:
                    state["status"] = f"ocr_insufficient_labels:{len(labels)}"
                    state["lines"] = []
        except Exception as exc:
            state["status"] = f"error: {exc}"
            state["lines"] = []

        state["last_update"] = time.time()

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


@app.on_event("startup")
async def startup_event():
    state["dpi_scale"] = get_dpi_scale()
    asyncio.create_task(ocr_loop())


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
                },
            }
        )
    )
    try:
        async for raw in websocket.iter_text():
            msg = json.loads(raw)
            if msg.get("type") == "set_positions":
                state["positions"] = [float(p) for p in msg.get("positions", [])]
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in clients:
            clients.remove(websocket)


@app.post("/positions")
async def set_positions(body: PositionsUpdate):
    state["positions"] = body.positions
    return {"ok": True, "positions": state["positions"]}


@app.get("/status")
async def get_status():
    return {
        "status": state["status"],
        "positions": state["positions"],
        "lines": state["lines"],
        "y_min": state["y_min"],
        "y_max": state["y_max"],
        "dpi_scale": state["dpi_scale"],
        "last_update": state["last_update"],
    }


if __name__ == "__main__":
    configure_tesseract_cmd()
    print(f"[OCR] Iniciando serviço OCR na porta {OCR_PORT}...")
    uvicorn.run(app, host="127.0.0.1", port=OCR_PORT, log_level="warning")
