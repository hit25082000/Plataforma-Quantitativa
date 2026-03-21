"""
profit_ocr_service.py
=====================
Serviço OCR para o Overlay do Gráfico de Profit.

- Detecta a janela do Profit Pro via Win32
- Captura a faixa do eixo Y (direita do gráfico)
- Extrai labels numéricos via Tesseract
- Interpola posições (valor → pixel Y) para cada posição configurada
- Publica atualizações via WebSocket a cada ~400 ms

Portas:
  HTTP  → 5556  (GET /status | POST /positions | GET /dpi)
  WS    → ws://127.0.0.1:5556/ws
"""

import asyncio
import json
import re
import time
import sys
from typing import Optional, List, Dict, Any

try:
    import mss
    from PIL import Image, ImageEnhance
    import pytesseract
    import win32gui
    import win32api
    import win32con
    import ctypes
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    from pydantic import BaseModel
except ImportError as e:
    print(f"[OCR] Dependência ausente: {e}")
    print("Execute: pip install mss Pillow pytesseract pywin32 fastapi uvicorn")
    sys.exit(1)

# ─── Configurações ────────────────────────────────────────────────────────────
OCR_PORT       = 5556
REFRESH_MS     = 400          # Ciclo de captura
Y_AXIS_FRAC    = 0.10         # Fração da largura usada para capturar o eixo Y
TOOLBAR_H      = 90           # Altura estimada da toolbar do Profit (px lógicos)
MIN_CONF       = 35           # Confiança mínima do Tesseract (0-100)
COLORS = ["#00FF88", "#FF4444", "#FFB800", "#00CCFF", "#FF88FF", "#FFFFFF"]

# ─── Estado global ────────────────────────────────────────────────────────────
state: Dict[str, Any] = {
    "positions": [],      # Valores alvo configurados pelo usuário
    "chart_rect": None,   # {left, top, width, height} em pixels físicos
    "y_min": None,
    "y_max": None,
    "lines": [],          # [{value, y_screen, color, chart_left, chart_right}]
    "status": "searching",
    "last_update": 0.0,
    "dpi_scale": 1.0,
}

clients: List[WebSocket] = []

# ─── FastAPI ──────────────────────────────────────────────────────────────────
app = FastAPI(title="Profit OCR Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class PositionsUpdate(BaseModel):
    positions: List[float]


# ─── DPI ──────────────────────────────────────────────────────────────────────
def get_dpi_scale() -> float:
    """Retorna o fator de escala DPI do monitor principal."""
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        dc = user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)  # LOGPIXELSX
        user32.ReleaseDC(0, dc)
        return dpi / 96.0
    except Exception:
        return 1.0


# ─── Win32: localizar janela do Profit ───────────────────────────────────────
def find_profit_window() -> Optional[Dict]:
    """
    Percorre janelas visíveis e retorna a maior que contenha
    'profit' ou 'nelogica' no título (case-insensitive).
    Coordenadas em pixels físicos (DPI-aware).
    """
    found: List[Dict] = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).lower()
        if "profit" in title or "nelogica" in title:
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            found.append({
                "hwnd": hwnd,
                "title": win32gui.GetWindowText(hwnd),
                "left": l, "top": t, "right": r, "bottom": b,
                "width": r - l, "height": b - t,
            })

    win32gui.EnumWindows(_cb, None)
    if not found:
        return None
    return max(found, key=lambda w: w["width"] * w["height"])


# ─── Captura de tela ──────────────────────────────────────────────────────────
def capture_region(left: int, top: int, width: int, height: int) -> Image.Image:
    """Captura região da tela via mss (coordenadas em pixels físicos)."""
    with mss.mss() as sct:
        mon = {"left": left, "top": top, "width": width, "height": height}
        shot = sct.grab(mon)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


# ─── Pré-processamento da imagem para OCR ────────────────────────────────────
def preprocess(img: Image.Image) -> Image.Image:
    """Converte, escala e binariza para melhor leitura de números."""
    img = img.convert("L")
    scale = 3
    img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(2.5)
    # Binarização adaptativa simples
    img = img.point(lambda x: 0 if x < 140 else 255, "1")
    return img, scale


# ─── Parsing numérico (suporte BR e US) ──────────────────────────────────────
def parse_number(text: str) -> Optional[float]:
    """
    Converte texto OCR para float.
    Aceita formatos: 1234.56 | 1.234,56 | -1234 | 1,234
    """
    text = text.strip().replace(" ", "")
    if not text:
        return None
    # Remove caracteres inválidos, mantém dígitos, ponto, vírgula, sinal
    text = re.sub(r"[^\d.,-]", "", text)
    if not text:
        return None
    try:
        # Formato brasileiro: vírgula como decimal, ponto como milhar
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "," in text:
            text = text.replace(",", ".")
        return float(text)
    except ValueError:
        return None


# ─── OCR do eixo Y ───────────────────────────────────────────────────────────
def extract_y_axis(chart: Dict) -> List[Dict]:
    """
    Captura a faixa direita do gráfico (eixo Y do Profit),
    executa OCR e retorna lista de {value, y_screen}.
    """
    ax_w = max(70, int(chart["width"] * Y_AXIS_FRAC))
    left  = chart["left"] + chart["width"] - ax_w
    top   = chart["top"]
    width = ax_w
    height = chart["height"]

    raw = capture_region(left, top, width, height)
    proc, scale = preprocess(raw)

    cfg = "--psm 6 --oem 3 -c tessedit_char_whitelist=0123456789.,-+"
    data = pytesseract.image_to_data(
        proc, config=cfg, output_type=pytesseract.Output.DICT
    )

    labels = []
    for i, word in enumerate(data["text"]):
        word = word.strip()
        if data["conf"][i] < MIN_CONF or not word:
            continue
        val = parse_number(word)
        if val is None:
            continue
        # Centro Y da palavra em coordenadas da imagem original
        y_orig = (data["top"][i] + data["height"][i] / 2) / scale
        y_screen = top + y_orig
        labels.append({"value": val, "y_screen": float(y_screen)})

    # Remove duplicatas próximas
    labels.sort(key=lambda x: x["y_screen"])
    deduped = []
    for lb in labels:
        if deduped and abs(lb["y_screen"] - deduped[-1]["y_screen"]) < 6:
            continue
        deduped.append(lb)

    return deduped


# ─── Interpolação valor → pixel Y ────────────────────────────────────────────
def value_to_y(value: float, labels: List[Dict]) -> Optional[int]:
    """
    Mapeia um valor de profit para coordenada Y na tela via interpolação/
    extrapolação linear entre os labels do eixo Y.
    """
    if len(labels) < 2:
        return None

    # Ordena por valor (ascendente)
    by_val = sorted(labels, key=lambda x: x["value"])

    # Interpolação
    for i in range(len(by_val) - 1):
        lo, hi = by_val[i], by_val[i + 1]
        v_lo, v_hi = lo["value"], hi["value"]
        if v_lo == v_hi:
            continue
        if min(v_lo, v_hi) <= value <= max(v_lo, v_hi):
            t = (value - v_lo) / (v_hi - v_lo)
            return int(lo["y_screen"] + t * (hi["y_screen"] - lo["y_screen"]))

    # Extrapolação pelos extremos
    if value < by_val[0]["value"]:
        lo, hi = by_val[0], by_val[1]
    else:
        lo, hi = by_val[-2], by_val[-1]

    v_range = hi["value"] - lo["value"]
    if abs(v_range) < 1e-9:
        return None

    t = (value - lo["value"]) / v_range
    return int(lo["y_screen"] + t * (hi["y_screen"] - lo["y_screen"]))


# ─── Loop principal de OCR ────────────────────────────────────────────────────
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
                    "left":   window["left"],
                    "top":    window["top"] + TOOLBAR_H,
                    "width":  window["width"],
                    "height": window["height"] - TOOLBAR_H,
                }
                state["chart_rect"] = chart

                labels = extract_y_axis(chart)

                if len(labels) >= 2:
                    vals = [lb["value"] for lb in labels]
                    state["y_min"] = min(vals)
                    state["y_max"] = max(vals)
                    state["status"] = "ok"

                    lines = []
                    for idx, pos in enumerate(state["positions"]):
                        y_screen = value_to_y(pos, labels)
                        if y_screen is not None:
                            lines.append({
                                "value":       pos,
                                "y_screen":    y_screen,
                                "color":       COLORS[idx % len(COLORS)],
                                "chart_left":  window["left"],
                                "chart_right": window["right"],
                            })
                    state["lines"] = lines
                else:
                    state["status"] = "ocr_insufficient_labels"
                    state["lines"] = []

        except Exception as exc:
            state["status"] = f"error: {exc}"
            state["lines"] = []

        state["last_update"] = time.time()

        # Broadcast para todos os clientes WS
        if clients:
            payload = json.dumps({
                "type": "overlay_update",
                "data": {
                    "lines":      state["lines"],
                    "status":     state["status"],
                    "y_min":      state["y_min"],
                    "y_max":      state["y_max"],
                    "chart_rect": state["chart_rect"],
                    "ts":         state["last_update"],
                },
            })
            dead = []
            for ws in clients:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                clients.remove(ws)

        elapsed = time.monotonic() - t0
        await asyncio.sleep(max(0.0, REFRESH_MS / 1000 - elapsed))


@app.on_event("startup")
async def _startup():
    state["dpi_scale"] = get_dpi_scale()
    asyncio.create_task(ocr_loop())


# ─── WebSocket ────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    # Envia estado atual imediatamente
    await websocket.send_text(json.dumps({
        "type": "overlay_update",
        "data": {
            "lines":  state["lines"],
            "status": state["status"],
            "y_min":  state["y_min"],
            "y_max":  state["y_max"],
        },
    }))
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


# ─── HTTP endpoints ───────────────────────────────────────────────────────────
@app.post("/positions")
async def set_positions(body: PositionsUpdate):
    state["positions"] = body.positions
    return {"ok": True, "positions": state["positions"]}


@app.get("/status")
async def get_status():
    return {
        "status":     state["status"],
        "positions":  state["positions"],
        "lines":      state["lines"],
        "y_min":      state["y_min"],
        "y_max":      state["y_max"],
        "dpi_scale":  state["dpi_scale"],
        "last_update": state["last_update"],
    }


@app.get("/dpi")
async def get_dpi():
    return {"dpi_scale": state["dpi_scale"]}


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[OCR] Iniciando serviço OCR na porta {OCR_PORT}...")
    uvicorn.run(app, host="127.0.0.1", port=OCR_PORT, log_level="warning")
