import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

type DragState = {
  startX: number;
  startY: number;
  curX: number;
  curY: number;
};

/**
 * Janela full-screen (label ocr-roi-picker): arrastar retângulo.
 * Coordenadas são enviadas ao Tauri → pixels físicos → POST /analysis_roi.
 * Não altera o cálculo das linhas do overlay (eixo Y continua na faixa padrão do gráfico).
 */
export default function OcrRoiPickerPage() {
  const [drag, setDrag] = useState<DragState | null>(null);
  const [committed, setCommitted] = useState<{
    x: number;
    y: number;
    w: number;
    h: number;
  } | null>(null);
  const drawing = useRef(false);

  const onMouseDown = (e: React.MouseEvent) => {
    drawing.current = true;
    setCommitted(null);
    setDrag({
      startX: e.clientX,
      startY: e.clientY,
      curX: e.clientX,
      curY: e.clientY,
    });
  };

  const onMouseMove = useCallback((e: MouseEvent) => {
    if (!drawing.current) return;
    setDrag((d) =>
      d
        ? {
            ...d,
            curX: e.clientX,
            curY: e.clientY,
          }
        : null,
    );
  }, []);

  const endDrag = useCallback(() => {
    if (!drawing.current) return;
    drawing.current = false;
    setDrag((d) => {
      if (!d) return null;
      const x = Math.min(d.startX, d.curX);
      const y = Math.min(d.startY, d.curY);
      const w = Math.abs(d.curX - d.startX);
      const h = Math.abs(d.curY - d.startY);
      if (w >= 12 && h >= 12) {
        setCommitted({ x, y, w, h });
      } else {
        setCommitted(null);
      }
      return null;
    });
  }, []);

  useEffect(() => {
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", endDrag);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", endDrag);
    };
  }, [onMouseMove, endDrag]);

  const rectStyle = (r: { x: number; y: number; w: number; h: number }) => ({
    position: "absolute" as const,
    left: r.x,
    top: r.y,
    width: r.w,
    height: r.h,
    border: "2px solid #00FF88",
    background: "rgba(0,255,136,0.12)",
    boxSizing: "border-box" as const,
    pointerEvents: "none" as const,
  });

  const preview = drag
    ? {
        x: Math.min(drag.startX, drag.curX),
        y: Math.min(drag.startY, drag.curY),
        w: Math.abs(drag.curX - drag.startX),
        h: Math.abs(drag.curY - drag.startY),
      }
    : null;

  const confirm = async () => {
    if (!committed) return;
    try {
      await invoke("submit_ocr_analysis_roi", {
        x: committed.x,
        y: committed.y,
        width: committed.w,
        height: committed.h,
      });
    } catch (err) {
      console.error("[ocr-roi] submit failed:", err);
      alert(err instanceof Error ? err.message : String(err));
    }
  };

  const cancel = useCallback(async () => {
    try {
      await invoke("close_ocr_roi_picker");
    } catch (err) {
      console.error("[ocr-roi] close failed:", err);
    }
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") void cancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cancel]);

  // index.css define body com #0a0a0a — com janela Tauri transparenta isso tapa o ecrã (parece tudo preto).
  useEffect(() => {
    const html = document.documentElement;
    const body = document.body;
    const root = document.getElementById("root");
    const prevHtml = html.style.background;
    const prevBody = body.style.background;
    const prevBodyColor = body.style.backgroundColor;
    const prevRootBg = root?.style.background ?? "";
    const prevRootMinH = root?.style.minHeight ?? "";
    html.style.background = "transparent";
    body.style.background = "transparent";
    body.style.backgroundColor = "transparent";
    if (root) {
      root.style.background = "transparent";
      root.style.minHeight = "100vh";
    }
    return () => {
      html.style.background = prevHtml;
      body.style.background = prevBody;
      body.style.backgroundColor = prevBodyColor;
      if (root) {
        root.style.background = prevRootBg;
        root.style.minHeight = prevRootMinH;
      }
    };
  }, []);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        cursor: "crosshair",
        /* Véu sobre o ecrã real (só visível com html/body/root transparentes) */
        background: "rgba(0,0,0,0.5)",
        userSelect: "none",
      }}
      onMouseDown={onMouseDown}
    >
      <div
        style={{
          position: "absolute",
          top: 12,
          left: 12,
          right: 12,
          maxWidth: 560,
          color: "#E2E8F0",
          fontSize: 13,
          fontFamily: "system-ui, sans-serif",
          lineHeight: 1.45,
          pointerEvents: "none",
          padding: "10px 12px",
          borderRadius: 8,
          background: "rgba(8,10,14,0.88)",
          border: "1px solid rgba(255,255,255,0.12)",
          boxShadow: "0 8px 32px rgba(0,0,0,0.45)",
        }}
      >
        <strong>Região só para análise OCR</strong> — não muda onde as linhas são desenhadas. Arraste um
        retângulo sobre o texto/números do Profit (ex.: painel de preços). Depois confirme.
      </div>

      {preview && preview.w > 2 && preview.h > 2 ? <div style={rectStyle(preview)} /> : null}
      {committed ? <div style={rectStyle(committed)} /> : null}

      <div
        onMouseDown={(e) => e.stopPropagation()}
        style={{
          position: "absolute",
          bottom: 20,
          left: "50%",
          transform: "translateX(-50%)",
          display: "flex",
          gap: 10,
          pointerEvents: "auto",
        }}
      >
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            void cancel();
          }}
          style={{
            padding: "10px 16px",
            borderRadius: 8,
            border: "1px solid rgba(255,255,255,0.35)",
            background: "rgba(30,30,30,0.92)",
            color: "#fff",
            cursor: "pointer",
            fontWeight: 600,
          }}
        >
          Cancelar
        </button>
        <button
          type="button"
          disabled={!committed}
          onClick={(e) => {
            e.stopPropagation();
            void confirm();
          }}
          style={{
            padding: "10px 16px",
            borderRadius: 8,
            border: "1px solid #00FF88",
            background: committed ? "rgba(0,255,136,0.2)" : "rgba(60,60,60,0.5)",
            color: committed ? "#00FF88" : "#666",
            cursor: committed ? "pointer" : "not-allowed",
            fontWeight: 700,
          }}
        >
          Confirmar região
        </button>
      </div>
    </div>
  );
}
