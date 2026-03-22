import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { isTauri } from "../../utils/tauri";
import { useSettingsStore } from "../../store/settingsStore";

interface SettingsPanelProps {
  onClose: () => void;
}

type Creds = { key: string; user: string; pass: string };

type Agent007Fields = {
  apiKey: string;
  model: string;
  baseUrl: string;
  referer: string;
  appTitle: string;
};

type AppConfigRead = {
  profit_activation_key?: string;
  profit_user?: string;
  profit_password?: string;
  agent007_api_key?: string;
  agent007_model?: string;
  agent007_base_url?: string;
  agent007_openrouter_http_referer?: string;
  agent007_openrouter_app_title?: string;
};

export function SettingsPanel({ onClose }: SettingsPanelProps) {
  const settings = useSettingsStore();
  const [profitKey, setProfitKey] = useState("");
  const [profitUser, setProfitUser] = useState("");
  const [profitPass, setProfitPass] = useState("");
  const [initialCreds, setInitialCreds] = useState<Creds | null>(null);
  const [agent007ApiKey, setAgent007ApiKey] = useState("");
  const [agent007Model, setAgent007Model] = useState("");
  const [agent007BaseUrl, setAgent007BaseUrl] = useState("");
  const [agent007Referer, setAgent007Referer] = useState("");
  const [agent007AppTitle, setAgent007AppTitle] = useState("");
  const [initialAgent007, setInitialAgent007] = useState<Agent007Fields | null>(null);
  const [agent007AdvancedOpen, setAgent007AdvancedOpen] = useState(false);
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
    invoke<AppConfigRead>("read_config")
      .then((cfg) => {
        const key = cfg.profit_activation_key ?? "";
        const user = cfg.profit_user ?? "";
        const pass = cfg.profit_password ?? "";
        setProfitKey(key);
        setProfitUser(user);
        setProfitPass(pass);
        setInitialCreds({ key, user, pass });
        const a7: Agent007Fields = {
          apiKey: cfg.agent007_api_key ?? "",
          model: cfg.agent007_model ?? "",
          baseUrl: cfg.agent007_base_url ?? "",
          referer: cfg.agent007_openrouter_http_referer ?? "",
          appTitle: cfg.agent007_openrouter_app_title ?? "",
        };
        setAgent007ApiKey(a7.apiKey);
        setAgent007Model(a7.model);
        setAgent007BaseUrl(a7.baseUrl);
        setAgent007Referer(a7.referer);
        setAgent007AppTitle(a7.appTitle);
        setInitialAgent007(a7);
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

  const agent007Changed = (): boolean => {
    if (!initialAgent007) return false;
    return (
      agent007ApiKey.trim() !== initialAgent007.apiKey.trim() ||
      agent007Model.trim() !== initialAgent007.model.trim() ||
      agent007BaseUrl.trim() !== initialAgent007.baseUrl.trim() ||
      agent007Referer.trim() !== initialAgent007.referer.trim() ||
      agent007AppTitle.trim() !== initialAgent007.appTitle.trim()
    );
  };

  const handleSave = async () => {
    if (!isTauri()) {
      onClose();
      return;
    }
    const credsChanged = credentialsChanged();
    const a7Changed = agent007Changed();
    setSaving(true);
    try {
      const config: Record<string, unknown> = {
        profit_activation_key: profitKey.trim() === "" ? undefined : profitKey,
        profit_user: profitUser.trim() === "" ? undefined : profitUser,
        profit_password: profitPass === "" ? undefined : profitPass,
        notifications_enabled: settings.notificationsEnabled,
        sounds_enabled: settings.soundsEnabled,
        volume: settings.volume,
        minimize_to_tray: settings.minimizeToTray,
        start_with_windows: settings.startWithWindows,
      };
      if (initialAgent007 != null) {
        config.agent007_api_key = agent007ApiKey;
        config.agent007_model = agent007Model;
        config.agent007_base_url = agent007BaseUrl;
        config.agent007_openrouter_http_referer = agent007Referer;
        config.agent007_openrouter_app_title = agent007AppTitle;
      }
      await invoke("write_config", { config });
      if (credsChanged) {
        setInitialCreds({ key: profitKey, user: profitUser, pass: profitPass });
      }
      if (a7Changed) {
        setInitialAgent007({
          apiKey: agent007ApiKey,
          model: agent007Model,
          baseUrl: agent007BaseUrl,
          referer: agent007Referer,
          appTitle: agent007AppTitle,
        });
      }
      if (credsChanged || a7Changed) {
        await handleRestartServices();
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
      // Notifica o fluxo de startup para revalidar saúde e reenviar set_active_asset,
      // fazendo o stream voltar sem reiniciar o app.
      window.dispatchEvent(new Event("pq:services-restarted"));
    } finally {
      setRestarting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-bg/80 p-4" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className="rounded-lg border border-border bg-grid p-6 w-full max-w-4xl max-h-[min(90vh,920px)] overflow-y-auto min-w-0 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
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
                <p className="text-text/80 break-words">{diagnostic.message}</p>
                <p className="text-text/60 break-words">
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

        {isTauri() && (
          <div className="space-y-3 mb-6">
            <h3 className="text-sm font-medium text-text/80">Agente 007 / OpenRouter</h3>
            <p className="text-xs text-text/60">
              Chave de API para o chat com IA (ex.:{" "}
              <a
                href="https://openrouter.ai/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sky-400 hover:text-sky-300 underline"
              >
                OpenRouter
              </a>
              ). Na app instalada use este campo — não há <code className="text-text/80">.env</code> no pacote.
            </p>
            <input
              type="password"
              placeholder="API key (OpenRouter)"
              value={agent007ApiKey}
              onChange={(e) => setAgent007ApiKey(e.target.value)}
              autoComplete="off"
              className="w-full px-3 py-2 rounded bg-bg border border-border text-text text-sm"
            />
            <p className="text-xs text-text/60">
              Alterações exigem reinício do distributor para aplicar a chave.
            </p>
            <button
              type="button"
              onClick={() => setAgent007AdvancedOpen((o) => !o)}
              className="text-xs text-sky-400 hover:text-sky-300"
            >
              {agent007AdvancedOpen ? "Ocultar opções avançadas" : "Opções avançadas (modelo, URL, headers)"}
            </button>
            {agent007AdvancedOpen && (
              <div className="pl-2 border-l border-border space-y-3">
                <p className="text-xs text-text/50">Vazio = usar padrão do distributor. Campos em duas colunas em ecrãs largos.</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 gap-x-4">
                  <label className="flex flex-col gap-1 min-w-0 sm:col-span-1">
                    <span className="text-xs text-text/70">Modelo</span>
                    <input
                      type="text"
                      placeholder="ex.: openai/gpt-4o-mini"
                      value={agent007Model}
                      onChange={(e) => setAgent007Model(e.target.value)}
                      className="w-full min-w-0 max-w-full px-3 py-2 rounded bg-bg border border-border text-text text-sm"
                    />
                  </label>
                  <label className="flex flex-col gap-1 min-w-0 sm:col-span-1">
                    <span className="text-xs text-text/70">Base URL</span>
                    <input
                      type="text"
                      placeholder="https://openrouter.ai/api/v1"
                      value={agent007BaseUrl}
                      onChange={(e) => setAgent007BaseUrl(e.target.value)}
                      className="w-full min-w-0 max-w-full px-3 py-2 rounded bg-bg border border-border text-text text-sm"
                    />
                  </label>
                  <label className="flex flex-col gap-1 min-w-0">
                    <span className="text-xs text-text/70">HTTP-Referer</span>
                    <input
                      type="text"
                      placeholder="Opcional (OpenRouter)"
                      value={agent007Referer}
                      onChange={(e) => setAgent007Referer(e.target.value)}
                      className="w-full min-w-0 max-w-full px-3 py-2 rounded bg-bg border border-border text-text text-sm"
                    />
                  </label>
                  <label className="flex flex-col gap-1 min-w-0">
                    <span className="text-xs text-text/70">X-Title</span>
                    <input
                      type="text"
                      placeholder="Opcional (OpenRouter)"
                      value={agent007AppTitle}
                      onChange={(e) => setAgent007AppTitle(e.target.value)}
                      className="w-full min-w-0 max-w-full px-3 py-2 rounded bg-bg border border-border text-text text-sm"
                    />
                  </label>
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

        <div className="flex flex-wrap gap-2">
          {isTauri() && (
            <button
              onClick={handleRestartServices}
              disabled={restarting}
              title="Reinicia engine e distributor (credenciais Profit e chaves Agente 007)"
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
