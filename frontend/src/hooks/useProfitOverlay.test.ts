import { describe, expect, it } from "vitest";

import { overlayLineColorForLabel } from "./useProfitOverlay";

describe("overlayLineColorForLabel", () => {
  it("usa cor fixa da UBS", () => {
    expect(overlayLineColorForLabel("UBS", 0)).toBe("#A855F7");
  });

  it("prioriza mapeamento para comprador e vendedor", () => {
    expect(overlayLineColorForLabel("Lider comprador", 0)).toBe("#00FF88");
    expect(overlayLineColorForLabel("Fluxo de venda", 0)).toBe("#FF4444");
  });

  it("usa fallback por índice quando label não é mapeada", () => {
    expect(overlayLineColorForLabel("Outra linha", 0)).toBe("#00FF88");
    expect(overlayLineColorForLabel("Outra linha", 1)).toBe("#FF4444");
    expect(overlayLineColorForLabel("Outra linha", 2)).toBe("#FFB800");
  });

  it("não classifica venda quando label também cita compra", () => {
    expect(overlayLineColorForLabel("compra e venda", 0)).toBe("#00FF88");
  });

  it("normaliza espaços e caixa para UBS", () => {
    expect(overlayLineColorForLabel("  uBs  ", 3)).toBe("#A855F7");
  });
});
