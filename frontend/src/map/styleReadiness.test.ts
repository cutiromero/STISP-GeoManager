import { afterEach, describe, expect, it, vi } from "vitest";
import type { Map as MapboxMap } from "mapbox-gl";
import { waitForStyleLoad } from "./mapExport";

function sourceMap() {
  const listeners = new Map<string, Set<() => void>>();
  let loaded = false;
  const map = {
    isStyleLoaded: () => loaded,
    on(event: string, callback: () => void) {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event)!.add(callback);
    },
    once(event: string, callback: () => void) {
      this.on(event, callback);
    },
    off(event: string, callback: () => void) {
      listeners.get(event)?.delete(callback);
    },
  };
  return {
    map: map as unknown as MapboxMap,
    ready: () => {
      loaded = true;
    },
    emit: (event: string) =>
      listeners.get(event)?.forEach((callback) => callback()),
    listenerCount: () =>
      [...listeners.values()].reduce((sum, set) => sum + set.size, 0),
  };
}

afterEach(() => vi.useRealTimers());

describe("source map readiness before rendering", () => {
  it("waits for initial style loading instead of reading an unfinished style", async () => {
    const source = sourceMap();
    let captured = false;
    const pending = waitForStyleLoad(source.map).then(() => {
      captured = true;
    });
    await Promise.resolve();
    expect(captured).toBe(false);
    source.emit("style.load");
    await pending;
    expect(captured).toBe(true);
    expect(source.listenerCount()).toBe(0);
  });

  it("resolves after pending sources settle even if style.load already fired", async () => {
    const source = sourceMap();
    const pending = waitForStyleLoad(source.map);
    source.ready();
    source.emit("render");
    await pending;
    expect(source.listenerCount()).toBe(0);
  });

  it("cancels waits and does not leave listeners behind", async () => {
    const source = sourceMap();
    const controller = new AbortController();
    const pending = waitForStyleLoad(source.map, 8000, controller.signal);
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(source.listenerCount()).toBe(0);
    source.ready();
    await expect(
      waitForStyleLoad(source.map, 8000, controller.signal),
    ).rejects.toMatchObject({ name: "AbortError" });
  });

  it("reports a timeout instead of leaving preview permanently busy", async () => {
    vi.useFakeTimers();
    const source = sourceMap();
    const pending = expect(waitForStyleLoad(source.map, 8000)).rejects.toThrow(
      "底图样式加载超时",
    );
    await vi.advanceTimersByTimeAsync(8000);
    await pending;
    expect(source.listenerCount()).toBe(0);
  });
});
