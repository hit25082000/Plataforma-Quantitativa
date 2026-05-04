import { emitTo } from "@tauri-apps/api/event";
import { PQ_OVERLAY_OCR_DEBUG_HUD_EVENT } from "../constants/pqTauriEvents";
import { isTauri } from "../utils/tauri";

export default function OverlayEmergencyControlPage() {
  const expandOcrDebugHud = async () => {
    if (!isTauri()) return;
    try {
      await emitTo("profit-overlay", PQ_OVERLAY_OCR_DEBUG_HUD_EVENT, { expanded: true });
    } catch (err) {
      console.error("[overlay] expand OCR debug HUD emit failed:", err);
    }
  };

  return (
    <div
      style={{
        width: "100vw",
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "transparent",
        backgroundColor: "transparent",
        backgroundImage: "none",
      }}
    >
      <button
        type="button"
        onClick={() => void expandOcrDebugHud()}
        style={{
          pointerEvents: "auto",
          background: "rgba(0, 100, 45, 0.92)",
          border: "1px solid rgba(255,255,255,0.5)",
          color: "#fff",
          borderRadius: 8,
          padding: "10px 14px",
          fontSize: 12,
          fontWeight: 700,
          cursor: "pointer",
          boxShadow: "0 4px 12px rgba(0,0,0,0.45)",
        }}
      >
        EXPANDIR OCR DEBUG
      </button>
    </div>
  );
}
