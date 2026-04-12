import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { OCR_WS_URL, ocrWsUrlFromPort } from "../config/ocrPort";
import {
  type OcrAxisDeltas,
  overlayStatusColor,
  overlayStatusText,
} from "../utils/ocrStatus";

interface OverlayLine {
  value: number;
  y_screen: number;
  color: string;
  chart_left: number;
  chart_right: number;
  label?: string;
}

interface OverlayData {
  lines: OverlayLine[];
  status: string;
  y_min: number | null;
  y_max: number | null;
  axis_deltas?: OcrAxisDeltas | null;
  axis_diagnostics?: {
    raw_labels?: number;
    kept_labels?: number;
    rejected?: number;
    rejected_monotonic?: number;
    rejected_slope_outlier?: number;
  } | null;
}

const LABEL_W = 150;
const LABEL_H = 36;
const FONT = "'JetBrains Mono', 'Fira Mono', monospace";
/** Recuo à direita para não cobrir a faixa de botões/ferramentas do Profit. */
const DEFAULT_OVERLAY_RIGHT_MARGIN_PX = 208;
const LABEL_MIN_GAP = LABEL_H + 4;
const LABEL_MARGIN_PX = 2;

type AppConfigRead = {
  overlay_right_margin_px?: number | null;
};

interface PositionedOverlayLine extends OverlayLine {
  labelY: number;
  rank: number;
  dense: boolean;
}

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

function layoutOverlayLines(lines: OverlayLine[], screenH: number): PositionedOverlayLine[] {
  if (lines.length === 0) return [];

  const sortedByY = lines
    .map((line, index) => ({ line, index }))
    .sort((a, b) => a.line.y_screen - b.line.y_screen);

  const gaps: number[] = [];
  for (let i = 1; i < sortedByY.length; i++) {
    gaps.push(Math.abs(sortedByY[i].line.y_screen - sortedByY[i - 1].line.y_screen));
  }
  const avgGap = gaps.length > 0 ? gaps.reduce((acc, g) => acc + g, 0) / gaps.length : LABEL_MIN_GAP;
  const dense = sortedByY.length >= 4 || avgGap < LABEL_MIN_GAP + 8;

  const minCenter = LABEL_H / 2 + LABEL_MARGIN_PX;
  const maxCenter = screenH - LABEL_H / 2 - LABEL_MARGIN_PX;
  const centers = sortedByY.map((x) => clamp(x.line.y_screen, minCenter, maxCenter));

  // Passo para baixo: garante distanciamento mínimo entre labels.
  for (let i = 1; i < centers.length; i++) {
    centers[i] = Math.max(centers[i], centers[i - 1] + LABEL_MIN_GAP);
  }

  const overflowBottom = centers[centers.length - 1] - maxCenter;
  if (overflowBottom > 0) {
    for (let i = 0; i < centers.length; i++) centers[i] -= overflowBottom;
  }

  // Passo para cima: corrige colisões restantes após ajustar o rodapé.
  for (let i = centers.length - 2; i >= 0; i--) {
    centers[i] = Math.min(centers[i], centers[i + 1] - LABEL_MIN_GAP);
  }

  const overflowTop = minCenter - centers[0];
  if (overflowTop > 0) {
    for (let i = 0; i < centers.length; i++) centers[i] += overflowTop;
  }

  const arranged = sortedByY.map((x, i) => ({
    line: x.line,
    index: x.index,
    labelY: clamp(centers[i], minCenter, maxCenter),
    rank: i + 1,
    dense,
  }));

  const byOriginal = new Array<PositionedOverlayLine>(arranged.length);
  for (const item of arranged) {
    byOriginal[item.index] = {
      ...item.line,
      labelY: item.labelY,
      rank: item.rank,
      dense: item.dense,
    };
  }
  return byOriginal;
}

export default function OverlayPage() {
  const [data, setData] = useState<OverlayData>({
    lines: [],
    status: "connecting",
    y_min: null,
    y_max: null,
    axis_deltas: null,
    axis_diagnostics: null,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout>>();
  const wsRetryRef = useRef(0);
  const wsStartRef = useRef<number | null>(null);
  const wsOpenLoggedRef = useRef(false);
  const [overlayRightMarginPx, setOverlayRightMarginPx] = useState<number>(
    DEFAULT_OVERLAY_RIGHT_MARGIN_PX,
  );
  const [viewport, setViewport] = useState({
    width: window.innerWidth,
    height: window.innerHeight,
  });

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    setData((prev) => ({ ...prev, status: "connecting" }));
    if (wsStartRef.current == null) wsStartRef.current = performance.now();
    const openWs = async () => {
      let wsUrl = OCR_WS_URL;
      try {
        const runtimePort = await invoke<number>("get_ocr_runtime_port");
        if (Number.isFinite(runtimePort) && runtimePort > 0) {
          wsUrl = ocrWsUrlFromPort(runtimePort);
        }
      } catch {
        // fallback para porta estática
      }
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.onopen = () => {
        wsRetryRef.current = 0;
        if (!wsOpenLoggedRef.current && wsStartRef.current != null) {
          const ms = Math.round(performance.now() - wsStartRef.current);
          console.info(`[overlay-latency] overlay_page_ws_open elapsed_ms=${ms}`);
          wsOpenLoggedRef.current = true;
        }
        setData((prev) => ({ ...prev, status: "connecting" }));
      };

      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "overlay_update") {
            setData(msg.data);
          }
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        const delays = [
          250, 500, 800, 1200, 1600, 2000, 2500, 3000, 3500, 4000, 4500,
        ];
        const i = Math.min(wsRetryRef.current++, delays.length - 1);
        const ms = delays[i] ?? 4500;
        setData((prev) => ({
          ...prev,
          status: wsRetryRef.current > 32 ? "ocr_unreachable_retrying" : "warming_up",
        }));
        retryTimer.current = setTimeout(connect, ms);
      };

      ws.onerror = () => ws.close();
    };
    void openWs();
  }, []);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
      clearTimeout(retryTimer.current);
    };
  }, [connect]);

  useEffect(() => {
    const onResize = () => {
      setViewport({ width: window.innerWidth, height: window.innerHeight });
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    let mounted = true;
    invoke<AppConfigRead>("read_config")
      .then((cfg) => {
        if (!mounted) return;
        const v = cfg?.overlay_right_margin_px;
        if (typeof v === "number" && Number.isFinite(v) && v >= 0) {
          setOverlayRightMarginPx(v);
        }
      })
      .catch(() => {});
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    const html = document.documentElement;
    const body = document.body;
    const root = document.getElementById("root");
    const prevHtml = html.style.background;
    const prevBody = body.style.background;
    const prevRoot = root?.style.background ?? "";

    html.style.background = "transparent";
    body.style.background = "transparent";
    if (root) root.style.background = "transparent";

    return () => {
      html.style.background = prevHtml;
      body.style.background = prevBody;
      if (root) root.style.background = prevRoot;
    };
  }, []);

  const renderScale = useMemo(() => {
    const dpr = window.devicePixelRatio || 1;
    if (!Number.isFinite(dpr) || dpr <= 0) return 1;
    return 1 / dpr;
  }, []);
  const scaledLines = useMemo(
    () =>
      data.lines.map((line) => ({
        ...line,
        y_screen: line.y_screen * renderScale,
        chart_left: line.chart_left * renderScale,
        chart_right: line.chart_right * renderScale,
      })),
    [data.lines, renderScale],
  );
  const W = viewport.width;
  const H = viewport.height;
  const positionedLines = useMemo(() => layoutOverlayLines(scaledLines, H), [scaledLines, H]);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        pointerEvents: "none",
        background: "transparent",
        overflow: "hidden",
        userSelect: "none",
        WebkitUserSelect: "none",
      }}
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        style={{ position: "absolute", inset: 0, display: "block" }}
      >
        {positionedLines.map((line, i) => (
          <OverlayLineEl key={i} line={line} rightMarginPx={overlayRightMarginPx} />
        ))}

        <StatusBadge
          status={data.status}
          y_min={data.y_min}
          y_max={data.y_max}
          axis_deltas={data.axis_deltas}
          axis_diagnostics={data.axis_diagnostics}
          viewportHeight={H}
        />
      </svg>
    </div>
  );
}

function OverlayLineEl({
  line,
  rightMarginPx,
}: {
  line: PositionedOverlayLine;
  rightMarginPx: number;
}) {
  const { value, y_screen, color, chart_left, chart_right, label: paramLabel, labelY, rank, dense } =
    line;
  const compact = dense;
  const labelH = compact ? 32 : LABEL_H;
  const titleFontSize = compact ? 9 : 10;
  const priceFontSize = compact ? 11 : 12;

  const priceStr =
    value >= 1000 || value <= -1000
      ? value.toLocaleString("pt-BR", { minimumFractionDigits: 0, maximumFractionDigits: 0 })
      : value.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const lineRight = Math.max(
    chart_left + LABEL_W + 24,
    chart_right - rightMarginPx,
  );
  const lx = lineRight - LABEL_W - 4;
  const ly = labelY - labelH / 2;
  const baseTitle = paramLabel?.trim() ? paramLabel.trim() : "";
  const title = baseTitle ? `${rank}) ${baseTitle}` : "";

  return (
    <g>
      <line
        x1={lineRight - 14}
        y1={y_screen}
        x2={lx - 3}
        y2={labelY}
        stroke={color}
        strokeWidth={1}
        opacity={0.78}
      />
      <line
        x1={chart_left}
        y1={y_screen}
        x2={lineRight}
        y2={y_screen}
        stroke="rgba(0,0,0,0.5)"
        strokeWidth={3.5}
        strokeDasharray="10 5"
        opacity={0.4}
      />
      <line
        x1={chart_left}
        y1={y_screen}
        x2={lineRight}
        y2={y_screen}
        stroke={color}
        strokeWidth={1.8}
        strokeDasharray="10 5"
        opacity={0.92}
      />
      <rect
        x={lx}
        y={ly}
        width={LABEL_W}
        height={labelH}
        rx={3}
        fill="rgba(10,10,10,0.82)"
        stroke={color}
        strokeWidth={1}
      />
      {title ? (
        <text
          x={lineRight - 8}
          y={labelY - (compact ? 4 : 3)}
          fill="rgba(200,210,225,0.95)"
          fontSize={titleFontSize}
          fontFamily={FONT}
          fontWeight="600"
          textAnchor="end"
          style={{ letterSpacing: "0.02em" }}
        >
          {title}
        </text>
      ) : null}
      <text
        x={lineRight - 8}
        y={labelY + (title ? (compact ? 10 : 12) : 5)}
        fill={color}
        fontSize={priceFontSize}
        fontFamily={FONT}
        fontWeight="700"
        textAnchor="end"
        style={{ letterSpacing: "0.04em" }}
      >
        {priceStr}
      </text>
      <polygon
        points={`${chart_left},${y_screen - 5} ${chart_left + 10},${y_screen} ${chart_left},${y_screen + 5}`}
        fill={color}
        opacity={0.85}
      />
    </g>
  );
}

function StatusBadge({
  status,
  y_min,
  y_max,
  axis_deltas,
  axis_diagnostics,
  viewportHeight,
}: {
  status: string;
  y_min: number | null;
  y_max: number | null;
  axis_deltas?: OcrAxisDeltas | null;
  axis_diagnostics?: {
    raw_labels?: number;
    kept_labels?: number;
    rejected?: number;
  } | null;
  viewportHeight: number;
}) {
  const color = overlayStatusColor(status);
  const text = overlayStatusText(status, y_min, y_max, axis_deltas);
  const diagText =
    axis_diagnostics && typeof axis_diagnostics.kept_labels === "number"
      ? `labels ${axis_diagnostics.kept_labels}/${axis_diagnostics.raw_labels ?? "?"} | rej ${axis_diagnostics.rejected ?? 0}`
      : "";

  return (
    <g>
      <rect x={8} y={viewportHeight - 44} width={940} height={36} rx={3} fill="rgba(0,0,0,0.65)" />
      <text x={14} y={viewportHeight - 13} fill={color} fontSize={11} fontFamily={FONT} fontWeight="600">
        {text}
      </text>
      {diagText ? (
        <text
          x={14}
          y={viewportHeight - 29}
          fill="rgba(210,220,230,0.86)"
          fontSize={10}
          fontFamily={FONT}
          fontWeight="500"
        >
          {diagText}
        </text>
      ) : null}
    </g>
  );
}
