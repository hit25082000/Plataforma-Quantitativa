import type { FlowInversionMessage } from "../../types/messages";

export function FlowInversionCard({ msg }: { msg: FlowInversionMessage }) {
  const flipped = msg.previous_delta > 0 && msg.current_delta < 0;
  const color = flipped ? "rgb(239, 68, 68)" : "rgb(34, 197, 94)";
  return (
    <div
      className="rounded border px-2 py-1.5 text-xs"
      style={{ borderColor: color, backgroundColor: `${color}15` }}
    >
      <span className="font-semibold" style={{ color }}>
        {msg.agent_name}
      </span>{" "}
      inversão {msg.previous_delta} → {msg.current_delta}
    </div>
  );
}
