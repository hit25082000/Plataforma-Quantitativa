import { invoke } from "@tauri-apps/api/core";

export default function OverlayEmergencyControlPage() {
  const closeOverlay = async () => {
    try {
      await invoke("close_profit_overlay");
    } catch (err) {
      console.error("[overlay] close_profit_overlay failed:", err);
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
      }}
    >
      <button
        onClick={closeOverlay}
        style={{
          pointerEvents: "auto",
          background: "rgba(120, 0, 0, 0.9)",
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
        FECHAR OVERLAY
      </button>
    </div>
  );
}
