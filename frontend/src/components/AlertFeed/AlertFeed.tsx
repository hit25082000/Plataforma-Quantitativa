import { useDeferredValue } from "react";
import { useMarketStore } from "../../store/marketStore";
import { AlertCard } from "./AlertCard";

export function AlertFeed() {
  const alerts = useMarketStore((s) => s.alerts);
  const deferredAlerts = useDeferredValue(alerts);

  return (
    <div className="h-full flex flex-col">
      <h2 className="px-4 py-2 text-sm font-semibold text-text/80 border-b border-border shrink-0">
        ALERT FEED
      </h2>
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {deferredAlerts.length === 0 ? (
          <p className="text-text/40 text-sm text-center py-8">Aguardando alertas...</p>
        ) : (
          deferredAlerts.map((a, i) => (
            <AlertCard key={`${a.ts}-${a.rule}-${i}`} alert={a} />
          ))
        )}
      </div>
    </div>
  );
}
