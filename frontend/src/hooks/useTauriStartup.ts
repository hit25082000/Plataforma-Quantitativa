import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useMarketStore } from "../store/marketStore";
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
  const m = message.toLowerCase();
  return (
    m.includes("5556") ||
    m.includes("timed out") ||
    m.includes("connection refused") ||
    m.includes("escutando")
  );
}

const SWITCH_RETRY_MS = 2000;
const SWITCH_MAX_ATTEMPTS = 15;

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
      if (spawnEngineIfNotListening && i === 0) {
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
      const label = useMarketStore.getState().selectedTicker;
      const [ticker, exchange] = label.includes(" · ")
        ? label.split(" · ").map((s) => s.trim())
        : ["WINFUT", "BMF"];
      let cleanup: (() => void) | undefined;
      if (ticker && exchange) {
        let cancelled = false;
        const retryMs = 2000;
        const maxAttempts = 15;
        (async () => {
          for (let i = 0; i < maxAttempts; i++) {
            if (cancelled) return;
            if (i > 0) await new Promise((r) => setTimeout(r, retryMs));
            try {
              const res = await fetch("/api/set-active-asset", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ ticker, exchange }),
              });
              const body = (await res.json().catch(() => ({}))) as { success?: boolean; message?: string };
              if (cancelled) return;
              if (body?.success) return;
              const msg = (body?.message ?? "").toLowerCase();
              if (!(msg.includes("5556") || msg.includes("timed out") || msg.includes("connection refused") || msg.includes("escutando") || msg.includes("respondeu"))) return;
            } catch {
              // retry
            }
          }
        })();
        cleanup = () => {
          cancelled = true;
        };
      }
      return cleanup;
    }

    let cancelled = false;

    const INITIAL_DELAY_MS = 5000;

    async function run() {
      await new Promise((r) => setTimeout(r, INITIAL_DELAY_MS));
      if (cancelled) return;

      setStatus("checking");
      setError(null);

      try {
        const ok = await invoke<boolean>("check_health");
        if (cancelled) return;

        const cfg = await invoke<{
          profit_activation_key?: string | null;
          profit_user?: string | null;
          profit_password?: string | null;
          selected_ticker?: string | null;
          selected_exchange?: string | null;
        }>("read_config");
        if (cancelled) return;

        const ticker = (cfg.selected_ticker ?? "WINFUT").trim();
        const exchange = (cfg.selected_exchange ?? "BMF").trim();
        if (ticker && exchange) {
          useMarketStore
            .getState()
            .setSelectedTicker(`${ticker} · ${exchange}`);
        }

        if (ok) {
          setStatus("ready");
          if (ticker && exchange) {
            await setActiveAssetWithRetry(ticker, exchange, () => cancelled, true);
          }
          return;
        }

        const keyOk = (cfg.profit_activation_key ?? "").trim().length > 0;
        const userOk = (cfg.profit_user ?? "").trim().length > 0;
        const passOk = (cfg.profit_password ?? "").length > 0;

        if (!keyOk || !userOk || !passOk) {
          setStatus("ready");
          setConfigNeeded(true);
          setError(CONFIG_NEEDED_MESSAGE);
          return;
        }

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
            setStatus("ready");
            if (ticker && exchange) {
              await new Promise((r) => setTimeout(r, 1500));
              if (cancelled) return;
              await setActiveAssetWithRetry(ticker, exchange, () => cancelled, true);
            }
            return;
          }
          await new Promise((r) => setTimeout(r, pollInterval));
        }

        if (cancelled) return;
        setStatus("error");
        setError("Falha ao iniciar serviços. Verifique as credenciais Profit.");
      } catch (e) {
        if (cancelled) return;
        setStatus("error");
        setError(String(e));
      }
    }

    run();
    return () => {
      cancelled = true;
    };
  }, []);

  return { status, error, configNeeded };
}
