import { isTauri } from "./tauri";
import { listen } from "@tauri-apps/api/event";
import {
  PQ_OCR_OVERLAY_STATUS_EVENT,
  type PqOcrOverlayStatusPayload,
} from "../constants/pqTauriEvents";

type Unlisten = () => void;

function asPayload(value: unknown): PqOcrOverlayStatusPayload | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const action = raw.action;
  const status = raw.status;
  if (
    (action !== "recalibrate" && action !== "freeze" && action !== "startup") ||
    typeof status !== "string"
  ) {
    return null;
  }
  if (!["start", "ok", "error", "released"].includes(status)) {
    return null;
  }
  return {
    action,
    status: status as PqOcrOverlayStatusPayload["status"],
    details: (raw.details as Record<string, unknown> | undefined) ?? undefined,
    ts_ms: typeof raw.ts_ms === "number" ? raw.ts_ms : undefined,
  };
}

/**
 * Bridge de consumo seguro para `pq:ocr-overlay-status`.
 * - Em Tauri usa `@tauri-apps/api/event`.
 * - Em browser usa `window.addEventListener`.
 */
export async function listenOcrOverlayStatus(
  onEvent: (payload: PqOcrOverlayStatusPayload) => void,
): Promise<Unlisten> {
  if (isTauri()) {
    return listen(PQ_OCR_OVERLAY_STATUS_EVENT, (event) => {
      const payload = asPayload(event.payload);
      if (payload) onEvent(payload);
    });
  }
  const handler = (event: Event) => {
    const custom = event as CustomEvent<unknown>;
    const payload = asPayload(custom.detail);
    if (payload) onEvent(payload);
  };
  window.addEventListener(
    PQ_OCR_OVERLAY_STATUS_EVENT,
    handler as EventListener,
  );
  return () => {
    window.removeEventListener(
      PQ_OCR_OVERLAY_STATUS_EVENT,
      handler as EventListener,
    );
  };
}
