// frontend/src/pages/OverlayPage.tsx
//
// Renderizado na janela Tauri "profit-overlay" (transparente, full-screen).
// Conecta ao serviço OCR via WebSocket e desenha linhas horizontais
// em SVG full-screen nas coordenadas Y retornadas pelo OCR.

import { useCallback, useEffect, useRef, useState } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────
interface OverlayLine {
  value: number;
  y_screen: number;
  color: string;
  chart_left: number;
  chart_right: number;
}

interface OverlayData {
  lines: OverlayLine[];
  status: string;
  y_min: number | null;
  y_max: number | null;
  chart_rect: { left: number; top: number; width: number; height: number } | null;
  ts?: number;
}

// ─── Constantes ───────────────────────────────────────────────────────────────
const OCR_WS = "ws://127.0.0.1:5558/ws";
const LABEL_W = 90;
const LABEL_H = 22;
const FONT    = "'JetBrains Mono', 'Fira Mono', monospace";

// ─── Componente ───────────────────────────────────────────────────────────────
export default function OverlayPage() {
  const [data, setData] = useState<OverlayData>({
    lines: [],
    status: "connecting",
    y_min: null,
    y_max: null,
    chart_rect: null,
  });

  const wsRef      = useRef<WebSocket | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(OCR_WS);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "overlay_update") setData(msg.data);
      } catch { /* ignore */ }
    };

    ws.onclose = () => {
      retryTimer.current = setTimeout(connect, 1_000);
    };

    ws.onerror = () => ws.close();
  }, []);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
      clearTimeout(retryTimer.current);
    };
  }, [connect]);

  const W = window.screen.width;
  const H = window.screen.height;

  return (
    <div
      style={{
        position:        "fixed",
        inset:           0,
        pointerEvents:   "none",
        background:      "transparent",
        overflow:        "hidden",
        userSelect:      "none",
        WebkitUserSelect:"none",
      }}
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        style={{ position: "absolute", inset: 0, display: "block" }}
      >
        {data.lines.map((line, i) => (
          <OverlayLineEl key={i} line={line} index={i} />
        ))}

        {/* Badge de status (canto inferior esquerdo) */}
        <StatusBadge status={data.status} y_min={data.y_min} y_max={data.y_max} />
      </svg>
    </div>
  );
}

// ─── Linha de overlay ─────────────────────────────────────────────────────────
function OverlayLineEl({ line, index }: { line: OverlayLine; index: number }) {
  const { value, y_screen, color, chart_left, chart_right } = line;

  // Formata o valor (R$ ou pontos)
  const label = value >= 1000 || value <= -1000
    ? value.toLocaleString("pt-BR", { minimumFractionDigits: 0, maximumFractionDigits: 0 })
    : value.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const lx = chart_right - LABEL_W - 4;
  const ly = y_screen - LABEL_H / 2;

  return (
    <g>
      {/* Linha tracejada */}
      <line
        x1={chart_left}
        y1={y_screen}
        x2={chart_right}
        y2={y_screen}
        stroke={color}
        strokeWidth={1.8}
        strokeDasharray="10 5"
        opacity={0.92}
      />

      {/* Sombra da linha para legibilidade */}
      <line
        x1={chart_left}
        y1={y_screen}
        x2={chart_right}
        y2={y_screen}
        stroke="rgba(0,0,0,0.5)"
        strokeWidth={3.5}
        strokeDasharray="10 5"
        opacity={0.4}
      />

      {/* Caixa do label */}
      <rect
        x={lx}
        y={ly}
        width={LABEL_W}
        height={LABEL_H}
        rx={3}
        fill="rgba(10,10,10,0.82)"
        stroke={color}
        strokeWidth={1}
      />

      {/* Texto do label */}
      <text
        x={chart_right - 8}
        y={y_screen + 5}
        fill={color}
        fontSize={12}
        fontFamily={FONT}
        fontWeight="700"
        textAnchor="end"
        style={{ letterSpacing: "0.04em" }}
      >
        {label}
      </text>

      {/* Marcador triangular na esquerda */}
      <polygon
        points={`${chart_left},${y_screen - 5} ${chart_left + 10},${y_screen} ${chart_left},${y_screen + 5}`}
        fill={color}
        opacity={0.85}
      />
    </g>
  );
}

// ─── Badge de status ──────────────────────────────────────────────────────────
function StatusBadge({
  status,
  y_min,
  y_max,
}: {
  status: string;
  y_min: number | null;
  y_max: number | null;
}) {
  const H = window.screen.height;
  const ok = status === "ok";
  const color = ok ? "#00FF88" : "#FF4444";
  const text = ok
    ? `OCR ✓  ${y_min?.toFixed(0)} – ${y_max?.toFixed(0)}`
    : `OCR ⚠ ${status}`;

  return (
    <g>
      <rect x={8} y={H - 28} width={240} height={20} rx={3} fill="rgba(0,0,0,0.65)" />
      <text x={14} y={H - 13} fill={color} fontSize={11} fontFamily={FONT} fontWeight="600">
        {text}
      </text>
    </g>
  );
}
