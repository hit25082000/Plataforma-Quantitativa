import { useEffect, useRef, useState } from "react";
import {
  OVERLAY_METRIC_LABELS,
  OVERLAY_METRIC_ORDER,
  overlayLineColorForLabel,
  useProfitOverlay,
} from "../../hooks/useProfitOverlay";
import { overlayStatusColor, overlayStatusText } from "../../utils/ocrStatus";
/** Valores do overlay são preços (eixo Y do gráfico), não saldo em contratos. */
const POSITION_STEP = 1;

export default function OverlayControl() {
  const {
    active,
    activating,
    status,
    targets,
    lines,
    y_min,
    y_max,
    analysisRoi,
    analysisSample,
    selectedMetricIds,
    toggleMetric,
    openOverlay,
    closeOverlay,
    openOcrRoiPicker,
    clearOcrAnalysisRoi,
    addPosition,
    removePosition,
    updatePosition,
  } = useProfitOverlay();

  const [newValue, setNewValue] = useState("");
  const [manualValueHint, setManualValueHint] = useState<string | null>(null);
  const [roiFeedback, setRoiFeedback] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const lastRoiKeyRef = useRef<string | null>(null);

  const canActivate = true;
  const handleToggle = () => {
    if (activating) return;
    active ? void closeOverlay() : void openOverlay();
  };

  const handleAdd = () => {
    const val = parseFloat(newValue.replace(",", "."));
    if (isNaN(val)) {
      setManualValueHint("Informe um preço numérico válido.");
      return;
    }
    if (!Number.isFinite(val) || val <= 0) {
      setManualValueHint("O preço manual deve ser maior que zero.");
      return;
    }
    addPosition(val);
    setNewValue("");
    setManualValueHint(null);
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleAdd();
  };
  const parsedManualValue = parseFloat(newValue.replace(",", "."));
  const canAddManualValue = Number.isFinite(parsedManualValue) && parsedManualValue > 0;

  const statusColor = activating ? "#FFB800" : overlayStatusColor(status);
  const statusText = activating
    ? "Overlay: a ligar o serviço (aguarde; timeout em ~45s)…"
    : overlayStatusText(status, y_min, y_max);

  useEffect(() => {
    if (!analysisRoi) {
      lastRoiKeyRef.current = null;
      setRoiFeedback(null);
      return;
    }
    const roiKey = `${analysisRoi.left}:${analysisRoi.top}:${analysisRoi.width}:${analysisRoi.height}`;
    if (lastRoiKeyRef.current === roiKey) return;
    lastRoiKeyRef.current = roiKey;
    setRoiFeedback("Região confirmada com sucesso.");
    const timer = window.setTimeout(() => setRoiFeedback(null), 4500);
    return () => window.clearTimeout(timer);
  }, [analysisRoi]);

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.title}>Overlay Profit</span>
        <button
          type="button"
          onClick={handleToggle}
          disabled={activating || (!active && !canActivate)}
          style={{
            ...styles.toggleBtn,
            opacity: activating || (!active && !canActivate) ? 0.45 : 1,
            cursor: activating || (!active && !canActivate) ? "not-allowed" : "pointer",
            background: active
              ? "rgba(255,68,68,0.15)"
              : activating
                ? "rgba(255,184,0,0.15)"
                : "rgba(0,255,136,0.15)",
            border: `1px solid ${active ? "#FF4444" : activating ? "#FFB800" : "#00FF88"}`,
            color: active ? "#FF4444" : activating ? "#FFB800" : "#00FF88",
          }}
        >
          {activating ? "A ligar…" : active ? "Desativar" : "Ativar"}
        </button>
      </div>

      <div style={styles.section}>
        <div style={styles.sectionLabel}>Monitorar</div>
        {OVERLAY_METRIC_ORDER.length > 0 ? (
          <div style={styles.checkboxGrid}>
            {OVERLAY_METRIC_ORDER.map((id) => {
              const checked = selectedMetricIds.includes(id);
              return (
                <label key={id} style={styles.checkboxRow}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleMetric(id)}
                    style={styles.checkbox}
                  />
                  <span>{OVERLAY_METRIC_LABELS[id]}</span>
                </label>
              );
            })}
          </div>
        ) : (
          <div style={styles.warnHint}>
            Modo estável: somente VP Sato e linhas manuais. Médias automáticas estão desligadas.
          </div>
        )}
      </div>

      <div style={styles.statusRow}>
        <span style={{ ...styles.statusDot, background: statusColor }} />
        <span style={{ ...styles.statusText, color: statusColor }}>{statusText}</span>
        {y_min !== null && y_max !== null && (
          <span style={styles.range}>
            {y_min.toFixed(0)} - {y_max.toFixed(0)}
          </span>
        )}
      </div>

      <div style={styles.section}>
        <div style={styles.sectionLabel}>OCR análise (opcional)</div>
        <div style={styles.analysisHint}>
          Área só para ler texto/números no Profit. <strong>Não altera</strong> onde as linhas do overlay são
          desenhadas. A região fica <strong>guardada</strong> (config.json) e é reaplicada ao ativar o overlay —
          não precisa redesenhar sempre.
        </div>
        <div style={styles.roiBtnRow}>
          <button
            type="button"
            disabled={!active}
            onClick={() => void openOcrRoiPicker()}
            style={{
              ...styles.roiBtn,
              opacity: active ? 1 : 0.45,
              cursor: active ? "pointer" : "not-allowed",
            }}
            title={active ? undefined : "Ative o overlay para o serviço OCR estar em execução"}
          >
            Desenhar região…
          </button>
          <button
            type="button"
            disabled={!analysisRoi}
            onClick={() => void clearOcrAnalysisRoi()}
            style={{
              ...styles.roiBtnSecondary,
              opacity: analysisRoi ? 1 : 0.45,
              cursor: analysisRoi ? "pointer" : "not-allowed",
            }}
          >
            Limpar região
          </button>
        </div>
        {analysisRoi ? (
          <div style={styles.roiMeta}>
            ROI físico: {analysisRoi.left},{analysisRoi.top} +{analysisRoi.width}×{analysisRoi.height}
          </div>
        ) : null}
        {analysisRoi ? <div style={styles.roiActiveBadge}>Região OCR ativa</div> : null}
        {roiFeedback ? <div style={styles.roiSuccessToast}>{roiFeedback}</div> : null}
        {analysisSample ? (
          <div style={styles.analysisOut}>
            {analysisSample.error ? (
              <span style={{ color: "#FF8888" }}>{analysisSample.error}</span>
            ) : (
              <>
                {analysisSample.numbers && analysisSample.numbers.length > 0 ? (
                  <div style={styles.analysisNumbers}>
                    Números: {analysisSample.numbers.slice(0, 12).join(" · ")}
                    {analysisSample.numbers.length > 12 ? "…" : ""}
                  </div>
                ) : null}
                {analysisSample.text ? (
                  <div style={styles.analysisText} title={analysisSample.text}>
                    {analysisSample.text.slice(0, 120)}
                    {analysisSample.text.length > 120 ? "…" : ""}
                  </div>
                ) : (
                  <div style={styles.analysisTextMuted}>Sem texto na última captura</div>
                )}
              </>
            )}
          </div>
        ) : null}
      </div>

      <div style={styles.section}>
        <div style={styles.sectionLabel}>Posicoes</div>
        {targets.length === 0 && <div style={styles.emptyHint}>Nenhuma posicao configurada</div>}
        {targets.map((t, i) => {
          const line = lines.find((l) => Math.abs(l.value - t.value) < 0.001);
          const color =
            line?.color ?? overlayLineColorForLabel(t.label ?? "", i);
          return (
            <div key={`${t.label}-${i}`} style={styles.posRow}>
              <span style={{ ...styles.colorDot, background: color }} />
              <input
                type="number"
                value={t.value}
                step={POSITION_STEP}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  if (!isNaN(v)) updatePosition(i, v);
                }}
                style={styles.posInput}
              />
              <span style={styles.defaultBadge}>{t.label}</span>
              <span style={{ ...styles.yBadge, color }}>{line ? `y:${line.y_screen}px` : "-"}</span>
              <button type="button" onClick={() => removePosition(i)} style={styles.removeBtn} title="Remover">
                x
              </button>
            </div>
          );
        })}
      </div>

      <div style={styles.addRow}>
        <input
          ref={inputRef}
          type="number"
          step={POSITION_STEP}
          placeholder="Ex: 100"
          value={newValue}
          onChange={(e) => {
            setNewValue(e.target.value);
            if (manualValueHint) setManualValueHint(null);
          }}
          onKeyDown={handleKeyDown}
          style={styles.addInput}
        />
        <button
          type="button"
          disabled={!canAddManualValue}
          onClick={handleAdd}
          style={{
            ...styles.addBtn,
            opacity: canAddManualValue ? 1 : 0.45,
            cursor: canAddManualValue ? "pointer" : "not-allowed",
          }}
          title={canAddManualValue ? undefined : "Digite um preço manual válido (> 0)"}
        >
          + Adicionar
        </button>
      </div>
      {manualValueHint ? <div style={styles.warnHint}>{manualValueHint}</div> : null}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    background: "rgba(12,14,18,0.97)",
    border: "1px solid rgba(255,255,255,0.08)",
    borderRadius: 8,
    padding: "10px 12px",
    minWidth: 280,
    fontFamily: "'Inter', 'Segoe UI', sans-serif",
    fontSize: 12,
    color: "#C8CDD6",
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  header: { display: "flex", justifyContent: "space-between", alignItems: "center" },
  title: { fontWeight: 700, fontSize: 13, color: "#E2E8F0", letterSpacing: "0.02em" },
  toggleBtn: {
    padding: "4px 10px",
    borderRadius: 5,
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 600,
    transition: "opacity 0.15s",
  },
  warnHint: { fontSize: 11, color: "#FFB800", lineHeight: 1.35 },
  checkboxGrid: { display: "flex", flexDirection: "column", gap: 4 },
  checkboxRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    cursor: "pointer",
    fontSize: 12,
    color: "#C8CDD6",
  },
  checkbox: { cursor: "pointer", flexShrink: 0 },
  statusRow: { display: "flex", alignItems: "center", gap: 6, fontSize: 11, opacity: 0.85 },
  statusDot: { width: 7, height: 7, borderRadius: "50%" },
  statusText: { fontFamily: "monospace" },
  range: { marginLeft: "auto", fontFamily: "monospace", color: "#8892A4" },
  section: { display: "flex", flexDirection: "column", gap: 6 },
  sectionLabel: {
    fontSize: 11,
    color: "#8892A4",
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.06em",
  },
  emptyHint: { color: "#4A5568", fontSize: 12, fontStyle: "italic" },
  posRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    background: "rgba(255,255,255,0.03)",
    borderRadius: 5,
    padding: "4px 8px",
  },
  colorDot: { width: 8, height: 8, borderRadius: "50%", flexShrink: 0 },
  posInput: {
    flex: 1,
    background: "transparent",
    border: "none",
    outline: "none",
    color: "#E2E8F0",
    fontSize: 13,
    fontFamily: "'JetBrains Mono', monospace",
    width: "100%",
  },
  yBadge: { fontFamily: "monospace", fontSize: 10, opacity: 0.7, flexShrink: 0 },
  defaultBadge: {
    fontFamily: "monospace",
    fontSize: 10,
    color: "#8892A4",
    border: "1px solid rgba(136,146,164,0.45)",
    borderRadius: 4,
    padding: "0 4px",
    lineHeight: "14px",
    flexShrink: 0,
    maxWidth: 120,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  removeBtn: {
    background: "transparent",
    border: "none",
    color: "#FF4444",
    cursor: "pointer",
    padding: "0 2px",
    fontSize: 12,
    opacity: 0.7,
    flexShrink: 0,
  },
  addRow: { display: "flex", gap: 6 },
  addInput: {
    flex: 1,
    background: "rgba(255,255,255,0.05)",
    border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: 5,
    padding: "5px 8px",
    color: "#E2E8F0",
    fontSize: 13,
    outline: "none",
    fontFamily: "'JetBrains Mono', monospace",
  },
  addBtn: {
    background: "rgba(0,255,136,0.12)",
    border: "1px solid #00FF88",
    color: "#00FF88",
    borderRadius: 5,
    padding: "5px 10px",
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 600,
    whiteSpace: "nowrap",
  },
  analysisHint: {
    fontSize: 10,
    color: "#8892A4",
    lineHeight: 1.4,
  },
  roiBtnRow: { display: "flex", gap: 6, flexWrap: "wrap" },
  roiBtn: {
    background: "rgba(0,204,255,0.12)",
    border: "1px solid #00CCFF",
    color: "#00CCFF",
    borderRadius: 5,
    padding: "5px 10px",
    cursor: "pointer",
    fontSize: 11,
    fontWeight: 600,
  },
  roiBtnSecondary: {
    background: "transparent",
    border: "1px solid rgba(136,146,164,0.5)",
    color: "#8892A4",
    borderRadius: 5,
    padding: "5px 10px",
    cursor: "pointer",
    fontSize: 11,
    fontWeight: 600,
  },
  roiMeta: { fontSize: 9, fontFamily: "monospace", color: "#5C6570" },
  roiActiveBadge: {
    alignSelf: "flex-start",
    fontSize: 10,
    color: "#00FF88",
    border: "1px solid rgba(0,255,136,0.55)",
    background: "rgba(0,255,136,0.1)",
    borderRadius: 999,
    padding: "2px 8px",
    fontWeight: 600,
  },
  roiSuccessToast: {
    fontSize: 10,
    color: "#86EFAC",
    background: "rgba(34,197,94,0.12)",
    border: "1px solid rgba(34,197,94,0.5)",
    borderRadius: 5,
    padding: "5px 8px",
    lineHeight: 1.3,
  },
  analysisOut: {
    marginTop: 4,
    padding: 6,
    borderRadius: 5,
    background: "rgba(255,255,255,0.04)",
    border: "1px solid rgba(255,255,255,0.06)",
  },
  analysisNumbers: { fontSize: 10, fontFamily: "monospace", color: "#A5F3FC", marginBottom: 4 },
  analysisText: { fontSize: 10, color: "#C8CDD6", lineHeight: 1.35, wordBreak: "break-word" },
  analysisTextMuted: { fontSize: 10, color: "#5C6570", fontStyle: "italic" },
};
