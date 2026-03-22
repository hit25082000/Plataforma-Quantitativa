import { useCallback, useEffect, useRef, useState } from "react";
import { distributorApiBase } from "../../config/distributorApi";
import { useMarketStore } from "../../store/marketStore";
import { formatPrice } from "../../utils/formatters";
import { isTauri } from "../../utils/tauri";

type ChatLine = { role: "user" | "assistant"; content: string };

const SIGNAL_LABEL: Record<string, string> = {
  green: "Verde — squeeze (preço > médio + Weis compradora)",
  red: "Vermelho — liquidação/estope (preço < médio + Weis vendedora)",
  neutral: "Neutro",
};

export function Agent007Panel() {
  const agent007 = useMarketStore((s) => s.agent007);
  const lastPrice = useMarketStore((s) => s.lastPrice);
  const vwap = useMarketStore((s) => s.vwap);
  const [chatLines, setChatLines] = useState<ChatLine[]>([]);
  const [input, setInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const listEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatLines]);

  const sendChat = useCallback(async () => {
    const text = input.trim();
    if (!text || chatBusy) return;
    setInput("");
    setChatError(null);
    const nextLines = [...chatLines, { role: "user" as const, content: text }];
    setChatLines(nextLines);
    setChatBusy(true);
    const base = distributorApiBase();
    const chatUrl = `${base}/api/agent007/chat`;
    const payload = nextLines.map((m) => ({ role: m.role, content: m.content }));
    try {
      if (isTauri()) {
        const { invoke } = await import("@tauri-apps/api/core");
        const data = await invoke<{
          ok: boolean;
          reply?: string;
          error?: string;
        }>("agent007_chat_invoke", { messages: payload });
        if (!data.ok) {
          setChatError(data.error ?? "Erro no chat");
          return;
        }
        setChatLines([
          ...nextLines,
          { role: "assistant", content: data.reply ?? "" },
        ]);
        return;
      }

      const res = await fetch(chatUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: payload }),
      });
      const data = (await res.json()) as { ok?: boolean; reply?: string; error?: string };
      if (!data.ok) {
        setChatError(data.error ?? "Erro no chat");
        return;
      }
      setChatLines([
        ...nextLines,
        { role: "assistant", content: data.reply ?? "" },
      ]);
    } catch {
      setChatError("Falha de rede — distributor em http://127.0.0.1:8000 ?");
    } finally {
      setChatBusy(false);
    }
  }, [chatBusy, chatLines, input]);

  const setWeis = useCallback(async (side: "buy" | "sell" | "unknown") => {
    const base = distributorApiBase();
    try {
      await fetch(`${base}/api/agent007/weis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ side }),
      });
    } catch {
      /* ignore */
    }
  }, []);

  const u = agent007?.urgency_0_100 ?? 0;
  const signal = agent007?.signal ?? "neutral";

  return (
    <div className="flex flex-col h-full min-h-0 bg-grid text-text/90">
      <div className="shrink-0 px-4 py-3 border-b border-border">
        <h2 className="font-mono text-sm font-semibold tracking-wide text-text">
          Agente 007
        </h2>
        <p className="text-[10px] text-text/50 mt-0.5">
          Sinais em tempo real (DLL → engine → WS). Chat usa snapshot sob demanda.
        </p>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-4">
        <div className="flex gap-4 items-stretch">
          <div className="flex flex-col items-center gap-1">
            <span className="text-[10px] text-text/50">Urgência</span>
            <div className="relative w-8 h-36 rounded border border-border/80 bg-bg overflow-hidden">
              <div
                className="absolute bottom-0 left-0 right-0 transition-all duration-150 rounded-b"
                style={{
                  height: `${u}%`,
                  background:
                    u < 35
                      ? "linear-gradient(to top, rgb(34 197 94 / 0.5), rgb(74 222 128 / 0.85))"
                      : u < 70
                        ? "linear-gradient(to top, rgb(234 179 8 / 0.5), rgb(250 204 21 / 0.9))"
                        : "linear-gradient(to top, rgb(220 38 38 / 0.5), rgb(248 113 113 / 0.95))",
                }}
              />
            </div>
            <span className="font-mono text-xs text-text/70">{u}</span>
          </div>

          <div className="flex-1 space-y-2 text-xs font-mono">
            <div>
              <span className="text-text/50">Sinal </span>
              <span
                className={
                  signal === "green"
                    ? "text-neon-buy"
                    : signal === "red"
                      ? "text-neon-sell"
                      : "text-text/70"
                }
              >
                {SIGNAL_LABEL[signal] ?? signal}
              </span>
            </div>
            <div className="text-text/70">
              <span className="text-text/50">Weis (proxy) </span>
              {agent007?.weis_side ?? "—"} ·{" "}
              <span className="text-text/50">vs médio </span>
              {agent007?.price_vs_vwap ?? "—"}
            </div>
            <div className="text-text/70">
              <span className="text-text/50">Preço </span>
              {lastPrice > 0 ? formatPrice(lastPrice) : "—"}
              <span className="text-text/50"> · VWAP </span>
              {vwap > 0 ? formatPrice(vwap) : "—"}
            </div>
            <div
              className={
                agent007?.entry_buy_valid === false
                  ? "text-amber-400/90"
                  : "text-text/60"
              }
            >
              {agent007?.entry_buy_valid === false
                ? agent007.entry_filter_reason ?? "Entrada compra inválida"
                : "Filtro compra: OK"}
            </div>
          </div>
        </div>

        {agent007?.weis_mode === "manual" && (
          <div className="flex flex-wrap gap-2">
            <span className="text-[10px] text-text/50 w-full">Weis manual</span>
            <button
              type="button"
              onClick={() => void setWeis("buy")}
              className="px-2 py-1 rounded text-[10px] bg-neon-buy/20 text-neon-buy border border-neon-buy/40"
            >
              Compra
            </button>
            <button
              type="button"
              onClick={() => void setWeis("sell")}
              className="px-2 py-1 rounded text-[10px] bg-neon-sell/20 text-neon-sell border border-neon-sell/40"
            >
              Venda
            </button>
            <button
              type="button"
              onClick={() => void setWeis("unknown")}
              className="px-2 py-1 rounded text-[10px] bg-border/50 text-text/70"
            >
              Limpar
            </button>
          </div>
        )}

        {agent007 && agent007.alerts.length > 0 && (
          <div>
            <p className="text-[10px] text-text/50 mb-1">Alertas recentes</p>
            <ul className="space-y-1 font-mono text-[10px] text-text/80">
              {agent007.alerts
                .slice(-4)
                .reverse()
                .map((a, i) => (
                  <li key={`${a.ts}-${i}`} className="border-l-2 border-amber-500/50 pl-2">
                    {a.text}
                  </li>
                ))}
            </ul>
          </div>
        )}

        {!agent007 && (
          <p className="text-xs text-text/50">
            Aguardando trades do ativo para o Agente 007…
          </p>
        )}
      </div>

      <div className="shrink-0 border-t border-border p-3 flex flex-col gap-2 min-h-[180px] max-h-[45vh]">
        <p className="text-[10px] text-text/50">Conversa</p>
        <div className="flex-1 min-h-[72px] max-h-[28vh] overflow-y-auto rounded border border-border/60 p-2 space-y-2 bg-bg/50">
          {chatLines.length === 0 && (
            <p className="text-[10px] text-text/40">
              Pergunte sobre o contexto atual (ex.: “Resuma o sinal e o filtro de entrada”).
            </p>
          )}
          {chatLines.map((line, i) => (
            <div
              key={i}
              className={
                line.role === "user"
                  ? "text-[11px] text-text/85 pl-2 border-l-2 border-text/30"
                  : "text-[11px] text-text/70 pl-2 border-l-2 border-neon-buy/40"
              }
            >
              <span className="text-text/40">{line.role === "user" ? "Você" : "007"}: </span>
              {line.content}
            </div>
          ))}
          <div ref={listEndRef} />
        </div>
        {chatError && (
          <p className="text-[10px] text-amber-400/90">{chatError}</p>
        )}
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void sendChat();
            }}
            placeholder="Mensagem…"
            className="flex-1 min-w-0 px-2 py-1.5 rounded bg-bg border border-border text-xs font-mono text-text placeholder:text-text/35"
            disabled={chatBusy}
          />
          <button
            type="button"
            onClick={() => void sendChat()}
            disabled={chatBusy || !input.trim()}
            className="shrink-0 px-3 py-1.5 rounded bg-text/15 hover:bg-text/25 text-xs font-mono disabled:opacity-40"
          >
            {chatBusy ? "…" : "Enviar"}
          </button>
        </div>
      </div>
    </div>
  );
}
