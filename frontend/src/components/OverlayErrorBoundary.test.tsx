/** @vitest-environment jsdom */
import { createRoot } from "react-dom/client";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OverlayErrorBoundary, PQ_LAST_OVERLAY_RENDER_ERROR_KEY } from "./OverlayErrorBoundary";

function ThrowOnce(): JSX.Element {
  throw new Error("boom");
}

describe("OverlayErrorBoundary", () => {
  const err = console.error;
  afterEach(() => {
    console.error = err;
    localStorage.removeItem(PQ_LAST_OVERLAY_RENDER_ERROR_KEY);
    delete (window as Window & { __PQ_LAST_OVERLAY_RENDER_ERROR__?: unknown }).__PQ_LAST_OVERLAY_RENDER_ERROR__;
  });

  it("shows error message, safe-mode subtitle, persists payload and logs crash", () => {
    console.error = vi.fn();
    (window as Window & { __PQ_OVERLAY_CONTEXT__?: { overlay_status?: string } }).__PQ_OVERLAY_CONTEXT__ =
      { overlay_status: "ok" };

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    expect(() =>
      act(() => {
        root.render(
          <OverlayErrorBoundary>
            <ThrowOnce />
          </OverlayErrorBoundary>,
        );
      }),
    ).not.toThrow();

    expect(container.textContent).toContain("boom");
    expect(container.textContent).toContain("Overlay em modo seguro");

    const raw = localStorage.getItem(PQ_LAST_OVERLAY_RENDER_ERROR_KEY);
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw as string) as {
      message: string;
      stack: string;
      componentStack: string;
      context: unknown;
    };
    expect(parsed.message).toBe("boom");
    expect(typeof parsed.stack).toBe("string");
    expect(parsed.componentStack).toBeTruthy();
    expect(parsed.context).toEqual({ overlay_status: "ok" });

    expect(
      (window as Window & { __PQ_LAST_OVERLAY_RENDER_ERROR__?: { message: string } }).__PQ_LAST_OVERLAY_RENDER_ERROR__,
    ).toMatchObject({ message: "boom" });

    const crashCalls = vi.mocked(console.error).mock.calls.filter((c) => c[0] === "[overlay] React render crash");
    expect(crashCalls.length).toBeGreaterThanOrEqual(1);
    const args = crashCalls[crashCalls.length - 1]!;
    expect(args[1]).toMatchObject({
      message: "boom",
      stack: expect.any(String),
      componentStack: expect.any(String),
      context: { overlay_status: "ok" },
    });

    act(() => root.unmount());
    container.remove();
  });
});
