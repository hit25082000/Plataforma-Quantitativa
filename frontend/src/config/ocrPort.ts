/**
 * WebSocket do serviço OCR (overlay). Deve coincidir com PQ_OCR_PORT no backend.
 * @see ../../../../docs/PORTS.md
 */
const port = import.meta.env.VITE_PQ_OCR_PORT?.trim() || "5558";

export const OCR_WS_URL = `ws://127.0.0.1:${port}/ws`;
