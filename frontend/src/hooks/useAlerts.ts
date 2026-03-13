import { useEffect, useRef } from "react";
import { useMarketStore } from "../store/marketStore";
import { useSettingsStore } from "../store/settingsStore";
import { isTauri } from "../utils/tauri";
import type { AlertMessage } from "../types/messages";

function getNotificationTitle(alert: AlertMessage): string {
  if (alert.rule === 5 && alert.conviction === "high") return "Alta Convicção";
  if (alert.rule === 2) return "Muralha Detectada";
  if (alert.rule === 3) return "VWAP";
  if (alert.rule === 6) return "Absorção Institucional";
  if (alert.rule === 1) return "Agressão";
  return `R${alert.rule}`;
}

function getNotificationBody(alert: AlertMessage): string {
  const dir = alert.direction === "buy" ? "▲" : alert.direction === "sell" ? "▼" : "—";
  return `${alert.ticker} ${dir} ${alert.label}`;
}

function getSoundForAlert(alert: AlertMessage): "wall" | "breakout" {
  if (alert.rule === 2) return "wall";
  if (alert.rule === 5 && alert.conviction === "high") return "breakout";
  if (alert.conviction === "medium" || alert.conviction === "high") return "breakout";
  return "wall";
}

export function useAlerts() {
  const alerts = useMarketStore((s) => s.alerts);
  const prevLenRef = useRef(0);
  const notificationsEnabled = useSettingsStore((s) => s.notificationsEnabled);
  const soundsEnabled = useSettingsStore((s) => s.soundsEnabled);
  const volume = useSettingsStore((s) => s.volume) / 100;

  useEffect(() => {
    if (alerts.length <= prevLenRef.current) return;
    const newAlert = alerts[0];
    prevLenRef.current = alerts.length;

    if (notificationsEnabled) {
      if (isTauri()) {
        import("@tauri-apps/plugin-notification").then(({ requestPermission, sendNotification, isPermissionGranted }) => {
          isPermissionGranted().then((granted) => {
            if (granted) {
              sendNotification({
                title: getNotificationTitle(newAlert),
                body: getNotificationBody(newAlert),
              });
            } else {
              requestPermission().then((perm) => {
                if (perm === "granted") {
                  sendNotification({
                    title: getNotificationTitle(newAlert),
                    body: getNotificationBody(newAlert),
                  });
                }
              });
            }
          });
        });
      } else if ("Notification" in window) {
        Notification.requestPermission().then((perm) => {
          if (perm === "granted") {
            new Notification(getNotificationTitle(newAlert), {
              body: getNotificationBody(newAlert),
            });
          }
        });
      }
    }

    if (soundsEnabled && isTauri()) {
      const sound = getSoundForAlert(newAlert);
      const filename = sound === "wall" ? "wall.wav" : "breakout.wav";
      import("@tauri-apps/api/core").then(({ invoke, convertFileSrc }) => {
        invoke<string>("get_resource_path", { name: `sounds/${filename}` }).then((path) => {
          const url = convertFileSrc(path);
          const audio = new Audio(url);
          audio.volume = volume;
          audio.play().catch(() => {});
        });
      });
    } else if (soundsEnabled && !isTauri()) {
      const sound = getSoundForAlert(newAlert);
      const url = sound === "wall" ? "/sounds/wall.wav" : "/sounds/breakout.wav";
      const audio = new Audio(url);
      audio.volume = volume;
      audio.play().catch(() => {});
    }
  }, [alerts, notificationsEnabled, soundsEnabled, volume]);
}
