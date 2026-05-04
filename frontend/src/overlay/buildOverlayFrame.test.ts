/** @vitest-environment node */
import type { TapeIntelligenceMessage, VolumeProfileMessage } from "../types/messages";
import type { VpOverlayDisplay } from "../types/messages";
import type { OverlayDiagFlags } from "./overlayDiagEnv";
import type { OverlayLayoutSnapshot } from "./overlayFrameTypes";
import { describe, expect, it } from "vitest";
import { buildOverlayFrame } from "./buildOverlayFrame";

const baseVpPrefs: VpOverlayDisplay = {
  overlay_enabled: true,
  poc_visible: true,
  val_vah_visible: true,
  labels_visible: true,
  histogram_visible: true,
  stretch_lines: false,
};

function baseSnapshot(): OverlayLayoutSnapshot {
  return {
    viewportWidth: 1280,
    viewportHeight: 720,
    devicePixelRatio: 1,
    overlayRightMarginPx: 208,
    showVolumeProfileOverlay: true,
    showTapeIntelligenceOverlay: true,
    vpFallbackMode: "auto",
    fallbackYLock: null,
    manualTop: null,
    manualBot: null,
    data: {
      lines: [],
      status: "connecting",
      y_min: null,
      y_max: null,
      chart_rect: null,
      axis_status: "no_axis",
      normalized_axis_status: "no_axis",
      last_good_axis_age_ms: null,
      parsed_labels_count: null,
    },
    volumeProfile: null,
    tapeIntelligence: null,
    effectiveVpDisplay: baseVpPrefs,
    axisUsableForOcr: false,
    axisUnusableReason: "axis_status_no_axis",
  };
}

const fakeDiag: OverlayDiagFlags = {
  diagStaticBadge: false,
  axisMode: "fake",
  vpMode: "fake",
  debugAxisLabels: false,
};

const diagReal: OverlayDiagFlags = {
  diagStaticBadge: false,
  axisMode: "real",
  vpMode: "real",
  debugAxisLabels: false,
};

const diagAxisFakeOnly: OverlayDiagFlags = {
  diagStaticBadge: false,
  axisMode: "fake",
  vpMode: "real",
  debugAxisLabels: false,
};

const diagVpFakeOnly: OverlayDiagFlags = {
  diagStaticBadge: false,
  axisMode: "real",
  vpMode: "fake",
  debugAxisLabels: false,
};

function minimalTape(vp: VolumeProfileMessage): TapeIntelligenceMessage {
  return {
    topic: "market",
    type: "tape_intelligence",
    ticker: vp.ticker || "TST",
    timestamp: Date.now(),
    poc_price: vp.poc,
    val_price: vp.val,
    vah_price: vp.vah,
    poc_player: 1,
    val_buyer: 2,
    vah_seller: 3,
    poc_top3: [],
    val_top3: [],
    vah_top3: [],
  };
}

function minimalVp(): VolumeProfileMessage {
  return {
    topic: "market",
    type: "volume_profile",
    ticker: "TST",
    period: "day",
    timestamp: Date.now(),
    price_step: 1,
    total_vol: 1000,
    poc: 101,
    vah: 102,
    val: 100,
    poc_y: 200,
    vah_y: 180,
    val_y: 220,
    levels: [
      { price: 100, total_vol: 100, bid_vol: 50, ask_vol: 50, pct_of_max: 0.5 },
      { price: 101, total_vol: 200, bid_vol: 50, ask_vol: 50, pct_of_max: 1, y: 300 },
      { price: 102, total_vol: 100, bid_vol: 50, ask_vol: 50, pct_of_max: 0.5 },
    ],
  };
}

describe("buildOverlayFrame scenarios", () => {
  it("A: no OCR, no VP, badge-only path still returns frame object", () => {
    const r = buildOverlayFrame(baseSnapshot(), diagReal);
    expect(r.viewportInvalid).toBe(false);
    expect(r.error).toBeNull();
    expect(r.frame).not.toBeNull();
    expect(r.frame!.guardStatus).toBeDefined();
    expect(r.renderItemsCount >= 0).toBe(true);
  });

  it("B: axis fake + vp fake renders histogram-ready model", () => {
    const r = buildOverlayFrame(baseSnapshot(), fakeDiag);
    expect(r.frame?.volumeProfileOverlay).not.toBeNull();
    expect((r.frame?.volumeProfileOverlay?.levels.length ?? 0) > 0).toBe(true);
    expect(r.renderItemsCount > 0).toBe(true);
  });

  it("C: axis real insufficient + VP fake injects VP", () => {
    const s = baseSnapshot();
    const r = buildOverlayFrame(s, diagVpFakeOnly);
    expect(r.frame?.volumeProfileOverlay).not.toBeNull();
  });

  it("D: axis fake + VP real uses live VP", () => {
    const s = baseSnapshot();
    const vp = minimalVp();
    s.volumeProfile = vp;
    s.tapeIntelligence = minimalTape(vp);
    const r = buildOverlayFrame(s, diagAxisFakeOnly);
    expect(r.frame?.volumeProfileOverlay).not.toBeNull();
    expect(r.frame?.usingOcrChart).toBe(true);
  });

  it("E: axis real usable + VP real", () => {
    const s = baseSnapshot();
    const vp = minimalVp();
    s.data.chart_rect = { left: 100, top: 100, width: 800, height: 400 };
    s.data.y_min = 95;
    s.data.y_max = 107;
    s.data.axis_status = "stable";
    s.data.normalized_axis_status = "stable";
    s.data.last_good_axis_age_ms = 100;
    s.data.parsed_labels_count = 8;
    s.data.lines = [
      {
        value: 100,
        y_screen: 400,
        color: "#fff",
        chart_left: 100,
        chart_right: 900,
      },
    ];
    s.axisUsableForOcr = true;
    s.volumeProfile = vp;
    s.tapeIntelligence = minimalTape(vp);
    s.axisUnusableReason = "";

    const r = buildOverlayFrame(s, diagReal);
    expect(r.frame?.scaledChartRect).not.toBeNull();
    expect((r.frame?.positionedLines.length ?? 0) > 0).toBe(true);
    expect(r.renderItemsCount > 0).toBe(true);
  });

  it("window size zero yields viewport invalid", () => {
    const s = baseSnapshot();
    s.viewportWidth = 0;
    const r = buildOverlayFrame(s, diagReal);
    expect(r.viewportInvalid).toBe(true);
    expect(r.frame).toBeNull();
  });

  it("non-array data.lines does not throw; treated as empty", () => {
    const s = baseSnapshot();
    (s.data as { lines?: unknown }).lines = { not: "array" };
    expect(() => buildOverlayFrame(s, diagReal)).not.toThrow();
    const r = buildOverlayFrame(s, diagReal);
    expect(r.error).toBeNull();
    expect(r.frame?.positionedLines ?? []).toEqual([]);
  });

  it("VP with non-finite val/vah still builds overlay model when levels are valid", () => {
    const s = baseSnapshot();
    const vp = minimalVp();
    vp.val = Number.NaN;
    vp.vah = Number.NaN;
    s.volumeProfile = vp;
    s.tapeIntelligence = minimalTape(vp);
    const r = buildOverlayFrame(s, diagAxisFakeOnly);
    expect(r.error).toBeNull();
    expect(r.frame?.volumeProfileOverlay).not.toBeNull();
  });

  it("ocr_labels_fake builds VP from axis_samples when axis usable", () => {
    const s = baseSnapshot();
    s.data.chart_rect = { left: 100, top: 100, width: 800, height: 400 };
    s.data.y_min = 90;
    s.data.y_max = 120;
    s.data.axis_status = "stable";
    s.data.normalized_axis_status = "stable";
    s.data.parsed_labels_count = 8;
    s.data.axis_samples = [
      { value: 100, y_screen: 400, y_chart: 100 },
      { value: 110, y_screen: 300, y_chart: 200 },
    ];
    s.axisUsableForOcr = true;
    s.axisUnusableReason = "";
    const diagOcrVp: OverlayDiagFlags = {
      diagStaticBadge: false,
      axisMode: "real",
      vpMode: "ocr_labels_fake",
      debugAxisLabels: false,
    };
    const r = buildOverlayFrame(s, diagOcrVp);
    expect(r.error).toBeNull();
    expect((r.frame?.volumeProfileOverlay?.levels.length ?? 0) > 0).toBe(true);
  });
});
