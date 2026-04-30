import { describe, expect, it } from "vitest";

import { parseOverlayUpdatePayload } from "./overlayUpdateCompat";

describe("parseOverlayUpdatePayload", () => {
  it("parseia payload legado", () => {
    const result = parseOverlayUpdatePayload({
      type: "overlay_update",
      data: {
        status: "ok_legacy",
        y_min: 101.5,
        y_max: 202.5,
        axis_status: "stable",
        axis_source: "legacy",
        bad_frames: 2,
        analysis_roi: { left: 10, right: 20 },
        analysis_sample: { count: 3 },
        axis_deltas: { up: 1 },
        axis_diagnostics: { skew: 0.3 },
        debug_visual: { enabled: true },
        lines: [
          {
            value: 150,
            y_screen: 42,
            color: "#fff",
            chart_left: 0,
            chart_right: 100,
            label: "L1",
          },
          {
            value: "invalid",
            y_screen: 1,
            color: "#000",
            chart_left: 0,
            chart_right: 10,
          },
        ],
      },
    });

    expect(result).not.toBeNull();
    expect(result?.status).toBe("ok_legacy");
    expect(result?.lines).toHaveLength(1);
    expect(result?.yMin).toBe(101.5);
    expect(result?.yMax).toBe(202.5);
    expect(result?.axisStatus).toBe("stable");
    expect(result?.axisSource).toBe("legacy");
    expect(result?.badFrames).toBe(2);
    expect(result?.analysisRoi).toEqual({ left: 10, right: 20 });
    expect(result?.analysisSample).toEqual({ count: 3 });
    expect(result?.axisDeltas).toEqual({ up: 1 });
    expect(result?.axisDiagnostics).toEqual({ skew: 0.3 });
    expect(result?.debugVisual).toEqual({ enabled: true });
  });

  it("parseia payload estruturado", () => {
    const result = parseOverlayUpdatePayload({
      type: "overlay_update",
      data: {
        structured: {
          status: {
            state: "ok_structured",
            analysis_roi: { x: 1 },
            analysis_sample: { size: 20 },
          },
          lines: {
            items: [
              {
                value: 10,
                y_screen: 15,
                color: "green",
                chart_left: 5,
                chart_right: 99,
              },
            ],
            visual_limits: {
              y_min: 9,
              y_max: 11,
            },
          },
          histogram: {
            axis_deltas: { p50: 2 },
            axis_diagnostics: { fit: "ok" },
          },
          axis: {
            axis_status: "tracking",
            axis_source: "structured",
            bad_frames: 0,
          },
          debug_visual: { mode: "wireframe" },
        },
      },
    });

    expect(result).not.toBeNull();
    expect(result?.status).toBe("ok_structured");
    expect(result?.lines).toHaveLength(1);
    expect(result?.yMin).toBe(9);
    expect(result?.yMax).toBe(11);
    expect(result?.axisDeltas).toEqual({ p50: 2 });
    expect(result?.axisDiagnostics).toEqual({ fit: "ok" });
    expect(result?.analysisRoi).toEqual({ x: 1 });
    expect(result?.analysisSample).toEqual({ size: 20 });
    expect(result?.axisStatus).toBe("tracking");
    expect(result?.axisSource).toBe("structured");
    expect(result?.badFrames).toBe(0);
    expect(result?.debugVisual).toEqual({ mode: "wireframe" });
  });

  it("suporta payload parcial", () => {
    const result = parseOverlayUpdatePayload({
      type: "overlay_update",
      data: {},
    });

    expect(result).not.toBeNull();
    expect(result?.status).toBe("");
    expect(result?.lines).toEqual([]);
    expect(result?.yMin).toBeNull();
    expect(result?.yMax).toBeNull();
    expect(result?.axisDeltas).toBeNull();
    expect(result?.axisDiagnostics).toBeNull();
    expect(result?.analysisRoi).toBeNull();
    expect(result?.analysisSample).toBeNull();
    expect(result?.axisStatus).toBeNull();
    expect(result?.axisSource).toBeNull();
    expect(result?.badFrames).toBeNull();
    expect(result?.debugVisual).toBeNull();
  });

  it("usa fallback de payload e valida tipo", () => {
    const withPayload = parseOverlayUpdatePayload({
      type: "overlay_update",
      payload: {
        status: "from_payload",
        lines: [
          {
            value: 1,
            y_screen: 2,
            color: "blue",
            chart_left: 3,
            chart_right: 4,
          },
        ],
      },
    });

    const wrongType = parseOverlayUpdatePayload({
      type: "other_event",
      data: {},
    });

    expect(withPayload).not.toBeNull();
    expect(withPayload?.status).toBe("from_payload");
    expect(withPayload?.lines).toHaveLength(1);
    expect(wrongType).toBeNull();
  });
});
