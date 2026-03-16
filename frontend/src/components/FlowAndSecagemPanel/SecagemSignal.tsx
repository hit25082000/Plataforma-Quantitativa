import type { SecagemSignal } from "../../hooks/useSecagemDetection";

export function SecagemSignal({ signal }: { signal: SecagemSignal }) {
  if (signal === "compra") {
    return (
      <div
        className="rounded border px-3 py-2 text-sm font-semibold"
        style={{
          borderColor: "rgb(34, 197, 94)",
          backgroundColor: "rgba(34, 197, 94, 0.15)",
          color: "rgb(34, 197, 94)",
        }}
      >
        Secagem de compra
      </div>
    );
  }
  if (signal === "venda") {
    return (
      <div
        className="rounded border px-3 py-2 text-sm font-semibold"
        style={{
          borderColor: "rgb(239, 68, 68)",
          backgroundColor: "rgba(239, 68, 68, 0.15)",
          color: "rgb(239, 68, 68)",
        }}
      >
        Secagem de venda
      </div>
    );
  }
  return (
    <p className="text-text/40 text-sm py-2">—</p>
  );
}
