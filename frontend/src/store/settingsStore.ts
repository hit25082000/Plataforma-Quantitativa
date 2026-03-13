import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface AppSettings {
  notificationsEnabled: boolean;
  soundsEnabled: boolean;
  volume: number;
  minimizeToTray: boolean;
  startWithWindows: boolean;
}

const defaultSettings: AppSettings = {
  notificationsEnabled: true,
  soundsEnabled: true,
  volume: 80,
  minimizeToTray: true,
  startWithWindows: false,
};

interface SettingsStore extends AppSettings {
  setNotificationsEnabled: (v: boolean) => void;
  setSoundsEnabled: (v: boolean) => void;
  setVolume: (v: number) => void;
  setMinimizeToTray: (v: boolean) => void;
  setStartWithWindows: (v: boolean) => void;
}

export const useSettingsStore = create<SettingsStore>()(
  persist(
    (set) => ({
      ...defaultSettings,
      setNotificationsEnabled: (v) => set({ notificationsEnabled: v }),
      setSoundsEnabled: (v) => set({ soundsEnabled: v }),
      setVolume: (v) => set({ volume: Math.max(0, Math.min(100, v)) }),
      setMinimizeToTray: (v) => set({ minimizeToTray: v }),
      setStartWithWindows: (v) => set({ startWithWindows: v }),
    }),
    { name: "plataforma-settings" }
  )
);
