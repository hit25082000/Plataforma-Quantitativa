import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { applyMarketConfigToStore } from "../utils/hydrateMarketFromConfig";
import { isTauri } from "../utils/tauri";
import { useSettingsStore } from "../store/settingsStore";

export type StartupStatus =
  | "idle"
  | "checking"
  | "starting"
  | "ready"
  | "error";

const CONFIG_NEEDED_MESSAGE =
  'Configure usuário, senha e chave de acesso em Configurações e use "Reiniciar serviços" para aplicar.';

function isEngineNotListening(message: string): boolean {
  const raw = (message ?? "").trim();
  if (!raw) {
    return false;
  }
  const m = raw.toLowerCase();
  const explicitNotListening =
    m.includes("não está escutando") ||
    m.includes("nao esta escutando") ||
    m.includes("escutando na porta");
  const refused =
    m.includes("connection refused") ||
    m.includes("actively refused") ||
    m.includes("forcibly rejected");
  return (
    explicitNotListening ||
    refused
  );
}

const SWITCH_RETRY_MS = 2000;
const SWITCH_MAX_ATTEMPTS = 15;
const RESPAWN_EVERY_ATTEMPTS = 3;
const DISTRIBUTOR_HEALTH_TIMEOUT_MS = 10000;
const DISTRIBUTOR_HEALTH_POLL_MS = 300;
const DISTRIBUTOR_READY_TIMEOUT_MS = 60000;
const DISTRIBUTOR_READY_POLL_MS = 500;

interface SwitchRetryResult {
  success: boolean;
  message: string;
}

interface DistributorReadyPayload {
  ok?: boolean;
  ready?: boolean;
  ipc_status?: string;
  ipc_mode?: string;
  error?: string | null;
  http_status?: number;
}

async function setActiveAssetWithRetry(
  ticker: string,
  exchange: string,
  cancelled: () => boolean,
  spawnEngineIfNotListening: boolean = false,
): Promise<SwitchRetryResult> {
  let lastMessage = "";
  for (let i = 0; i < SWITCH_MAX_ATTEMPTS; i++) {
    if (cancelled()) return { success: false, message: "cancelled" };
    if (i > 0) await new Promise((r) => setTimeout(r, SWITCH_RETRY_MS));
    try {
      const result = await invoke<{ success: boolean; message: string }>(
        "set_active_asset",
        { ticker, exchange },
      );
      lastMessage = result.message || `set_active_asset falhou (${ticker} ${exchange})`;
      if (result.success) return { success: true, message: lastMessage };
      if (
        isEngineNotListening(result.message) &&
        spawnEngineIfNotListening &&
        (i === 0 || i % RESPAWN_EVERY_ATTEMPTS === 0)
      ) {
        try {
          await invoke("spawn_engine");
        } catch {
          // engine já em execução ou falha ao spawnar
        }
        await new Promise((r) => setTimeout(r, 5000));
      }
    } catch (e) {
      lastMessage = String(e);
    }
  }
  return {
    success: false,
    message:
      lastMessage ||
      `Não foi possível ativar ${ticker} ${exchange} no engine após ${SWITCH_MAX_ATTEMPTS} tentativas.`,
  };
}

export function useTauriStartup() {
  const [status, setStatus] = useState<StartupStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [configNeeded, setConfigNeeded] = useState(false);

  useEffect(() => {
    if (!isTauri()) {
      setStatus("ready");
      return;
    }

    let cancelled = false;
    let running = false;

    const INITIAL_DELAY_MS = 5000;

    async function checkDistributorHealth(): Promise<boolean> {
      try {
        return await invoke<boolean>("check_health");
      } catch {
        return false;
      }
    }

    async function ensureDistributorHealth(
      cancelledFn: () => boolean,
    ): Promise<{ ok: boolean; error?: string }> {
      const alreadyUp = await checkDistributorHealth();
      if (alreadyUp) return { ok: true };

      let spawnError: string | null = null;
      try {
        await invoke("spawn_distributor");
      } catch (e) {
        spawnError = String(e);
      }

      const start = Date.now();
      while (Date.now() - start < DISTRIBUTOR_HEALTH_TIMEOUT_MS) {
        if (cancelledFn()) return { ok: false, error: "cancelled" };
        const healthy = await checkDistributorHealth();
        if (healthy) return { ok: true };
        await new Promise((r) => setTimeout(r, DISTRIBUTOR_HEALTH_POLL_MS));
      }
      return { ok: false, error: spawnError ?? undefined };
    }

    async function waitDistributorReadyNonFatal(cancelledFn: () => boolean): Promise<void> {
      const start = Date.now();
      while (Date.now() - start < DISTRIBUTOR_READY_TIMEOUT_MS) {
        if (cancelledFn()) return;
        try {
          const payload = await invoke<DistributorReadyPayload>("get_distributor_ready");
          if (payload.ready === true) {
            return;
          }
        } catch {
          // readiness é não fatal
        }
        await new Promise((r) => setTimeout(r, DISTRIBUTOR_READY_POLL_MS));
      }
    }

    async function ensureReady(flow: "startup" | "external-trigger") {
      if (running) return;
      running = true;
      try {
        if (flow === "startup") {
          await new Promise((r) => setTimeout(r, INITIAL_DELAY_MS));
        }
        if (cancelled) return;

        setStatus("checking");
        setError(null);

        const cfg = await invoke<{
          profit_activation_key?: string | null;
          profit_user?: string | null;
          profit_password?: string | null;
          selected_ticker?: string | null;
          selected_exchange?: string | null;
          renko_brick_points?: number | null;
          ifr_series?: string | null;
          vp_period?: string | null;
          show_volume_profile_overlay?: boolean | null;
          show_tape_intelligence_overlay?: boolean | null;
        }>("read_config");
        if (cancelled) return;

        const ticker = (cfg.selected_ticker ?? "WINFUT").trim();
        const exchange = (cfg.selected_exchange ?? "BMF").trim();
        const ifrMode = applyMarketConfigToStore(cfg);
        if (typeof cfg.show_volume_profile_overlay === "boolean") {
          useSettingsStore
            .getState()
            .setShowVolumeProfileOverlay(cfg.show_volume_profile_overlay);
        }
        if (typeof cfg.show_tape_intelligence_overlay === "boolean") {
          useSettingsStore
            .getState()
            .setShowTapeIntelligenceOverlay(cfg.show_tape_intelligence_overlay);
        }

        const keyOk = (cfg.profit_activation_key ?? "").trim().length > 0;
        const userOk = (cfg.profit_user ?? "").trim().length > 0;
        const passOk = (cfg.profit_password ?? "").length > 0;

        // Se ainda não há credenciais, não tenta subir serviços; mas mantém o app "ready" para abrir UI.
        if (!keyOk || !userOk || !passOk) {
          setStatus("ready");
          setConfigNeeded(true);
          setError(CONFIG_NEEDED_MESSAGE);
          return;
        }

        // Credenciais ok: a UI não deve mais pedir configuração.
        setConfigNeeded(false);

        setStatus("starting");
        const distributorHealth = await ensureDistributorHealth(() => cancelled);

        if (cancelled) return;

        if (!distributorHealth.ok) {
          setStatus("error");
          const detail = distributorHealth.error
            ? ` Detalhe: ${distributorHealth.error}`
            : "";
          setError(
            `Distributor não respondeu /health em até 10s. Verifique processo na porta 8000 e tente "Reiniciar serviços" nas Configurações.${detail}`,
          );
          return;
        }

        try {
          await invoke("spawn_engine");
        } catch (e) {
          console.warn("[startup] spawn_engine non-fatal:", e);
        }
        if (cancelled) return;

        if (ticker && exchange) {
          await new Promise((r) => setTimeout(r, 1000));
          if (cancelled) return;
          const active = await setActiveAssetWithRetry(
            ticker,
            exchange,
            () => cancelled,
            true,
          );
          if (cancelled) return;
          if (!active.success) {
            console.warn(
              `[startup] set_active_asset not ready yet (${ticker}/${exchange}): ${active.message}`,
            );
          }
        }
        if (!cancelled) {
          void waitDistributorReadyNonFatal(() => cancelled);
          try {
            await invoke("sync_ifr_series_to_distributor", {
              series: ifrMode,
            });
          } catch {
            // distributor pode ainda não estar pronto; usuário pode re-selecionar na barra
          }
          const vp = (cfg.vp_period ?? "day").trim().toLowerCase();
          if (vp === "day" || vp === "week" || vp === "manual") {
            try {
              await invoke("set_vp_period", { period: vp });
            } catch {
              // engine pode ainda nao escutar 5556; settings grava o mesmo periodo
            }
          }
        }
        if (!cancelled) setStatus("ready");
      } catch (e) {
        if (cancelled) return;
        setStatus("error");
        setError(String(e));
      } finally {
        running = false;
      }
    }

    const onServicesRestarted = () => {
      void ensureReady("external-trigger");
    };
    window.addEventListener("pq:services-restarted", onServicesRestarted);

    void ensureReady("startup");
    return () => {
      cancelled = true;
      window.removeEventListener("pq:services-restarted", onServicesRestarted);
    };
  }, []);

  return { status, error, configNeeded };
}
