import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { isTauri } from "../../utils/tauri";
import { useSettingsStore } from "../../store/settingsStore";

interface SettingsPanelProps {
  onClose: () => void;
}

type Creds = { key: string; user: string; pass: string };

export function SettingsPanel({ onClose }: SettingsPanelProps) {
  const settings = useSettingsStore();
  const [profitKey, setProfitKey] = useState("");
  const [profitUser, setProfitUser] = useState("");
  const [profitPass, setProfitPass] = useState("");
  const [initialCreds, setInitialCreds] = useState<Creds | null>(null);
  const [saving, setSaving] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [diagnostic, setDiagnostic] = useState<{
    credentials_configured: boolean;
    engine_log_path: string;
    engine_stderr_path?: string;
    app_data_dir?: string;
    offer_book_count: number;
    trade_count: number;
    daily_count: number;
    subscribe_ticker_ret?: number;
    subscribe_offer_book_ret?: number;
    message: string;
  } | null>(null);

  const loadDiagnostic = () => {
    if (!isTauri()) return;
    invoke<{
      credentials_configured: boolean;
      engine_log_path: string;
      engine_stderr_path?: string;
      app_data_dir?: string;
      offer_book_count: number;
      trade_count: number;
      daily_count: number;
      subscribe_ticker_ret?: number;
      subscribe_offer_book_ret?: number;
      message: string;
    }>("get_profit_diagnostic")
      .then(setDiagnostic)
      .catch(() => setDiagnostic(null));
  };

  useEffect(() => {
    if (!isTauri()) return;
    loadDiagnostic();
  }, []);

  useEffect(() => {
    if (!isTauri()) return;
    invoke<{ profit_activation_key?: string; profit_user?: string; profit_password?: string }>("read_config")
      .then((cfg) => {
        const key = cfg.profit_activation_key ?? "";
        const user = cfg.profit_user ?? "";
        const pass = cfg.profit_password ?? "";
        setProfitKey(key);
        setProfitUser(user);
        setProfitPass(pass);
        setInitialCreds({ key, user, pass });
      })
      .catch(() => {});
  }, []);

  const credentialsChanged = (): boolean => {
    if (!initialCreds) return false;
    return (
      profitKey.trim() !== initialCreds.key.trim() ||
      profitUser.trim() !== initialCreds.user.trim() ||
      profitPass !== initialCreds.pass
    );
  };

  const handleSave = async () => {
    if (!isTauri()) {
      onClose();
      return;
    }
    const credsChanged = credentialsChanged();
    setSaving(true);
    try {
      await invoke("write_config", {
        config: {
          profit_activation_key: profitKey || null,
          profit_user: profitUser || null,
          profit_password: profitPass || null,
          notifications_enabled: settings.notificationsEnabled,
          sounds_enabled: settings.soundsEnabled,
          volume: settings.volume,
          minimize_to_tray: settings.minimizeToTray,
          start_with_windows: settings.startWithWindows,
        },
      });
      if (credsChanged) {
        setInitialCreds({ key: profitKey, user: profitUser, pass: profitPass });
        const restartNow = window.confirm(
          "Credenciais salvas. Reiniciar serviços agora para aplicar no engine?"
        );
        if (restartNow) {
          await handleRestartServices();
        }
      }
      onClose();
    } finally {
      setSaving(false);
    }
  };

  const handleRestartServices = async () => {
    if (!isTauri()) return;
    setRestarting(true);
    try {
      await invoke("kill_services");
      await new Promise((r) => setTimeout(r, 500));
      await invoke("spawn_engine");
      await invoke("spawn_distributor");
    } finally {
      setRestarting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-bg/80" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="rounded-lg border border-border bg-grid p-6 w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-text mb-4">Configurações</h2>

        {isTauri() && (
          <div className="space-y-3 mb-6">
            <h3 className="text-sm font-medium text-text/80">Credenciais Profit</h3>
            <input
              type="text"
              placeholder="Chave de acesso (ativação)"
              value={profitKey}
              onChange={(e) => setProfitKey(e.target.value)}
              className="w-full px-3 py-2 rounded bg-bg border border-border text-text text-sm"
            />
            <input
              type="text"
              placeholder="Usuário"
              value={profitUser}
              onChange={(e) => setProfitUser(e.target.value)}
              className="w-full px-3 py-2 rounded bg-bg border border-border text-text text-sm"
            />
            <input
              type="password"
              placeholder="Senha"
              value={profitPass}
              onChange={(e) => setProfitPass(e.target.value)}
              className="w-full px-3 py-2 rounded bg-bg border border-border text-text text-sm"
            />
            <p className="text-xs text-text/60">
              Alterações nas credenciais exigem &quot;Reiniciar serviços&quot; para aplicar no engine.
            </p>
            {diagnostic && (
              <div className="mt-3 p-3 rounded bg-bg/60 border border-border text-xs text-text/90 space-y-1">
                <div className="font-medium text-text">Diagnóstico Profit / DLL</div>
                <p className="text-text/80">{diagnostic.message}</p>
                <p className="text-text/60">
                  Credenciais: {diagnostic.credentials_configured ? "OK" : "Não configuradas"} · Livro: {diagnostic.offer_book_count} · Trades: {diagnostic.trade_count} · Daily: {diagnostic.daily_count}
                  {typeof diagnostic.subscribe_ticker_ret === "number" && (
                    <> · SubscribeTicker: {diagnostic.subscribe_ticker_ret === 0 ? "OK" : diagnostic.subscribe_ticker_ret}</>
                  )}
                  {typeof diagnostic.subscribe_offer_book_ret === "number" && (
                    <> · SubscribeOfferBook: {diagnostic.subscribe_offer_book_ret === 0 ? "OK" : diagnostic.subscribe_offer_book_ret}</>
                  )}
                </p>
                <p className="text-text/50 truncate" title={diagnostic.engine_log_path}>
                  Log: {diagnostic.engine_log_path}
                </p>
                {diagnostic.engine_stderr_path != null && (
                  <p className="text-text/50 truncate text-sm" title={diagnostic.engine_stderr_path}>
                    Se não conectar, verifique erros do engine: {diagnostic.engine_stderr_path}
                  </p>
                )}
                {diagnostic.app_data_dir != null && (
                  <p className="text-text/50 truncate text-sm" title={diagnostic.app_data_dir}>
                    Pasta de logs: {diagnostic.app_data_dir}
                  </p>
                )}
                <div className="flex flex-wrap gap-2 mt-1">
                  <button type="button" onClick={loadDiagnostic} className="text-amber-400 hover:text-amber-300">
                    Atualizar diagnóstico
                  </button>
                  {diagnostic.app_data_dir != null && (
                    <button
                      type="button"
                      onClick={() => invoke("open_log_folder")}
                      className="text-sky-400 hover:text-sky-300"
                    >
                      Abrir pasta de logs
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        <div className="space-y-3 mb-6">
          <label className="flex items-center gap-2 text-text">
            <input
              type="checkbox"
              checked={settings.notificationsEnabled}
              onChange={(e) => settings.setNotificationsEnabled(e.target.checked)}
            />
            Notificações ativadas
          </label>
          <label className="flex items-center gap-2 text-text">
            <input
              type="checkbox"
              checked={settings.soundsEnabled}
              onChange={(e) => settings.setSoundsEnabled(e.target.checked)}
            />
            Sons ativados
          </label>
          <div className="flex items-center gap-2">
            <span className="text-text text-sm">Volume:</span>
            <input
              type="range"
              min="0"
              max="100"
              value={settings.volume}
              onChange={(e) => settings.setVolume(Number(e.target.value))}
              className="flex-1"
            />
            <span className="text-text/60 text-sm w-8">{settings.volume}%</span>
          </div>
          {isTauri() && (
            <>
              <label className="flex items-center gap-2 text-text">
                <input
                  type="checkbox"
                  checked={settings.minimizeToTray}
                  onChange={(e) => settings.setMinimizeToTray(e.target.checked)}
                />
                Minimizar para tray ao fechar
              </label>
              <label className="flex items-center gap-2 text-text">
                <input
                  type="checkbox"
                  checked={settings.startWithWindows}
                  onChange={(e) => settings.setStartWithWindows(e.target.checked)}
                />
                Iniciar com Windows
              </label>
            </>
          )}
        </div>

        <div className="flex gap-2">
          {isTauri() && (
            <button
              onClick={handleRestartServices}
              disabled={restarting}
              title="Aplica as credenciais Profit no engine (reinicia engine e distributor)"
              className="px-4 py-2 rounded bg-amber-600/80 text-white text-sm hover:bg-amber-600 disabled:opacity-50"
            >
              {restarting ? "Reiniciando..." : "Reiniciar serviços"}
            </button>
          )}
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 rounded bg-emerald-600/80 text-white text-sm hover:bg-emerald-600 disabled:opacity-50"
          >
            {saving ? "Salvando..." : "Salvar"}
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded bg-border text-text text-sm hover:bg-border/80"
          >
            Fechar
          </button>
        </div>
      </div>
    </div>
  );
}
