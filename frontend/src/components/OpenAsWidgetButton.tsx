import { invoke } from "@tauri-apps/api/core";
import { isTauri } from "../utils/tauri";

interface OpenAsWidgetButtonProps {
  widgetId: string;
  title?: string;
  className?: string;
}

export function OpenAsWidgetButton({
  widgetId,
  title = "Abrir em janela",
  className = "shrink-0 p-1.5 rounded hover:bg-border text-text/50 hover:text-text/80 text-xs",
}: OpenAsWidgetButtonProps) {
  if (!isTauri()) return null;

  const openWidget = () => {
    invoke("create_widget_window", { widgetId }).catch((e) =>
      console.error("create_widget_window:", e)
    );
  };

  return (
    <button
      type="button"
      onClick={openWidget}
      className={className}
      title={title}
      aria-label={title}
    >
      ⊡
    </button>
  );
}
