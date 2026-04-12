/**
 * WebSocket do serviço OCR (overlay). Deve coincidir com PQ_OCR_PORT no backend.
 * @see ../../../../docs/PORTS.md
 */
const fallbackPort = import.meta.env.VITE_PQ_OCR_PORT?.trim() || "5558";

export function ocrWsUrlFromPort(port: number | string): string {
  return `ws://127.0.0.1:${String(port).trim()}/ws`;
}

export const OCR_WS_URL = ocrWsUrlFromPort(fallbackPort);
