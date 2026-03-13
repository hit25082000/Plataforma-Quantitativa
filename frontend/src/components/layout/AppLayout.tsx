import { StatusBar } from "./StatusBar";
import { AlertFeed } from "../AlertFeed/AlertFeed";
import { OrderBookHeatmap } from "../OrderBookHeatmap/OrderBookHeatmap";
import { AggressionPanel } from "../AggressionPanel/AggressionPanel";

interface AppLayoutProps {
  onOpenSettings?: () => void;
}

export function AppLayout({ onOpenSettings }: AppLayoutProps) {
  return (
    <div className="h-screen flex flex-col bg-bg">
      <StatusBar onOpenSettings={onOpenSettings} />
      <div className="flex-1 grid grid-cols-3 gap-px bg-border overflow-hidden">
        <div className="bg-grid overflow-hidden">
          <AlertFeed />
        </div>
        <div className="bg-grid overflow-hidden">
          <OrderBookHeatmap />
        </div>
        <div className="bg-grid overflow-hidden">
          <AggressionPanel />
        </div>
      </div>
    </div>
  );
}
