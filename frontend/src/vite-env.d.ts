/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PQ_OCR_PORT?: string;
}

interface PqOverlayContextSnapshot {
  axis_status?: string | null;
  last_good_axis?: number | null;
  last_valid_vp?: { exists: boolean; ticker?: string; levels?: number };
  last_render_frame?: { exists: boolean; guardStatus?: string };
  render_items_count?: number;
  ws_connected?: boolean;
  overlay_status?: string;
}

interface PqOverlayRenderErrorPayload {
  ts: number;
  message: string;
  stack: string;
  componentStack: string;
  context: unknown;
}

interface Window {
  __PQ_OVERLAY_CONTEXT__?: PqOverlayContextSnapshot;
  __PQ_LAST_OVERLAY_RENDER_ERROR__?: PqOverlayRenderErrorPayload;
  __PQ_LAST_OVERLAY_WINDOW_ERROR__?: Record<string, unknown>;
  __PQ_LAST_OVERLAY_PROMISE_ERROR__?: Record<string, unknown>;
}
