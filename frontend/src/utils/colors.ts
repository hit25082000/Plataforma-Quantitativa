import type { AlertMessage } from "../types/messages";

export function getAlertBorderColor(alert: AlertMessage): string {
  if (alert.conviction === "high") {
    return alert.direction === "buy" ? "#00ff88" : "#ff2244";
  }
  if (alert.conviction === "medium") return "#ffbb00";
  return "#444444";
}

export function getAlertPulseClass(alert: AlertMessage): boolean {
  return alert.conviction === "high";
}

export function getHeatmapColor(qty: number): string {
  if (qty < 100) return "transparent";
  if (qty < 300) return "#1a3a2a";
  if (qty < 500) return "#ff880044";
  return "#ff440088";
}
