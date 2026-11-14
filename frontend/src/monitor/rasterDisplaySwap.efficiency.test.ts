import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Map as MapboxMap } from "mapbox-gl";
import type { RasterRenderResult } from "../api/generated/types.gen";
import { createRasterDisplaySwap } from "./rasterDisplaySwap";

function map() {
  const sources = new Set<string>();
  const layers = new Map<string, { paint: Record<string, unknown> }>();
  const events = new Map<
    string,
    Set<(event?: { sourceId?: string; sourceDataType?: string }) => void>
  >();
  let loaded = false;
  const value = {
    getStyle: () => ({ version: 8, sources: {}, layers: [] }),
    getBounds: () => ({ intersects: () => true }),
    getLayer: (id: string) => layers.get(id),
    getSource: (id: string) => sources.has(id),
    addSource: vi.fn((id: string) => sources.add(id)),
    addLayer: vi.fn((layer: { id: string; paint: Record<string, unknown> }) =>
      layers.set(layer.id, layer),
    ),
    removeLayer: vi.fn((id: string) => layers.delete(id)),
    removeSource: vi.fn((id: string) => sources.delete(id)),
    setPaintProperty: vi.fn((id: string, key: string, value: unknown) => {
      layers.get(id)!.paint[key] = value;
    }),
    isSourceLoaded: vi.fn(() => loaded),
    on: (
      name: string,
      callback: (event?: {
        sourceId?: string;
        sourceDataType?: string;
      }) => void,
    ) => {
      if (!events.has(name)) events.set(name, new Set());
      events.get(name)!.add(callback);
    },
    off: (
      name: string,
      callback: (event?: {
        sourceId?: string;
        sourceDataType?: string;
      }) => void,
    ) => events.get(name)?.delete(callback),
  };
  return {
    value: value as unknown as MapboxMap,
    api: value,
    sources,
    layers,
    ready: () => {
      loaded = true;
      events
        .get("sourcedata")
        ?.forEach((callback) =>
          callback({ sourceId: "product-next-1", sourceDataType: "content" }),
        );
    },
    render: () => events.get("render")?.forEach((callback) => callback()),
  };
}
const result = (style: string) =>
  ({
    datasetId: 1,
    tileUrl: `/api/raster/tiles/1/${style}/{z}/{x}/{y}.png`,
    tileSampling: "nearest",
    minZoom: 0,
    maxZoom: 16,
    bounds4326: [1, 2, 3, 4],
  }) as RasterRenderResult;
beforeEach(() =>
  vi.stubGlobal("window", { location: { origin: "http://localhost" } }),
);
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("retains the displayed raster until replacement tiles are ready and a frame has rendered", async () => {
  const m = map();
  const display = createRasterDisplaySwap(m.value);
  await display.show(result("all"), new AbortController().signal);
  const pending = display.show(
    result("hide-road"),
    new AbortController().signal,
  );
  expect(m.layers.has("product-raster")).toBe(true);
  expect(m.layers.get("product-raster-next-1")!.paint["raster-opacity"]).toBe(
    0,
  );
  m.ready();
  expect(m.layers.has("product-raster")).toBe(true);
  m.render();
  await pending;
  expect(m.layers.has("product-raster")).toBe(false);
  expect(m.layers.get("product-raster-next-1")!.paint["raster-opacity"]).toBe(
    1,
  );
  expect(m.sources.size).toBe(1);
  expect(m.api.addSource.mock.calls[1]?.[0]).toBe("product-next-1");
});
it("cancels an outdated style update without clearing the current classification", async () => {
  const m = map();
  const display = createRasterDisplaySwap(m.value);
  await display.show(result("all"), new AbortController().signal);
  const controller = new AbortController();
  const pending = display.show(result("old"), controller.signal);
  const rejected = expect(pending).rejects.toMatchObject({
    name: "AbortError",
  });
  controller.abort();
  await rejected;
  expect(m.layers.has("product-raster")).toBe(true);
  expect(m.sources.size).toBe(1);
});
it("retains the current map after a replacement times out", async () => {
  vi.useFakeTimers();
  const m = map();
  const display = createRasterDisplaySwap(m.value);
  await display.show(result("all"), new AbortController().signal);
  const failed = expect(
    display.show(result("missing"), new AbortController().signal),
  ).rejects.toThrow("显示更新超时");
  await vi.advanceTimersByTimeAsync(20000);
  await failed;
  expect(m.layers.has("product-raster")).toBe(true);
  expect(m.sources.size).toBe(1);
});

it("restores the current combination without creating another raster source", async () => {
  const m=map(); const display=createRasterDisplaySwap(m.value);
  await display.show(result('all'),new AbortController().signal);
  const stale=display.show(result('hidden'),new AbortController().signal);
  const cancelled=expect(stale).rejects.toMatchObject({name:'AbortError'});
  await display.show(result('all'),new AbortController().signal);
  await cancelled;
  expect(m.api.addSource).toHaveBeenCalledTimes(2);
  expect(m.sources.size).toBe(1);
  expect(m.layers.has('product-raster')).toBe(true);
});
