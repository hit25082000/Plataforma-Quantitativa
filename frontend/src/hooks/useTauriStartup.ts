import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { applyMarketConfigToStore } from "../utils/hydrateMarketFromConfig";
import { isTauri } from "../utils/tauri";

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

async function setActiveAssetWithRetry(
  ticker: string,
  exchange: string,
  cancelled: () => boolean,
  spawnEngineIfNotListening: boolean = false,
): Promise<void> {
  for (let i = 0; i < SWITCH_MAX_ATTEMPTS; i++) {
    if (cancelled()) return;
    if (i > 0) await new Promise((r) => setTimeout(r, SWITCH_RETRY_MS));
    try {
      const result = await invoke<{ success: boolean; message: string }>(
        "set_active_asset",
        { ticker, exchange },
      );
      if (result.success) return;
      if (!isEngineNotListening(result.message)) return;
      if (
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
    } catch {
      // retry
    }
  }
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
        }>("read_config");
        if (cancelled) return;

        const ticker = (cfg.selected_ticker ?? "WINFUT").trim();
        const exchange = (cfg.selected_exchange ?? "BMF").trim();
        const ifrMode = applyMarketConfigToStore(cfg);

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

        const ok = await invoke<boolean>("check_health");
        if (cancelled) return;

        let healthOk = ok;
        if (!ok) {
          setStatus("starting");
          await invoke("spawn_engine");
          if (cancelled) return;
          await invoke("spawn_distributor");
          if (cancelled) return;

          const timeout = 30000;
          const pollInterval = 500;
          const start = Date.now();
          while (Date.now() - start < timeout) {
            if (cancelled) return;
            const healthy = await invoke<boolean>("check_health");
            if (healthy) {
              healthOk = true;
              break;
            }
            await new Promise((r) => setTimeout(r, pollInterval));
          }
        }

        if (cancelled) return;

        if (!healthOk) {
          setStatus("error");
          setError(
            "Distributor não iniciou a tempo (porta 8000). Verifique se nenhum outro processo usa a porta e tente \"Reiniciar serviços\" nas Configurações.",
          );
          return;
        }

        // Mesmo quando o distributor já estava de pé, garantimos que o engine receba o ativo selecionado
        // (principalmente após "reiniciar serviços" ou salvar credenciais).
        setStatus("ready");
        if (ticker && exchange) {
          await new Promise((r) => setTimeout(r, 1000));
          if (cancelled) return;
          await setActiveAssetWithRetry(
            ticker,
            exchange,
            () => cancelled,
            true,
          );
        }
        if (!cancelled) {
          try {
            await invoke("sync_ifr_series_to_distributor", {
              series: ifrMode,
            });
          } catch {
            // distributor pode ainda não estar pronto; usuário pode re-selecionar na barra
          }
        }
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
