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

    async function run() {
      setStatus("checking");
      setError(null);

      try {
        const ok = await invoke<boolean>("check_health");
        if (cancelled) return;

        if (ok) {
          setStatus("ready");
          return;
        }

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
