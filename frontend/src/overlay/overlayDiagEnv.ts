function readStorage(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(key) ?? window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function envVite(key: string): string | undefined {
  try {
    const env = import.meta.env as Record<string, string | undefined>;
    return env[key];
  } catch {
    return undefined;
  }
}

function truthy(raw: string | null | undefined): boolean {
  if (raw == null) return false;
  const v = raw.trim().toLowerCase();
  return v === "1" || v === "true" || v === "yes";
}

export type OverlayAxisVpMode = "real" | "fake" | "ocr_labels_fake";

function axisModeFrom(raw: string | null | undefined, viteKey: string): OverlayAxisVpMode {
  const v = (raw ?? envVite(viteKey) ?? "").trim().toLowerCase();
  return v === "fake" ? "fake" : "real";
}

function vpModeFrom(raw: string | null | undefined, viteKey: string): OverlayAxisVpMode {
  const v = (raw ?? envVite(viteKey) ?? "").trim().toLowerCase();
  if (v === "fake") return "fake";
  if (v === "ocr_labels_fake") return "ocr_labels_fake";
  return "real";
}

export interface OverlayDiagFlags {
  diagStaticBadge: boolean;
  axisMode: OverlayAxisVpMode;
  vpMode: OverlayAxisVpMode;
  debugAxisLabels: boolean;
}

export function readOverlayDiagEnv(): OverlayDiagFlags {
  return {
    diagStaticBadge: truthy(readStorage("PQ_OVERLAY_DIAG_STATIC_BADGE")),
    axisMode: axisModeFrom(readStorage("PQ_OVERLAY_AXIS_MODE"), "VITE_PQ_OVERLAY_AXIS_MODE"),
    vpMode: vpModeFrom(readStorage("PQ_OVERLAY_VP_MODE"), "VITE_PQ_OVERLAY_VP_MODE"),
    debugAxisLabels:
      truthy(readStorage("PQ_OVERLAY_DEBUG_AXIS_LABELS")) ||
      truthy(envVite("VITE_PQ_OVERLAY_DEBUG_AXIS_LABELS")),
  };
}
