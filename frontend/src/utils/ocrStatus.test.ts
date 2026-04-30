import { describe, expect, it } from "vitest";

import { overlayStatusColor, overlayStatusText } from "./ocrStatus";

describe("ocrStatus runtime messaging", () => {
  it("classifica estados degradado/instavel como alerta visual", () => {
    expect(overlayStatusColor("degraded")).toBe("#FFB800");
    expect(overlayStatusColor("unstable")).toBe("#FFB800");
  });

  it("expõe mensagens operacionais para reconexão/degradação", () => {
    expect(overlayStatusText("ocr_unreachable_retrying", null, null)).toContain(
      "reconectando automaticamente",
    );
    expect(overlayStatusText("degraded", null, null)).toContain("degradado");
    expect(overlayStatusText("unstable", null, null)).toContain("instável");
    expect(overlayStatusText("reconnecting", null, null)).toContain("reconectando");
  });
});
