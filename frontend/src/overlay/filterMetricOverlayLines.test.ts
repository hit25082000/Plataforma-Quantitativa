import { describe, expect, it } from "vitest";
import {
  filterOverlayLinesForVpMode,
  filterOverlayLinesWithoutVp,
  isMetricOcrOverlayLine,
  isVpOcrOverlayLine,
} from "./filterMetricOverlayLines";
import type { OverlayLine } from "./overlayFrameTypes";

function line(label: string): OverlayLine {
  return {
    value: 100_500,
    y_screen: 200,
    color: "#00FF88",
    chart_left: 100,
    chart_right: 900,
    label,
  };
}

describe("filterMetricOverlayLines", () => {
  it("detects VP OCR echo labels", () => {
    expect(isVpOcrOverlayLine("VP POC")).toBe(true);
    expect(isVpOcrOverlayLine("VP VAH")).toBe(true);
    expect(isMetricOcrOverlayLine("Líder comprador (XP)")).toBe(true);
    expect(isMetricOcrOverlayLine("UBS")).toBe(true);
  });

  it("filterOverlayLinesForVpMode keeps only metric lines", () => {
    const mixed = [
      line("VP POC"),
      line("Líder comprador (XP)"),
      line("VP VAL"),
      line("Líder vendedor (BTG)"),
      line("UBS"),
    ];
    const out = filterOverlayLinesForVpMode(mixed);
    expect(out.map((l) => l.label)).toEqual([
      "Líder comprador (XP)",
      "Líder vendedor (BTG)",
      "UBS",
    ]);
  });

  it("filterOverlayLinesWithoutVp drops VP echo only", () => {
    const mixed = [line("VP POC"), line("Manual"), line("UBS")];
    const out = filterOverlayLinesWithoutVp(mixed);
    expect(out.map((l) => l.label)).toEqual(["Manual", "UBS"]);
  });
});
