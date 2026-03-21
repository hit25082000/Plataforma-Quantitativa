import { useRef, useState } from "react";
import { useProfitOverlay } from "../../hooks/useProfitOverlay";

const COLORS = ["#00FF88", "#FF4444", "#FFB800", "#00CCFF", "#FF88FF", "#FFFFFF"];
/** Valores do overlay são preços (eixo Y do gráfico), não saldo em contratos. */
const POSITION_STEP = 1;

export default function OverlayControl() {
  const {
    active,
    status,
    positions,
    lines,
    y_min,
    y_max,
    openOverlay,
    closeOverlay,
    addPosition,
    removePosition,
    updatePosition,
  } = useProfitOverlay();

  const [newValue, setNewValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const handleToggle = () => (active ? closeOverlay() : openOverlay());

  const handleAdd = () => {
    const val = parseFloat(newValue.replace(",", "."));
    if (!isNaN(val)) {
      addPosition(val);
      setNewValue("");
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleAdd();
  };

  const statusColor =
    status === "ok"
      ? "#00FF88"
      : status === "connecting" || status === "idle"
        ? "#FFB800"
        : "#FF4444";

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.title}>Overlay Profit</span>
        <button
          onClick={handleToggle}
          style={{
            ...styles.toggleBtn,
            background: active ? "rgba(255,68,68,0.15)" : "rgba(0,255,136,0.15)",
            border: `1px solid ${active ? "#FF4444" : "#00FF88"}`,
            color: active ? "#FF4444" : "#00FF88",
          }}
        >
          {active ? "Desativar" : "Ativar"}
        </button>
      </div>

      <div style={styles.statusRow}>
        <span style={{ ...styles.statusDot, background: statusColor }} />
        <span style={{ ...styles.statusText, color: statusColor }}>{status}</span>
        {y_min !== null && y_max !== null && (
          <span style={styles.range}>
            {y_min.toFixed(0)} - {y_max.toFixed(0)}
          </span>
        )}
      </div>

      <div style={styles.section}>
        <div style={styles.sectionLabel}>Posicoes</div>
        {positions.length === 0 && <div style={styles.emptyHint}>Nenhuma posicao configurada</div>}
        {positions.map((pos, i) => {
          const line = lines.find((l) => Math.abs(l.value - pos) < 0.001);
          const color = COLORS[i % COLORS.length];
          return (
            <div key={i} style={styles.posRow}>
              <span style={{ ...styles.colorDot, background: color }} />
              <input
                type="number"
                value={pos}
                step={POSITION_STEP}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  if (!isNaN(v)) updatePosition(i, v);
                }}
                style={styles.posInput}
              />
              {i === 0 && <span style={styles.defaultBadge}>MEDIO</span>}
              {i === 1 && <span style={styles.defaultBadge}>UBS</span>}
              <span style={{ ...styles.yBadge, color }}>{line ? `y:${line.y_screen}px` : "-"}</span>
              <button onClick={() => removePosition(i)} style={styles.removeBtn} title="Remover">
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
          onChange={(e) => setNewValue(e.target.value)}
          onKeyDown={handleKeyDown}
          style={styles.addInput}
        />
        <button onClick={handleAdd} style={styles.addBtn}>
          + Adicionar
        </button>
      </div>
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
};
