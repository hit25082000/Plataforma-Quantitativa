import { useMarketStore } from "../../store/marketStore";
import { AggressionPanel } from "../AggressionPanel/AggressionPanel";
import { AlertFeed } from "../AlertFeed/AlertFeed";
import { MacdChart } from "../MacdChart/MacdChart";
import { FlowAndSecagemPanel } from "../FlowAndSecagemPanel/FlowAndSecagemPanel";
import { SyncPanel } from "../SyncPanel/SyncPanel";
import { StatusBar } from "./StatusBar";

interface AppLayoutProps {
  onOpenSettings?: () => void;
}

export function AppLayout({ onOpenSettings }: AppLayoutProps) {
  const inSync = useMarketStore((s) => s.inSync);

  return (
    <div
      className={`h-screen flex flex-col bg-bg ${!inSync ? "bg-[#1a1a1a]" : ""}`}
    >
      <StatusBar onOpenSettings={onOpenSettings} />
      <SyncPanel />
      <div className="flex-1 grid grid-cols-3 gap-px bg-border overflow-hidden">
        <div className="bg-grid overflow-hidden flex flex-col">
          <AlertFeed />
          <div className="border-t border-border shrink-0" style={{ minHeight: "80px" }}>
            <MacdChart />
          </div>
        </div>
        <div className="bg-grid overflow-hidden">
          <FlowAndSecagemPanel />
        </div>
        <div className="bg-grid overflow-hidden">
          <AggressionPanel />
        </div>
      </div>
    </div>
  );
}
