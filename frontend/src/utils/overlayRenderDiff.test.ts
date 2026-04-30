import { describe, expect, it } from "vitest";

import { hasMeaningfulLineDiff } from "./overlayRenderDiff";
import type { OverlayCompatLine } from "./overlayUpdateCompat";

const BASE_LINE: OverlayCompatLine = {
  value: 100000,
  y_screen: 400,
  color: "#fff",
  chart_left: 100,
  chart_right: 900,
  label: "L1",
};

describe("overlayRenderDiff", () => {
  it("ignora delta visual menor que 1px", () => {
    const prev = [BASE_LINE];
    const next = [{ ...BASE_LINE, y_screen: 400.5 }];
    expect(hasMeaningfulLineDiff(prev, next, 1)).toBe(false);
  });

  it("detecta delta visual a partir de 1px", () => {
    const prev = [BASE_LINE];
    const next = [{ ...BASE_LINE, y_screen: 401.1 }];
    expect(hasMeaningfulLineDiff(prev, next, 1)).toBe(true);
  });

  it("detecta mudança estrutural mesmo sem delta de y", () => {
    const prev = [BASE_LINE];
    const next = [{ ...BASE_LINE, color: "#0f0" }];
    expect(hasMeaningfulLineDiff(prev, next, 1)).toBe(true);
  });

  it("ignora reordenação de linhas quando conteúdo é igual", () => {
    const l1 = { ...BASE_LINE, label: "A", value: 101 };
    const l2 = { ...BASE_LINE, label: "B", value: 202, y_screen: 350 };
    const prev = [l1, l2];
    const next = [l2, l1];
    expect(hasMeaningfulLineDiff(prev, next, 1)).toBe(false);
  });

  it("detecta alteração de status e out_of_bounds", () => {
    const prev = [{ ...BASE_LINE, status: "stable", out_of_bounds: false }];
    const next = [{ ...BASE_LINE, status: "frozen", out_of_bounds: true }];
    expect(hasMeaningfulLineDiff(prev, next, 1)).toBe(true);
  });

  it("detecta alteração de quantidade de linhas", () => {
    const prev = [BASE_LINE];
    const next = [BASE_LINE, { ...BASE_LINE, label: "L2", value: 100010 }];
    expect(hasMeaningfulLineDiff(prev, next, 1)).toBe(true);
  });

  it("respeita limiar customizado para jitter pequeno", () => {
    const prev = [BASE_LINE];
    const next = [{ ...BASE_LINE, y_screen: 401.1 }];
    expect(hasMeaningfulLineDiff(prev, next, 2)).toBe(false);
  });
});
