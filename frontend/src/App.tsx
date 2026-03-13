import { useState } from "react";
import { AppLayout } from "./components/layout/AppLayout";
import { SettingsPanel } from "./components/Settings/SettingsPanel";
import { StartupScreen } from "./components/StartupScreen";
import { useAlerts } from "./hooks/useAlerts";
import { useTauriStartup } from "./hooks/useTauriStartup";
import { useWebSocket } from "./hooks/useWebSocket";

function App() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { status, error, configNeeded } = useTauriStartup();
  useWebSocket();
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

export default App;
