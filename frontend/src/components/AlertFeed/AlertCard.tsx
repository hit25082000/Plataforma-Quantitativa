import { useState } from "react";
import type { AlertMessage } from "../../types/messages";
import { getAlertBorderColor, getAlertPulseClass } from "../../utils/colors";
import { formatPrice, formatRelativeTime } from "../../utils/formatters";

interface AlertCardProps {
  alert: AlertMessage;
}

export function AlertCard({ alert }: AlertCardProps) {
  const [expanded, setExpanded] = useState(false);
  const borderColor = getAlertBorderColor(alert);
  const pulse = getAlertPulseClass(alert);

  const arrow = alert.direction === "buy" ? "▲" : alert.direction === "sell" ? "▼" : "—";

  return (
    <div
      className="rounded-lg border-2 p-3 cursor-pointer transition-colors"
      style={{
        borderColor,
        boxShadow: pulse ? `0 0 8px ${borderColor}40` : undefined,
        animation: pulse ? "pulse 1.5s ease-in-out infinite" : undefined,
      }}
      onClick={() => setExpanded((e) => !e)}
    >
      <div className="flex items-start gap-2">
        <span
          className="text-xs font-semibold px-1.5 py-0.5 rounded shrink-0"
          style={{ backgroundColor: `${borderColor}30`, color: borderColor }}
        >
          R{alert.rule}
        </span>
        <span className="font-medium text-text flex-1">{alert.label}</span>
      </div>
      <div className="flex items-center gap-2 mt-1 text-sm text-text/80 font-mono">
        <span>{arrow}</span>
        <span>{formatPrice(alert.price)}</span>
        <span className="text-text/50 text-xs">{formatRelativeTime(alert.ts)}</span>
      </div>
      {expanded && Object.keys(alert.data).length > 0 && (
        <pre className="mt-2 text-xs text-text/60 bg-bg/50 p-2 rounded overflow-x-auto">
          {JSON.stringify(alert.data, null, 2)}
        </pre>
      )}
    </div>
  );
}
