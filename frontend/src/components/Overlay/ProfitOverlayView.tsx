import { useEffect, useMemo } from "react";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import { useMarketStore } from "../../store/marketStore";
import { isTauri } from "../../utils/tauri";

function lineY(price: number, originPrice: number, originY: number, pricePerPixel: number) {
  if (pricePerPixel === 0) return originY;
  return originY + (price - originPrice) / pricePerPixel;
}

type OverlayCalibrationPayload = {
  price_per_pixel: number;
  origin_price: number;
  origin_y: number;
  chart_x: number;
  chart_y: number;
  chart_width: number;
  chart_height: number;
  updated_at: string;
};

export function ProfitOverlayView() {
  const calibration = useMarketStore((s) => s.overlayCalibration);
  const ubsPrice = useMarketStore((s) => s.overlayUbsPrice);
  const avgPrice = useMarketStore((s) => s.overlayAvgPrice);

  // Esta janela tem Zustand isolado: carregar calibração do disco e ouvir eventos da janela principal.
  useEffect(() => {
    if (!isTauri()) return;
    let unLines: (() => void) | undefined;
    let unCalib: (() => void) | undefined;
    (async () => {
      try {
        const saved = (await invoke(
          "get_overlay_calibration",
        )) as OverlayCalibrationPayload | null;
        if (saved) {
          useMarketStore.setState({
            overlayCalibration: {
              pricePerPixel: saved.price_per_pixel,
              originPrice: saved.origin_price,
              originY: saved.origin_y,
              chartX: saved.chart_x,
              chartY: saved.chart_y,
              chartWidth: saved.chart_width,
              chartHeight: saved.chart_height,
              updatedAt: saved.updated_at,
            },
          });
        }
      } catch {
        // ignore
      }
      unLines = await listen("pq-overlay-lines", (e) => {
        const p = e.payload as {
          ubsPrice: number;
          avgPrice: number;
          ts: string;
        };
        useMarketStore.setState({
          overlayUbsPrice: p.ubsPrice,
          overlayAvgPrice: p.avgPrice,
          overlayLastUpdateTs: p.ts,
        });
      });
      unCalib = await listen("pq-overlay-calibration", (e) => {
        useMarketStore.setState({
          overlayCalibration: e.payload as {
            pricePerPixel: number;
            originPrice: number;
            originY: number;
            chartX: number;
            chartY: number;
            chartWidth: number;
            chartHeight: number;
            updatedAt: string;
          },
        });
      });
    })();
    return () => {
      unLines?.();
      unCalib?.();
    };
  }, []);

  const yValues = useMemo(() => {
    if (!calibration || ubsPrice == null || avgPrice == null) return null;
    return {
      ubsY: lineY(
        ubsPrice,
        calibration.originPrice,
        calibration.originY,
        calibration.pricePerPixel,
      ),
      avgY: lineY(
        avgPrice,
        calibration.originPrice,
        calibration.originY,
        calibration.pricePerPixel,
      ),
    };
  }, [calibration, ubsPrice, avgPrice]);

  return (
    <div className="h-screen w-screen relative pointer-events-none bg-transparent overflow-hidden">
      {yValues && (
        <>
          <div
            className="absolute left-0 right-0 border-t border-cyan-400/80"
            style={{ top: `${yValues.ubsY}px` }}
          />
          <div
            className="absolute left-3 -translate-y-1/2 px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300 text-xs font-mono"
            style={{ top: `${yValues.ubsY}px` }}
          >
            UBS {ubsPrice?.toFixed(1)}
          </div>

          <div
            className="absolute left-0 right-0 border-t border-amber-400/80"
            style={{ top: `${yValues.avgY}px` }}
          />
          <div
            className="absolute left-3 -translate-y-1/2 px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 text-xs font-mono"
            style={{ top: `${yValues.avgY}px` }}
          >
            Medio {avgPrice?.toFixed(1)}
          </div>
        </>
      )}
    </div>
  );
}
