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
        pending_frames: 1,
        labels_count: 6,
        residual_px: 1.25,
        max_error_px: 2.5,
        slope: -0.33,
        intercept: 542,
        value_per_px: 0.2,
        analysis_roi: { left: 10, right: 20 },
        analysis_sample: { count: 3 },
        axis_deltas: {
          delta_first_last_value: 10,
          delta_first_last_y: 50,
          labels_count: 4,
          delta_intervals: [
            {
              i: 0,
              value_delta: 2,
              y_delta: 10,
              value_per_px_segment: 0.2,
            },
          ],
        },
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
    expect(result?.confidence).toBeNull();
    expect(result?.axisStatus).toBe("stable");
    expect(result?.axisSource).toBe("legacy");
    expect(result?.badFrames).toBe(2);
    expect(result?.pendingFrames).toBe(1);
    expect(result?.labelsCount).toBe(6);
    expect(result?.residualPx).toBe(1.25);
    expect(result?.maxErrorPx).toBe(2.5);
    expect(result?.slope).toBe(-0.33);
    expect(result?.intercept).toBe(542);
    expect(result?.valuePerPx).toBe(0.2);
    expect(result?.analysisRoi).toEqual({ left: 10, right: 20 });
    expect(result?.analysisSample).toEqual({ count: 3 });
    expect(result?.axisDeltas).toEqual({
      delta_first_last_value: 10,
      delta_first_last_y: 50,
      labels_count: 4,
      delta_intervals: [
        {
          i: 0,
          value_delta: 2,
          y_delta: 10,
          value_per_px_segment: 0.2,
        },
      ],
    });
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
            axis_deltas: {
              delta_first_last_value: 12,
              delta_first_last_y: 48,
              labels_count: 5,
              delta_intervals: [
                {
                  i: 1,
                  value_delta: 3,
                  y_delta: 12,
                  value_per_px_segment: 0.25,
                },
              ],
            },
            axis_diagnostics: { fit: "ok" },
          },
          axis: {
            axis_status: "tracking",
            axis_source: "structured",
            bad_frames: 0,
            pending_frames: 4,
            labels_count: 7,
            residual_px: 0.8,
            max_error_px: 1.6,
            slope: -0.15,
            intercept: 410,
            value_per_px: 0.09,
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
    expect(result?.axisDeltas).toEqual({
      delta_first_last_value: 12,
      delta_first_last_y: 48,
      labels_count: 5,
      delta_intervals: [
        {
          i: 1,
          value_delta: 3,
          y_delta: 12,
          value_per_px_segment: 0.25,
        },
      ],
    });
    expect(result?.axisDiagnostics).toEqual({ fit: "ok" });
    expect(result?.analysisRoi).toEqual({ x: 1 });
    expect(result?.analysisSample).toEqual({ size: 20 });
    expect(result?.confidence).toBeNull();
    expect(result?.axisStatus).toBe("tracking");
    expect(result?.axisSource).toBe("structured");
    expect(result?.badFrames).toBe(0);
    expect(result?.pendingFrames).toBe(4);
    expect(result?.labelsCount).toBe(7);
    expect(result?.residualPx).toBe(0.8);
    expect(result?.maxErrorPx).toBe(1.6);
    expect(result?.slope).toBe(-0.15);
    expect(result?.intercept).toBe(410);
    expect(result?.valuePerPx).toBe(0.09);
    expect(result?.debugVisual).toEqual({ mode: "wireframe" });
  });

  it("aceita pending_count como alias de pending_frames", () => {
    const result = parseOverlayUpdatePayload({
      type: "overlay_update",
      data: {
        structured: {
          axis: {
            pending_count: 3,
          },
        },
      },
    });

    expect(result).not.toBeNull();
    expect(result?.pendingFrames).toBe(3);
  });

  it("prioriza pending_count canônico quando conflito com pending_frames", () => {
    const result = parseOverlayUpdatePayload({
      type: "overlay_update",
      data: {
        pending_count: 7,
        pending_frames: 2,
        structured: {
          axis: {
            pending_count: 5,
            pending_frames: 1,
          },
        },
      },
    });

    expect(result).not.toBeNull();
    expect(result?.pendingFrames).toBe(7);
  });

  it("suporta payload com blocks sem structured", () => {
    const result = parseOverlayUpdatePayload({
      type: "overlay_update",
      data: {
        blocks: {
          status: {
            state: "ok_blocks_only",
          },
          lines: {
            items: [
              {
                value: 42,
                y_screen: 77,
                color: "#fff",
                chart_left: 1,
                chart_right: 2,
              },
            ],
            visual_limits: {
              y_min: 40,
              y_max: 45,
            },
          },
          axis: {
            axis_status: "STABLE",
            axis_source: "ocr",
            source: "legacy_source",
            confidence: 0.88,
            pending_count: 2,
          },
          histogram: {
            axis_diagnostics: { source: "blocks" },
          },
          debug_visual: { mode: "blocks" },
        },
      },
    });

    expect(result).not.toBeNull();
    expect(result?.status).toBe("ok_blocks_only");
    expect(result?.lines).toHaveLength(1);
    expect(result?.yMin).toBe(40);
    expect(result?.yMax).toBe(45);
    expect(result?.axisStatus).toBe("STABLE");
    expect(result?.axisSource).toBe("ocr");
    expect(result?.confidence).toBe(0.88);
    expect(result?.pendingFrames).toBe(2);
    expect(result?.axisDiagnostics).toEqual({ source: "blocks" });
    expect(result?.debugVisual).toEqual({ mode: "blocks" });
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
    expect(result?.confidence).toBeNull();
    expect(result?.axisStatus).toBeNull();
    expect(result?.axisSource).toBeNull();
    expect(result?.badFrames).toBeNull();
    expect(result?.pendingFrames).toBeNull();
    expect(result?.labelsCount).toBeNull();
    expect(result?.residualPx).toBeNull();
    expect(result?.maxErrorPx).toBeNull();
    expect(result?.slope).toBeNull();
    expect(result?.intercept).toBeNull();
    expect(result?.valuePerPx).toBeNull();
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

  it("parseia payload dual sem envelope type", () => {
    const result = parseOverlayUpdatePayload({
      status: "ok_dual",
      axis_status: "MANUAL_LOCKED",
      axis_source: "manual",
      pending_count: 2,
      structured: {
        lines: {
          items: [
            {
              value: 99,
              y_screen: 140,
              color: "#abc",
              chart_left: 10,
              chart_right: 80,
            },
          ],
        },
      },
      blocks: {
        histogram: {
          axis_diagnostics: { pending_frames: 2 },
        },
      },
    });

    expect(result).not.toBeNull();
    expect(result?.status).toBe("ok_dual");
    expect(result?.lines).toHaveLength(1);
    expect(result?.axisStatus).toBe("MANUAL_LOCKED");
    expect(result?.axisSource).toBe("manual");
    expect(result?.pendingFrames).toBe(2);
    expect(result?.axisDiagnostics).toEqual({ pending_frames: 2 });
  });

  it("usa fallback de regressão no debug_visual quando axis não envia métricas", () => {
    const result = parseOverlayUpdatePayload({
      type: "overlay_update",
      data: {
        structured: {
          debug_visual: {
            regression: {
              slope: -0.27,
              intercept: 700,
              value_per_px: 0.14,
            },
          },
        },
      },
    });

    expect(result).not.toBeNull();
    expect(result?.slope).toBe(-0.27);
    expect(result?.intercept).toBe(700);
    expect(result?.valuePerPx).toBe(0.14);
  });

  it("prioriza axis_deltas válido de histogram quando legado está incompleto", () => {
    const result = parseOverlayUpdatePayload({
      type: "overlay_update",
      data: {
        axis_deltas: {
          delta_first_last_value: 10,
          labels_count: 2,
        },
        histogram: {
          axis_deltas: {
            delta_first_last_value: 11,
            delta_first_last_y: 55,
            labels_count: 3,
            delta_intervals: [
              {
                i: 1,
                value_delta: 4,
                y_delta: 20,
                value_per_px_segment: 0.2,
              },
            ],
          },
        },
      },
    });

    expect(result).not.toBeNull();
    expect(result?.axisDeltas).toEqual({
      delta_first_last_value: 11,
      delta_first_last_y: 55,
      labels_count: 3,
      delta_intervals: [
        {
          i: 1,
          value_delta: 4,
          y_delta: 20,
          value_per_px_segment: 0.2,
        },
      ],
    });
  });

  it("aceita aliases source/confidence em structured axis", () => {
    const result = parseOverlayUpdatePayload({
      type: "overlay_update",
      data: {
        structured: {
          axis: {
            source: "manual",
            confidence: 0.91,
          },
        },
      },
    });

    expect(result).not.toBeNull();
    expect(result?.axisStatus).toBeNull();
    expect(result?.axisSource).toBe("manual");
    expect(result?.confidence).toBe(0.91);
  });

  it("usa axis_diagnostics top-level quando coexistem com histogram", () => {
    const result = parseOverlayUpdatePayload({
      type: "overlay_update",
      data: {
        axis_diagnostics: { source: "top-level", labels_count: 8 },
        histogram: {
          axis_diagnostics: { source: "histogram", labels_count: 3 },
        },
      },
    });

    expect(result).not.toBeNull();
    expect(result?.axisDiagnostics).toEqual({ source: "top-level", labels_count: 8 });
    expect(result?.labelsCount).toBe(8);
  });

  it("descarta linhas inválidas em items estruturados", () => {
    const result = parseOverlayUpdatePayload({
      type: "overlay_update",
      data: {
        structured: {
          lines: {
            items: [
              {
                value: 123,
                y_screen: 222,
                color: "#fff",
                chart_left: 10,
                chart_right: 50,
              },
              {
                value: 321,
                y_screen: "bad",
                color: "#000",
                chart_left: 10,
                chart_right: 50,
              },
            ],
          },
        },
      },
    });

    expect(result).not.toBeNull();
    expect(result?.lines).toHaveLength(1);
    expect(result?.lines[0]?.value).toBe(123);
  });
});
