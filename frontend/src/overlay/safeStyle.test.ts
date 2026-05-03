/** @vitest-environment node */
import { describe, expect, it } from "vitest";
import { safeNumber, safePx } from "./safeStyle";

describe("safeStyle", () => {
  it("safeNumber returns finite numbers or fallback", () => {
    expect(safeNumber(3.5, 0)).toBe(3.5);
    expect(safeNumber(NaN, 7)).toBe(7);
    expect(safeNumber(Infinity, 7)).toBe(7);
    expect(safeNumber("-2", -1)).toBe(-2);
    expect(safeNumber("x", 2)).toBe(2);
    expect(safeNumber(undefined, 1)).toBe(1);
    expect(safeNumber(null, 1)).toBe(1);
  });

  it("safePx matches safeNumber semantics", () => {
    expect(safePx(10, 5)).toBe(10);
    expect(safePx(Number.NaN, 4)).toBe(4);
  });
});
