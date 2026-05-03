/** @vitest-environment node */
import { describe, expect, it } from "vitest";
import { isFiniteChartRect, isOverlayViewportRenderable, isOverlayWindowRenderable } from "./overlayViewportGuards";

describe("overlayViewportGuards", () => {
  it("isOverlayWindowRenderable rejects zero size", () => {
    expect(
      isOverlayWindowRenderable({
        width: 0,
        height: 800,
        devicePixelRatio: 1,
      }),
    ).toBe(false);
    expect(
      isOverlayWindowRenderable({
        width: 100,
        height: 100,
        devicePixelRatio: 0,
      }),
    ).toBe(false);
  });

  it("isFiniteChartRect validates positive area", () => {
    expect(isFiniteChartRect({ left: 0, top: 0, width: 100, height: 50 })).toBe(true);
    expect(isFiniteChartRect({ left: 0, top: 0, width: 0, height: 50 })).toBe(false);
    expect(isFiniteChartRect(null)).toBe(false);
  });

  it("isOverlayViewportRenderable requires chart", () => {
    expect(
      isOverlayViewportRenderable({
        width: 400,
        height: 300,
        devicePixelRatio: 1,
        chart: null,
      }),
    ).toBe(false);
    expect(
      isOverlayViewportRenderable({
        width: 400,
        height: 300,
        devicePixelRatio: 1,
        chart: { left: 1, top: 1, width: 10, height: 10 },
      }),
    ).toBe(true);
  });
});
