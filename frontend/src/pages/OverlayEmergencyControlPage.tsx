import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

export default function OverlayEmergencyControlPage() {
  const [armed, setArmed] = useState(false);
  const [countdown, setCountdown] = useState(0);

  useEffect(() => {
    if (!armed) return;
    setCountdown(5);
    const id = window.setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          setArmed(false);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [armed]);

  const closeOverlay = async () => {
    if (!armed) {
      setArmed(true);
      return;
    }
    try {
      await invoke("close_profit_overlay", { reason: "overlay_emergency_button" });
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
        backgroundColor: "transparent",
        backgroundImage: "none",
      }}
    >
      <button
        onClick={closeOverlay}
        style={{
          pointerEvents: "auto",
          background: armed ? "rgba(180, 0, 0, 0.95)" : "rgba(120, 0, 0, 0.9)",
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
        {armed ? `CONFIRMAR FECHAMENTO (${countdown})` : "FECHAR OVERLAY"}
      </button>
    </div>
  );
}
