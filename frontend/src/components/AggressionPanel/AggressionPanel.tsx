import type { ReactNode } from "react";
import { useMarketStore } from "../../store/marketStore";
import { formatPrice } from "../../utils/formatters";
import { OpenAsWidgetButton } from "../OpenAsWidgetButton";
import { IfrChart } from "./IfrChart";
import { TopBrokersTable } from "./TopBrokersTable";
import { UBSLine } from "./UBSLine";

function AggressionSection({
  title,
  widgetId,
  children,
}: {
  title: string;
  widgetId: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded border border-border/50 bg-bg/50 px-3 py-2">
      <div className="flex items-center justify-between gap-2 mb-2">
        <h3 className="text-xs font-semibold text-text/60">{title}</h3>
        <OpenAsWidgetButton
          widgetId={widgetId}
          title={`Abrir ${title} em janela`}
          className="shrink-0 p-1 rounded hover:bg-border text-text/50 hover:text-text/80 text-xs"
        />
      </div>
      {children}
    </section>
  );
}

export function AggressionPanel() {
  const vwap = useMarketStore((s) => s.vwap);

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-2 text-sm font-semibold text-text/80 border-b border-border shrink-0 flex items-center justify-between gap-2">
        <span>AGGRESSION PANEL</span>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        <AggressionSection title="Top Brokers" widgetId="top-brokers">
          <TopBrokersTable />
        </AggressionSection>

        <AggressionSection title="IFR 9" widgetId="ifr-9">
          <IfrChart variant="9" />
        </AggressionSection>

        <AggressionSection title="IFR 30" widgetId="ifr-30">
          <IfrChart variant="30" />
        </AggressionSection>

        <AggressionSection title="IFR 18" widgetId="ifr-18">
          <IfrChart variant="18" />
        </AggressionSection>

        <AggressionSection title="UBS Line" widgetId="ubs-line">
          <UBSLine />
        </AggressionSection>

        <AggressionSection title="VWAP" widgetId="vwap">
          <div className="mb-2">
            <p className="text-[10px] text-text/50">Preço médio (Times & Trades — 1ª linha)</p>
          </div>
          <p className="font-mono text-sm text-text/90">
            {vwap > 0 ? formatPrice(vwap) : "—"}
          </p>
        </AggressionSection>
      </div>
    </div>
  );
}
