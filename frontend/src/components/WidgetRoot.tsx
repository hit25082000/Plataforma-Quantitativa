import { AlertFeed } from "./AlertFeed/AlertFeed";
import { AggressionChart } from "./AggressionPanel/AggressionChart";
import { BuyVsSellBar } from "./AggressionPanel/BuyVsSellBar";
import { IfrChart } from "./AggressionPanel/IfrChart";
import { TopBrokersTable } from "./AggressionPanel/TopBrokersTable";
import { UBSLine } from "./AggressionPanel/UBSLine";
import { FlowAndSecagemPanel } from "./FlowAndSecagemPanel/FlowAndSecagemPanel";
import { MacdChart } from "./MacdChart/MacdChart";
import { useMarketStore } from "../store/marketStore";
import { formatPrice } from "../utils/formatters";

const WIDGET_TITLES: Record<string, string> = {
  "alert-feed": "Alert Feed",
  macd: "MACD 30min",
  "flow-secagem": "Flow & Secagem",
  "buy-vs-sell": "Buy vs Sell",
  "top-brokers": "Top Brokers",
  "aggression-chart": "Aggression Chart",
  "ifr-9": "IFR 9",
  "ifr-30min": "IFR 30min",
  "ifr-18": "IFR 18",
  "ubs-line": "UBS Line",
  vwap: "VWAP",
};

interface WidgetRootProps {
  widgetId: string;
}

export function WidgetRoot({ widgetId }: WidgetRootProps) {
  const title = WIDGET_TITLES[widgetId] ?? widgetId;
  const vwap = useMarketStore((s) => s.vwap);

  const content = (() => {
    const responsive = "h-full min-h-0 w-full min-w-0";
    switch (widgetId) {
      case "alert-feed":
        return (
          <div className={responsive}>
            <AlertFeed />
          </div>
        );
      case "macd":
        return (
          <div className={responsive}>
            <MacdChart />
          </div>
        );
      case "flow-secagem":
        return (
          <div className={responsive}>
            <FlowAndSecagemPanel />
          </div>
        );
      case "buy-vs-sell":
        return (
          <div className={`${responsive} p-3`}>
            <BuyVsSellBar />
          </div>
        );
      case "top-brokers":
        return (
          <div className={responsive}>
            <TopBrokersTable />
          </div>
        );
      case "aggression-chart":
        return (
          <div className={`${responsive} p-3`}>
            <AggressionChart />
          </div>
        );
      case "ifr-9":
        return (
          <div className="h-full min-h-0 w-full flex flex-col p-3">
            <IfrChart variant="9" fillHeight />
          </div>
        );
      case "ifr-30min":
        return (
          <div className="h-full min-h-0 w-full flex flex-col p-3">
            <IfrChart variant="30min" fillHeight />
          </div>
        );
      case "ifr-18":
        return (
          <div className="h-full min-h-0 w-full flex flex-col p-3">
            <IfrChart variant="18" fillHeight />
          </div>
        );
      case "ubs-line":
        return (
          <div className="h-full min-h-0 w-full p-3">
            <UBSLine />
          </div>
        );
      case "vwap":
        return (
          <div className="h-full min-h-0 w-full p-4 flex flex-col justify-center">
            <p className="text-xs text-text/60 mb-1">Preço médio (Times & Trades)</p>
            <p className="font-mono text-lg text-text/90">
              {vwap > 0 ? formatPrice(vwap) : "—"}
            </p>
          </div>
        );
      default:
        return (
          <div className="p-4 text-text/60 text-sm">
            Widget &quot;{widgetId}&quot; não encontrado.
          </div>
        );
    }
  })();

  return (
    <div className="h-full w-full min-h-0 min-w-0 flex flex-col bg-bg text-text overflow-hidden">
      <header className="shrink-0 flex items-center justify-between gap-2 px-3 py-2 border-b border-border bg-grid">
        <span
          className="text-sm font-semibold text-text/90 flex-1 min-w-0"
          data-tauri-drag-region
        >
          {title}
        </span>
        <button
          type="button"
          onClick={async () => {
            const { getCurrentWindow } = await import("@tauri-apps/api/window");
            await getCurrentWindow().close();
          }}
          className="shrink-0 p-1.5 rounded hover:bg-border text-text/70 hover:text-text text-xs cursor-pointer select-none"
          title="Fechar"
        >
          ✕
        </button>
      </header>
      <div
        className="flex-1 min-h-0 min-w-0 overflow-auto w-full"
        data-tauri-drag-region
      >
        {content}
      </div>
    </div>
  );
}
