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

      // #region agent log
      fetch(
        "http://127.0.0.1:7350/ingest/74027e3c-6845-4f2c-85c1-20fad01d1448",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Debug-Session-Id": "5ad9d4",
          },
          body: JSON.stringify({
            sessionId: "5ad9d4",
            location: "useTauriStartup.ts:run",
            message: "startup_run",
            data: {},
            timestamp: Date.now(),
            hypothesisId: "H2",
          }),
        },
      ).catch(() => {});
      // #endregion

      try {
        const ok = await invoke<boolean>("check_health");
        if (cancelled) return;

        // #region agent log
        fetch(
          "http://127.0.0.1:7350/ingest/74027e3c-6845-4f2c-85c1-20fad01d1448",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Debug-Session-Id": "5ad9d4",
            },
            body: JSON.stringify({
              sessionId: "5ad9d4",
              location: "useTauriStartup.ts:check_health",
              message: "check_health_initial",
              data: { ok },
              timestamp: Date.now(),
              hypothesisId: "H4",
            }),
          },
        ).catch(() => {});
        // #endregion

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

        // #region agent log
        fetch(
          "http://127.0.0.1:7350/ingest/74027e3c-6845-4f2c-85c1-20fad01d1448",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Debug-Session-Id": "5ad9d4",
            },
            body: JSON.stringify({
              sessionId: "5ad9d4",
              location: "useTauriStartup.ts:read_config",
              message: "read_config_result",
              data: {
                keyOk,
                userOk,
                passOk,
                keyLen: (cfg.profit_activation_key ?? "").length,
                userLen: (cfg.profit_user ?? "").length,
                passLen: (cfg.profit_password ?? "").length,
              },
              timestamp: Date.now(),
              hypothesisId: "H1",
            }),
          },
        ).catch(() => {});
        // #endregion

        if (!keyOk || !userOk || !passOk) {
          setStatus("ready");
          setConfigNeeded(true);
          setError(CONFIG_NEEDED_MESSAGE);
          return;
        }

        setStatus("starting");
        try {
          await invoke("spawn_engine");
        } catch (e) {
          // #region agent log
          fetch(
            "http://127.0.0.1:7350/ingest/74027e3c-6845-4f2c-85c1-20fad01d1448",
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-Debug-Session-Id": "5ad9d4",
              },
              body: JSON.stringify({
                sessionId: "5ad9d4",
                location: "useTauriStartup.ts:spawn_engine",
                message: "spawn_engine_error",
                data: { err: String(e) },
                timestamp: Date.now(),
                hypothesisId: "H2",
              }),
            },
          ).catch(() => {});
          // #endregion
          throw e;
        }
        if (cancelled) return;
        // #region agent log
        fetch(
          "http://127.0.0.1:7350/ingest/74027e3c-6845-4f2c-85c1-20fad01d1448",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Debug-Session-Id": "5ad9d4",
            },
            body: JSON.stringify({
              sessionId: "5ad9d4",
              location: "useTauriStartup.ts:spawn_engine",
              message: "spawn_engine_ok",
              data: {},
              timestamp: Date.now(),
              hypothesisId: "H2",
            }),
          },
        ).catch(() => {});
        // #endregion

        try {
          await invoke("spawn_distributor");
        } catch (e) {
          // #region agent log
          fetch(
            "http://127.0.0.1:7350/ingest/74027e3c-6845-4f2c-85c1-20fad01d1448",
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-Debug-Session-Id": "5ad9d4",
              },
              body: JSON.stringify({
                sessionId: "5ad9d4",
                location: "useTauriStartup.ts:spawn_distributor",
                message: "spawn_distributor_error",
                data: { err: String(e) },
                timestamp: Date.now(),
                hypothesisId: "H3",
              }),
            },
          ).catch(() => {});
          // #endregion
          throw e;
        }
        if (cancelled) return;
        // #region agent log
        fetch(
          "http://127.0.0.1:7350/ingest/74027e3c-6845-4f2c-85c1-20fad01d1448",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Debug-Session-Id": "5ad9d4",
            },
            body: JSON.stringify({
              sessionId: "5ad9d4",
              location: "useTauriStartup.ts:spawn_distributor",
              message: "spawn_distributor_ok",
              data: {},
              timestamp: Date.now(),
              hypothesisId: "H3",
            }),
          },
        ).catch(() => {});
        // #endregion

        const timeout = 30000;
        const pollInterval = 500;
        const start = Date.now();
        let pollCount = 0;

        while (Date.now() - start < timeout) {
          if (cancelled) return;
          const healthy = await invoke<boolean>("check_health");
          pollCount += 1;
          if (healthy) {
            // #region agent log
            fetch(
              "http://127.0.0.1:7350/ingest/74027e3c-6845-4f2c-85c1-20fad01d1448",
              {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                  "X-Debug-Session-Id": "5ad9d4",
                },
                body: JSON.stringify({
                  sessionId: "5ad9d4",
                  location: "useTauriStartup.ts:poll",
                  message: "poll_health_ready",
                  data: { pollCount, elapsed: Date.now() - start },
                  timestamp: Date.now(),
                  hypothesisId: "H4",
                }),
              },
            ).catch(() => {});
            // #endregion
            setStatus("ready");
            return;
          }
          if (pollCount === 1 || pollCount % 10 === 0) {
            // #region agent log
            fetch(
              "http://127.0.0.1:7350/ingest/74027e3c-6845-4f2c-85c1-20fad01d1448",
              {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                  "X-Debug-Session-Id": "5ad9d4",
                },
                body: JSON.stringify({
                  sessionId: "5ad9d4",
                  location: "useTauriStartup.ts:poll",
                  message: "poll_health_wait",
                  data: { pollCount, elapsed: Date.now() - start },
                  timestamp: Date.now(),
                  hypothesisId: "H4",
                }),
              },
            ).catch(() => {});
            // #endregion
          }
          await new Promise((r) => setTimeout(r, pollInterval));
        }

        if (cancelled) return;
        // #region agent log
        fetch(
          "http://127.0.0.1:7350/ingest/74027e3c-6845-4f2c-85c1-20fad01d1448",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Debug-Session-Id": "5ad9d4",
            },
            body: JSON.stringify({
              sessionId: "5ad9d4",
              location: "useTauriStartup.ts:timeout",
              message: "startup_timeout",
              data: { pollCount },
              timestamp: Date.now(),
              hypothesisId: "H4",
            }),
          },
        ).catch(() => {});
        // #endregion
        setStatus("error");
        setError("Falha ao iniciar serviços. Verifique as credenciais Profit.");
      } catch (e) {
        if (cancelled) return;
        // #region agent log
        fetch(
          "http://127.0.0.1:7350/ingest/74027e3c-6845-4f2c-85c1-20fad01d1448",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Debug-Session-Id": "5ad9d4",
            },
            body: JSON.stringify({
              sessionId: "5ad9d4",
              location: "useTauriStartup.ts:catch",
              message: "startup_error",
              data: { err: String(e) },
              timestamp: Date.now(),
              hypothesisId: "H5",
            }),
          },
        ).catch(() => {});
        // #endregion
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
