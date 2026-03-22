import { isTauri } from "../utils/tauri";

/** Base URL do distributor (HTTP). Browser dev: proxy relativo. Tauri: localhost. */
export function distributorApiBase(): string {
  if (typeof window === "undefined") return "";
  if (isTauri()) return "http://127.0.0.1:8000";
  return "";
}
