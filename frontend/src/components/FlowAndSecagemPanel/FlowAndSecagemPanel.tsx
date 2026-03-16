import { useEffect, useDeferredValue, useState } from "react";
import type { SecagemSignal } from "../../hooks/useSecagemDetection";
import { useSecagemDetection } from "../../hooks/useSecagemDetection";
import { useMarketStore } from "../../store/marketStore";
import { FlowInversionCard } from "./FlowInversionCard";
import { SecagemSignal as SecagemSignalComponent } from "./SecagemSignal";

const SECAGEM_TICKER = "BOVA11";
const SECAGEM_ALERT_DURATION_MS = 30_000;

export function FlowAndSecagemPanel() {
  const domBuy = useMarketStore((s) => s.domBuy);
  const domSell = useMarketStore((s) => s.domSell);
  const lastPrice = useMarketStore((s) => s.lastPrice);
  const streamingTicker = useMarketStore((s) => s.streamingTicker);
  const flowInversions = useMarketStore((s) => s.flowInversions);

  const isBova11 = streamingTicker === SECAGEM_TICKER;
  const domBuyForSecagem = isBova11 ? domBuy : [];
  const domSellForSecagem = isBova11 ? domSell : [];
  const lastPriceForSecagem = isBova11 ? lastPrice : 0;

  const rawSecagem = useSecagemDetection(domBuyForSecagem, domSellForSecagem, lastPriceForSecagem);

  const [displaySignal, setDisplaySignal] = useState<SecagemSignal>(null);
  const [signalExpiresAt, setSignalExpiresAt] = useState(0);

  useEffect(() => {
    if (rawSecagem === "compra" || rawSecagem === "venda") {
      setDisplaySignal(rawSecagem);
      setSignalExpiresAt(Date.now() + SECAGEM_ALERT_DURATION_MS);
    }
  }, [rawSecagem]);

  useEffect(() => {
    const interval = setInterval(() => {
      if (signalExpiresAt > 0 && Date.now() >= signalExpiresAt) {
        setDisplaySignal(null);
        setSignalExpiresAt(0);
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [signalExpiresAt]);

  const now = Date.now();
  const showSticky = signalExpiresAt > 0 && now < signalExpiresAt;
  const displayedSignal: SecagemSignal =
    rawSecagem !== null ? rawSecagem : showSticky && displaySignal ? displaySignal : null;

  const deferredFlow = useDeferredValue(flowInversions);

  return (
    <div className="h-full flex flex-col">
      <section className="flex-[0_0_50%] flex flex-col min-h-0 border-b border-border">
        <h2 className="px-4 py-2 text-sm font-semibold text-text/80 shrink-0">
          INVERSÃO DE FLUXO
        </h2>
        <div className="flex-1 overflow-y-auto p-3 space-y-2 min-h-0">
          {deferredFlow.length === 0 ? (
            <p className="text-text/40 text-sm">Nenhuma inversão recente.</p>
          ) : (
            deferredFlow.map((f, i) => (
              <FlowInversionCard
                key={`${f.ts}-${f.agent_name}-${i}`}
                msg={f}
              />
            ))
          )}
        </div>
      </section>
      <section className="flex-[0_0_50%] flex flex-col min-h-0 p-3 border-t border-border">
        <h2 className="text-sm font-semibold text-text/80 mb-2 shrink-0">
          SECAGEM (BOVA11)
        </h2>
        <div className="flex-1 min-h-0 flex items-start">
          <SecagemSignalComponent signal={displayedSignal} />
        </div>
      </section>
    </div>
  );
}
