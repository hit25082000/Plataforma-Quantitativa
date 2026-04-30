import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import { useEffect, useState } from "react";
import { AppLayout } from "./components/layout/AppLayout";
import { WidgetRoot } from "./components/WidgetRoot";
import { SettingsPanel } from "./components/Settings/SettingsPanel";
import { StartupScreen } from "./components/StartupScreen";
import OverlayEmergencyControlPage from "./pages/OverlayEmergencyControlPage";
import OcrRoiPickerPage from "./pages/OcrRoiPickerPage";
import OverlayPage from "./pages/OverlayPage";
import { useAlerts } from "./hooks/useAlerts";
import { useTauriStartup } from "./hooks/useTauriStartup";
import { useWebSocket } from "./hooks/useWebSocket";
import {
  PQ_IFR_SERIES_EVENT,
  PQ_SELECTED_ASSET_EVENT,
  type PqIfrSeriesPayload,
  type PqSelectedAssetPayload,
} from "./constants/pqTauriEvents";
import { useMarketStore } from "./store/marketStore";
import {
  applyMarketConfigToStore,
  readConfigAndHydrateMarketStore,
} from "./utils/hydrateMarketFromConfig";
import { isTauri } from "./utils/tauri";
import { fetchWarmMacdSnapshot } from "./utils/warmMacd";

function AppContent() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { status, error, configNeeded } = useTauriStartup();
  useWebSocket(isTauri() ? status === "ready" : true);
  useAlerts();

  return (
    <>
      <StartupScreen status={status} error={error} />
      {configNeeded && (
        <div className="fixed top-0 left-0 right-0 z-40 flex items-center justify-center gap-3 px-4 py-2 bg-amber-900/90 text-amber-100 text-sm border-b border-amber-700/50">
          <span className="flex-1 text-center">{error}</span>
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="shrink-0 px-3 py-1 rounded bg-amber-600 hover:bg-amber-500 text-white font-medium"
          >
            Abrir Configurações
          </button>
        </div>
      )}
      <div className={configNeeded ? "pt-12" : undefined}>
        <AppLayout onOpenSettings={() => setSettingsOpen(true)} />
      </div>
      {settingsOpen && <SettingsPanel onClose={() => setSettingsOpen(false)} />}
    </>
  );
}

function WidgetWindow({ widgetId }: { widgetId: string }) {
  const [marketHydrated, setMarketHydrated] = useState(false);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const ifrMode = await readConfigAndHydrateMarketStore();
        try {
          await invoke("sync_ifr_series_to_distributor", { series: ifrMode });
        } catch {
          // distributor pode estar indisponível
        }
      } catch {
        // config ilegível: mantém defaults do store
      } finally {
        if (!cancelled) setMarketHydrated(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    void listen<PqSelectedAssetPayload>(PQ_SELECTED_ASSET_EVENT, (ev) => {
      const { ticker, exchange } = ev.payload;
      applyMarketConfigToStore({
        selected_ticker: ticker,
        selected_exchange: exchange,
      });
      useMarketStore
        .getState()
        .setTimesTradesLoading(true, "Atualizando Times & Trades");
      void fetchWarmMacdSnapshot({
        retries: 8,
        retryDelayMs: 250,
      });
    }).then((fn) => {
      unlisten = fn;
    });
    return () => {
      unlisten?.();
    };
  }, []);
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    void listen<PqIfrSeriesPayload>(PQ_IFR_SERIES_EVENT, (ev) => {
      const s = ev.payload.series;
      if (s !== "42r" && s !== "16r" && s !== "30m") return;
      useMarketStore.getState().setIfrSeries(s);
      useMarketStore.getState().setIfrLoading(true, s, "Atualizando IFR");
      void invoke("sync_ifr_series_to_distributor", { series: s }).catch(
        () => {},
      );
      void fetchWarmMacdSnapshot({
        retries: 8,
        retryDelayMs: 250,
        expectedSeries: s,
      });
    }).then((fn) => {
      unlisten = fn;
    });
    return () => {
      unlisten?.();
    };
  }, []);
  useWebSocket(marketHydrated);
  useAlerts();
  return (
    <div className="h-screen flex flex-col">
      <WidgetRoot widgetId={widgetId} />
    </div>
  );
}

function App() {
  const [widgetId, setWidgetId] = useState<string | null>(null);
  const [isOverlayWindow, setIsOverlayWindow] = useState(false);
  const [isOverlayControlWindow, setIsOverlayControlWindow] = useState(false);
  const [isOcrRoiPickerWindow, setIsOcrRoiPickerWindow] = useState(false);
  const [hasCheckedWindow, setHasCheckedWindow] = useState(false);

  useEffect(() => {
    if (!isTauri()) {
      setHasCheckedWindow(true);
      return;
    }
    import("@tauri-apps/api/window").then(({ getCurrentWindow }) => {
      const w = getCurrentWindow();
      const label = w.label;
      if (label.startsWith("widget-")) {
        setWidgetId(label.replace(/^widget-/, ""));
      }
      if (label === "profit-overlay") {
        setIsOverlayWindow(true);
      }
      if (label === "profit-overlay-control") {
        setIsOverlayControlWindow(true);
      }
      if (label === "ocr-roi-picker") {
        setIsOcrRoiPickerWindow(true);
      }
      setHasCheckedWindow(true);
    });
  }, []);

  if (isTauri() && !hasCheckedWindow) {
    return (
      <div className="h-screen flex items-center justify-center bg-bg text-text/60 text-sm">
        Carregando…
      </div>
    );
  }

  if (isTauri() && widgetId) {
    return <WidgetWindow widgetId={widgetId} />;
  }

  if (isTauri() && isOverlayWindow) {
    return <OverlayPage />;
  }

  if (isTauri() && isOverlayControlWindow) {
    return <OverlayEmergencyControlPage />;
  }

  if (isTauri() && isOcrRoiPickerWindow) {
    return <OcrRoiPickerPage />;
  }

  return <AppContent />;
}

export default App;
