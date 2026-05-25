/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VpOverlayHud, type VpOverlayHudProps } from "./OverlayPage";

(
  globalThis as typeof globalThis & {
    IS_REACT_ACT_ENVIRONMENT?: boolean;
  }
).IS_REACT_ACT_ENVIRONMENT = true;

const { isTauriMock } = vi.hoisted(() => ({
  isTauriMock: vi.fn(() => false),
}));

vi.mock("../utils/tauri", () => ({
  isTauri: isTauriMock,
}));

function makeProps(overrides: Partial<VpOverlayHudProps> = {}): VpOverlayHudProps {
  return {
    effective: {
      overlay_enabled: true,
      histogram_visible: true,
      poc_visible: true,
      val_vah_visible: true,
      labels_visible: true,
      top_avg_visible: true,
      stretch_lines: false,
      max_visible_histogram_levels: 400,
    },
    showVp: true,
    showTi: true,
    onPatch: vi.fn(),
    onRecalibrate: vi.fn(),
    onFreeze: vi.fn(),
    onUnfreeze: vi.fn(),
    recalibrateHint: null,
    axisActionHint: null,
    manualCalibrateHint: null,
    vpPeriod: "day",
    onVpPeriod: vi.fn(),
    streamVpPeriod: null,
    health: null,
    overlayDebug: {
      axisStatus: null,
      axisSource: null,
      badFrames: null,
      pendingFrames: null,
      labelsCount: null,
      residualPx: null,
      maxErrorPx: null,
      slope: null,
      intercept: null,
      valuePerPx: null,
      lineStatusSummary: "",
    },
    vpOverlayRawTicker: null,
    vpOverlayAgeMs: null,
    showVisualDebug: false,
    onToggleVisualDebug: vi.fn(),
    debugLayerVisibility: {
      ocrLabels: true,
      regression: true,
      roi: true,
      bounds: true,
    },
    onToggleDebugLayer: vi.fn(),
    manualCalibrateMode: false,
    onToggleManualCalibrateMode: vi.fn(),
    manualPointA: null,
    manualPointB: null,
    onSetManualPointAValue: vi.fn(),
    onSetManualPointBValue: vi.fn(),
    onSubmitManualCalibration: vi.fn(),
    onClearManualCalibration: vi.fn(),
    onReturnAutoAxis: vi.fn(),
    ocrHudCollapsed: false,
    onSetOcrHudCollapsed: vi.fn(),
    onCloseOverlay: vi.fn(),
    ...overrides,
  };
}

interface InteractiveHudResult {
  container: HTMLDivElement;
  rerender: (overrides?: Partial<VpOverlayHudProps>) => void;
  unmount: () => void;
  onPatch: ReturnType<typeof vi.fn>;
  onToggleVisualDebug: ReturnType<typeof vi.fn>;
  onToggleDebugLayer: ReturnType<typeof vi.fn>;
  onToggleManualCalibrateMode: ReturnType<typeof vi.fn>;
  onSubmitManualCalibration: ReturnType<typeof vi.fn>;
  onVpPeriod: ReturnType<typeof vi.fn>;
  onFreeze: ReturnType<typeof vi.fn>;
  onUnfreeze: ReturnType<typeof vi.fn>;
  onReturnAutoAxis: ReturnType<typeof vi.fn>;
}

function renderHudInteractive(overrides: Partial<VpOverlayHudProps> = {}): InteractiveHudResult {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const onPatch = vi.fn();
  const onToggleVisualDebug = vi.fn();
  const onToggleDebugLayer = vi.fn();
  const onToggleManualCalibrateMode = vi.fn();
  const onSetManualPointAValue = vi.fn();
  const onSetManualPointBValue = vi.fn();
  const onSubmitManualCalibration = vi.fn();
  const onVpPeriod = vi.fn();
  const onFreeze = vi.fn();
  const onUnfreeze = vi.fn();
  const onReturnAutoAxis = vi.fn();
  const baseOverrides: Partial<VpOverlayHudProps> = {
    onPatch,
    onToggleVisualDebug,
    onToggleDebugLayer,
    onToggleManualCalibrateMode,
    onSetManualPointAValue,
    onSetManualPointBValue,
    onSubmitManualCalibration,
    onVpPeriod,
    onFreeze,
    onUnfreeze,
    onReturnAutoAxis,
  };

  const doRender = (nextOverrides: Partial<VpOverlayHudProps> = {}) => {
    act(() => {
      root.render(<VpOverlayHud {...makeProps({ ...baseOverrides, ...nextOverrides })} />);
    });
  };

  doRender(overrides);
  return {
    container,
    rerender: doRender,
    unmount: () => {
      act(() => {
        root.unmount();
      });
      container.remove();
    },
    onPatch,
    onToggleVisualDebug,
    onToggleDebugLayer,
    onToggleManualCalibrateMode,
    onSubmitManualCalibration,
    onVpPeriod,
    onFreeze,
    onUnfreeze,
    onReturnAutoAxis,
  };
}

function byLabel<T extends Element = Element>(container: ParentNode, label: string): T {
  const el = container.querySelector(`[aria-label="${label}"]`);
  if (!el) throw new Error(`Elemento não encontrado: ${label}`);
  return el as T;
}

function dispatchClick(element: Element): void {
  act(() => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function dispatchInput(element: HTMLInputElement | HTMLSelectElement, value: string): void {
  act(() => {
    element.value = value;
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

describe("VpOverlayHud", () => {
  const mounted: Array<{ unmount: () => void }> = [];
  const mount = (overrides: Partial<VpOverlayHudProps> = {}) => {
    const mountedHud = renderHudInteractive(overrides);
    mounted.push(mountedHud);
    return mountedHud;
  };

  beforeEach(() => {
    // no-op: act environment is configured at module scope.
  });

  afterEach(() => {
    isTauriMock.mockReturnValue(false);
    while (mounted.length > 0) {
      mounted.pop()?.unmount();
    }
  });

  it("renderiza bloco de saúde com estado missing e badge de erro", () => {
    const { container } = mount({
      health: {
        overlay_age_state: "missing",
      } as VpOverlayHudProps["health"],
    });

    expect(container.textContent).toContain("Saúde / OCR");
    expect(container.textContent).toContain("overlay: degradado");
    expect(container.textContent).toContain("motivo: sem payload recente");
    expect(container.textContent).toContain("ação: aguardar próximo payload ou reabrir overlay");
    expect(container.textContent).toContain("ERRO");
  });

  it("renderiza estado stale/fresh conforme transição de saúde", () => {
    const { container, rerender } = mount({
      health: {
        overlay_age_state: "stale",
      } as VpOverlayHudProps["health"],
    });
    expect(container.textContent).toContain("overlay: instável");
    expect(container.textContent).toContain("motivo: payload desatualizado");
    expect(container.textContent).toContain("ação: validar estabilidade do feed antes de operar");
    expect(container.textContent).toContain("ALERTA");

    rerender({
      health: {
        overlay_age_state: "fresh",
      } as VpOverlayHudProps["health"],
    });
    expect(container.textContent).toContain("overlay: atualizado");
    expect(container.textContent).toContain("ação: operação normal: seguir monitorando");
    expect(container.textContent).toContain("INFO");
  });

  it("eleva badge para erro quando runtime reporta falha mesmo com age fresh", () => {
    const { container } = mount({
      health: {
        overlay_age_state: "fresh",
        data_status: "error: ocr timeout",
      } as VpOverlayHudProps["health"],
    });
    expect(container.textContent).toContain("overlay: degradado");
    expect(container.textContent).toContain("motivo: falha no runtime OCR");
    expect(container.textContent).toContain("ação: manter overlay aberto e revisar logs do runtime OCR");
    expect(container.textContent).toContain("ERRO");
  });

  it("marca instável em pressão de frames e sanitiza contadores negativos", () => {
    const { container } = mount({
      health: {
        overlay_age_state: "fresh",
      } as VpOverlayHudProps["health"],
      overlayDebug: {
        axisStatus: null,
        axisSource: null,
        badFrames: -4,
        pendingFrames: 7,
        labelsCount: null,
        residualPx: null,
        maxErrorPx: null,
        slope: null,
        intercept: null,
        valuePerPx: null,
        lineStatusSummary: "",
      },
    });
    expect(container.textContent).toContain("overlay: instável");
    expect(container.textContent).toContain("motivo: fila/bad frames elevados");
    expect(container.textContent).toContain("ação: reduzir carga visual e monitorar normalização dos frames");
    expect(container.textContent).toContain("ALERTA");
    expect(container.textContent).toContain("bad frames: 0");
    expect(container.textContent).toContain("pending: 7");
  });

  it("prioriza ação de recalibração quando eixo sinaliza erro", () => {
    const { container } = mount({
      health: {
        overlay_age_state: "fresh",
        axis_status: "AUTO_ERROR",
      } as VpOverlayHudProps["health"],
    });
    expect(container.textContent).toContain("overlay: degradado");
    expect(container.textContent).toContain("motivo: eixo OCR inconsistente");
    expect(container.textContent).toContain("ação: acionar recalibrar eixo e validar leitura no gráfico");
    expect(container.textContent).toContain("ERRO");
  });

  it("aciona callbacks de debug visual e camadas", () => {
    const { container, rerender, onToggleVisualDebug, onToggleDebugLayer } = mount({
      showVisualDebug: false,
    });
    const visualDebugToggle = byLabel<HTMLInputElement>(
      container,
      "Ativar camada de debug visual OCR",
    );
    dispatchClick(visualDebugToggle);
    expect(onToggleVisualDebug).toHaveBeenCalledWith(true);
    expect(container.textContent).not.toContain("Labels OCR");

    rerender({ showVisualDebug: true });
    const labelsToggle = byLabel<HTMLInputElement>(container, "Exibir labels OCR");
    dispatchClick(labelsToggle);
    expect(onToggleDebugLayer).toHaveBeenCalledWith("ocrLabels", false);
  });

  it("bloco manual valida inputs, estados e callbacks críticos", () => {
    const {
      container,
      onToggleManualCalibrateMode,
      onVpPeriod,
    } = mount({
      manualCalibrateMode: false,
    });
    const manualModeToggle = byLabel<HTMLInputElement>(
      container,
      "Ativar calibração manual em dois pontos",
    );
    dispatchClick(manualModeToggle);
    expect(onToggleManualCalibrateMode).toHaveBeenCalledWith(true);
    expect(container.textContent).not.toContain("Aplicar eixo manual");

    dispatchInput(
      byLabel<HTMLSelectElement>(container, "Selecionar período do volume profile"),
      "week",
    );
    expect(onVpPeriod).toHaveBeenCalledWith("week");

    const withManual = mount({
      manualCalibrateMode: true,
      manualPointA: { y: 120, value: "1000" },
      manualPointB: { y: 120, value: "1000" },
    });
    const pointAInput = byLabel<HTMLInputElement>(withManual.container, "Preço do ponto A");
    const pointBInput = byLabel<HTMLInputElement>(withManual.container, "Preço do ponto B");
    dispatchInput(pointAInput, "1010");
    dispatchInput(pointBInput, "990");

    const applyButton = byLabel<HTMLButtonElement>(withManual.container, "Aplicar calibração manual");
    expect(applyButton.disabled).toBe(true);
    dispatchClick(applyButton);
    expect(withManual.onSubmitManualCalibration).not.toHaveBeenCalled();
    expect(withManual.container.textContent).toContain("A e B precisam ter preços diferentes.");
  });

  it("habilita aplicar calibração quando A/B são válidos e orientados", () => {
    const { container, onSubmitManualCalibration } = mount({
      manualCalibrateMode: true,
      manualPointA: { y: 100, value: "1100" },
      manualPointB: { y: 200, value: "1000" },
    });
    const applyButton = byLabel<HTMLButtonElement>(container, "Aplicar calibração manual");
    expect(applyButton.disabled).toBe(false);
    dispatchClick(applyButton);
    expect(onSubmitManualCalibration).toHaveBeenCalledTimes(1);
  });

  it("respeita estados de habilitação para VP e T&T", () => {
    const { container } = mount({ showVp: false, showTi: false });
    expect(byLabel<HTMLInputElement>(container, "Exibir histograma do volume profile").disabled).toBe(true);
    expect(byLabel<HTMLInputElement>(container, "Exibir etiquetas de times and trades").disabled).toBe(true);
    expect(byLabel<HTMLInputElement>(container, "Exibir linhas monitoradas UBS e líderes").disabled).toBe(true);
  });

  it("cobre sequência manual completa de lock/unlock no HUD", () => {
    isTauriMock.mockReturnValue(true);
    const { container, onFreeze, onUnfreeze, onReturnAutoAxis } = mount({
      axisActionHint: "eixo congelado (manual lock)",
      manualCalibrateHint: "manual_axis_unlocked",
      health: {
        overlay_age_state: "fresh",
        axis_status: "MANUAL_LOCKED",
        axis_source: "manual",
      } as VpOverlayHudProps["health"],
      manualCalibrateMode: true,
      manualPointA: { y: 120, value: "1100" },
      manualPointB: { y: 200, value: "1000" },
    });

    expect(container.textContent).toContain("OCR OVERLAY DEBUG");
    expect(container.textContent).toContain("Saúde / OCR");
    expect(container.textContent).toContain("axis: MANUAL_LOCKED / manual");
    expect(container.textContent).toContain("eixo congelado (manual lock)");
    expect(container.textContent).toContain("manual_axis_unlocked");

    dispatchClick(byLabel<HTMLButtonElement>(container, "Congelar eixo manualmente"));
    dispatchClick(byLabel<HTMLButtonElement>(container, "Descongelar eixo manualmente"));
    expect(onFreeze).toHaveBeenCalledTimes(1);
    expect(onUnfreeze).toHaveBeenCalledTimes(1);

    const returnAutoAxisBtn = byLabel<HTMLButtonElement>(
      container,
      "Retornar para modo automático de eixo",
    );
    expect(returnAutoAxisBtn.disabled).toBe(false);
    expect(returnAutoAxisBtn.textContent).toContain("Voltar para eixo automático");
    dispatchClick(returnAutoAxisBtn);
    expect(onReturnAutoAxis).toHaveBeenCalledTimes(1);
  });

  it("mantém retorno automático desabilitado quando eixo não está travado manualmente", () => {
    isTauriMock.mockReturnValue(true);
    const { container } = mount({
      health: {
        overlay_age_state: "fresh",
        axis_status: "AUTO_OK",
        axis_source: "auto",
      } as VpOverlayHudProps["health"],
    });
    const returnAutoAxisBtn = byLabel<HTMLButtonElement>(
      container,
      "Retornar para modo automático de eixo",
    );
    expect(returnAutoAxisBtn.disabled).toBe(true);
    expect(returnAutoAxisBtn.getAttribute("title")).toContain("MANUAL_LOCKED");
  });
});
