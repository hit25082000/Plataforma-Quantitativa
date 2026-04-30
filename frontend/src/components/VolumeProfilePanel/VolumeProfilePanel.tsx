import { useMemo } from "react";
import { useMarketStore } from "../../store/marketStore";
import { formatPrice } from "../../utils/formatters";

function formatVolume(value: number): string {
  return value.toLocaleString("pt-BR");
}

export function VolumeProfilePanel() {
  const profile = useMarketStore((s) => s.volumeProfile);
  const vpOverlay = useMarketStore((s) => s.vpOverlay);

  const levels = useMemo(() => {
    if (profile) return [...profile.levels].sort((a, b) => b.total_vol - a.total_vol);
    if (vpOverlay) return [...vpOverlay.levels].sort((a, b) => b.total_vol - a.total_vol);
    return [];
  }, [profile, vpOverlay]);

  const topLevel = levels[0];
  const fallbackActive = !profile && Boolean(vpOverlay);
  const pocValue = profile?.poc ?? vpOverlay?.poc?.price ?? 0;
  const vahValue = profile?.vah ?? vpOverlay?.vah?.price ?? 0;
  const valValue = profile?.val ?? vpOverlay?.val?.price ?? 0;
  const totalValue = profile?.total_vol ?? vpOverlay?.levels?.reduce((acc, lvl) => acc + (lvl.total_vol ?? 0), 0) ?? 0;

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-2 text-sm font-semibold text-text/80 border-b border-border shrink-0 flex items-center justify-between gap-2">
        <span>VOLUME PROFILE SATO</span>
        {profile ? (
          <span className="text-[11px] font-mono text-text/50 uppercase">{profile.period}</span>
        ) : fallbackActive ? (
          <span className="text-[11px] font-mono text-amber-300 uppercase">fallback vp_overlay</span>
        ) : null}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {!profile && !vpOverlay ? (
          <div className="rounded border border-dashed border-border/60 bg-bg/40 px-3 py-4 text-sm text-text/50">
            Aguardando snapshots do Volume Profile.
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
              <MetricCard label="POC" value={formatPrice(pocValue)} tone="orange" />
              <MetricCard label="VAH" value={formatPrice(vahValue)} tone="cyan" />
              <MetricCard label="VAL" value={formatPrice(valValue)} tone="rose" />
              <MetricCard label="Total" value={formatVolume(totalValue)} tone="slate" />
            </div>

            <div className="rounded border border-border/60 bg-bg/40 p-3">
              <div className="flex items-center justify-between gap-2 mb-3">
                <div className="text-[11px] uppercase tracking-[0.16em] text-text/50">
                  Níveis mais fortes
                </div>
                {topLevel ? (
                  <div className="text-[11px] font-mono text-text/50">
                    Topo {formatPrice(topLevel.price)}
                  </div>
                ) : fallbackActive ? (
                  <div className="text-[11px] font-mono text-text/50">Overlay ativo</div>
                ) : null}
              </div>

              <div className="space-y-2">
                {levels.slice(0, 12).map((level) => {
                  const isPoc = level.price === pocValue;
                  const isVah = level.price === vahValue;
                  const isVal = level.price === valValue;
                  const tone = isPoc
                    ? "bg-orange-400"
                    : isVah
                      ? "bg-cyan-400"
                      : isVal
                        ? "bg-rose-400"
                        : "bg-white/70";
                  const pct = Number.isFinite(level.pct_of_max) ? level.pct_of_max : 0;
                  return (
                    <div key={level.price} className="space-y-1">
                      <div className="flex items-center justify-between gap-3 text-[11px] font-mono">
                        <span className="text-text/70">{formatPrice(level.price)}</span>
                        <span className="text-text/45">
                          {formatVolume(level.total_vol)} | B {formatVolume(level.bid_vol)} | A {formatVolume(level.ask_vol)}
                        </span>
                      </div>
                      <div className="h-2 rounded bg-white/5 overflow-hidden">
                        <div
                          className={`h-full ${tone} transition-[width] duration-300 ease-out`}
                          style={{ width: `${Math.max(2, Math.min(100, Math.round(pct * 100)))}%` }}
                        />
                      </div>
                      {isPoc || isVah || isVal ? (
                        <div className="flex gap-1 text-[10px] font-mono uppercase tracking-[0.12em]">
                          {isPoc ? <span className="text-orange-300">POC</span> : null}
                          {isVah ? <span className="text-cyan-300">VAH</span> : null}
                          {isVal ? <span className="text-rose-300">VAL</span> : null}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
                {levels.length === 0 && fallbackActive ? (
                  <div className="rounded border border-dashed border-border/60 bg-bg/30 px-3 py-3 text-xs text-text/60">
                    Snapshot do overlay ativo, aguardando consolidação completa do Volume Profile.
                  </div>
                ) : null}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "orange" | "cyan" | "rose" | "slate";
}) {
  const toneClass =
    tone === "orange"
      ? "text-orange-300 border-orange-500/30 bg-orange-500/10"
      : tone === "cyan"
        ? "text-cyan-300 border-cyan-500/30 bg-cyan-500/10"
        : tone === "rose"
          ? "text-rose-300 border-rose-500/30 bg-rose-500/10"
          : "text-text/70 border-border/60 bg-white/5";
  return (
    <div className={`rounded border px-3 py-2 ${toneClass}`}>
      <div className="text-[10px] uppercase tracking-[0.16em] opacity-75">{label}</div>
      <div className="mt-1 text-sm font-semibold">{value}</div>
    </div>
  );
}
