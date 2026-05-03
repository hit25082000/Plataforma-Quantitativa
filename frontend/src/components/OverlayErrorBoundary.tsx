import { Component, type ErrorInfo, type ReactNode } from "react";

export const PQ_LAST_OVERLAY_RENDER_ERROR_KEY = "PQ_LAST_OVERLAY_RENDER_ERROR";

type Props = { children: ReactNode };

type State = {
  hasError: boolean;
  errorMessage: string;
  errorStack: string;
  componentStack: string;
};

function readOverlayContextSnapshot(): unknown {
  if (typeof window === "undefined") return null;
  return (window as Window & { __PQ_OVERLAY_CONTEXT__?: unknown }).__PQ_OVERLAY_CONTEXT__ ?? null;
}

export class OverlayErrorBoundary extends Component<Props, State> {
  state: State = {
    hasError: false,
    errorMessage: "",
    errorStack: "",
    componentStack: "",
  };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    const errorMessage = error instanceof Error ? error.message : String(error);
    return { hasError: true, errorMessage };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    const err = error instanceof Error ? error : new Error(String(error));
    const message = err.message;
    const stack = err.stack ?? "";
    const componentStack = info.componentStack ?? "";
    const context = readOverlayContextSnapshot();
    const payload = {
      ts: Date.now(),
      message,
      stack,
      componentStack,
      context,
    };
    try {
      localStorage.setItem(PQ_LAST_OVERLAY_RENDER_ERROR_KEY, JSON.stringify(payload));
    } catch {
      // ignore quota / private mode
    }
    if (typeof window !== "undefined") {
      (window as Window & { __PQ_LAST_OVERLAY_RENDER_ERROR__?: typeof payload }).__PQ_LAST_OVERLAY_RENDER_ERROR__ =
        payload;
    }
    console.error("[overlay] React render crash", {
      message,
      stack,
      componentStack,
      context,
    });
    this.setState({ errorStack: stack, componentStack });
  }

  render(): ReactNode {
    if (this.state.hasError) {
      const line1 = this.state.errorMessage || "erro desconhecido";
      return (
        <div
          className="overlay-root"
          style={{
            position: "fixed",
            inset: 0,
            pointerEvents: "none",
            background: "transparent",
            backgroundColor: "transparent",
            overflow: "hidden",
            zIndex: 2147483000,
          }}
        >
          <div
            style={{
              position: "absolute",
              bottom: 8,
              left: 8,
              display: "flex",
              flexDirection: "column",
              gap: 2,
              maxWidth: "min(92vw, 720px)",
              padding: "4px 8px",
              borderRadius: 4,
              fontSize: 11,
              fontFamily: "'JetBrains Mono', monospace",
              background: "rgba(15,23,42,0.55)",
              color: "rgba(248,250,252,0.92)",
              border: "1px solid rgba(148,163,184,0.35)",
            }}
            title={`${line1}\n${this.state.errorStack}`.slice(0, 8000)}
          >
            <div
              style={{
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {line1}
            </div>
            <div style={{ fontSize: 9, color: "rgba(148,163,184,0.9)", whiteSpace: "nowrap" }}>
              Overlay em modo seguro
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
