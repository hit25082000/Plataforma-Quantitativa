import { useEffect, useRef } from "react";
import { useMarketStore } from "../store/marketStore";
import { useSettingsStore } from "../store/settingsStore";
import { isTauri } from "../utils/tauri";
import type { AlertMessage } from "../types/messages";

const ALERT_COOLDOWN_MS = 30 * 1000;

function getAlertCooldownKey(alert: AlertMessage): string {
  return `${alert.ticker}|${alert.rule}|${alert.direction}`;
}

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
  const lastNotifiedByKeyRef = useRef<Map<string, number>>(new Map());
  const notificationsEnabled = useSettingsStore((s) => s.notificationsEnabled);
  const soundsEnabled = useSettingsStore((s) => s.soundsEnabled);
  const volume = useSettingsStore((s) => s.volume) / 100;

  useEffect(() => {
    if (alerts.length <= prevLenRef.current) return;
    const newAlert = alerts[0];
    prevLenRef.current = alerts.length;

    const key = getAlertCooldownKey(newAlert);
    const now = Date.now();
    const last = lastNotifiedByKeyRef.current.get(key);
    if (last != null && now - last < ALERT_COOLDOWN_MS) return;

    lastNotifiedByKeyRef.current.set(key, now);
    const toDelete: string[] = [];
    for (const [k, t] of lastNotifiedByKeyRef.current.entries()) {
      if (now - t > 60000) toDelete.push(k);
    }
    toDelete.forEach((k) => lastNotifiedByKeyRef.current.delete(k));

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
