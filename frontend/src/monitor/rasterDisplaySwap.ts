import type { Map, RasterSourceSpecification } from "mapbox-gl";
import type { RasterRenderResult } from "../api/generated/types.gen";
import { projectUrl } from "../projects/session";
import { versionedRasterTileUrl } from "../map/rasterLayerSync";

type Layer = { source: string; layer: string; signature: string };
export function createRasterDisplaySwap(map: Map) {
  let active: Layer | undefined;
  let sequence = 0;
  let cancelPending: (() => void) | undefined;
  const remove = (value: Layer) => {
    if (!map.getStyle()) return;
    if (map.getLayer(value.layer)) map.removeLayer(value.layer);
    if (map.getSource(value.source)) map.removeSource(value.source);
  };
  const clear = () => {
    cancelPending?.();
    if (active) {
      remove(active);
      active = undefined;
    }
  };
  const show = (result: RasterRenderResult, signal: AbortSignal) => {
    cancelPending?.();
    signal.throwIfAborted();
    const signature = `${result.tileUrl}:${result.tileSampling}`;
    if (active?.signature === signature) return Promise.resolve();
    const previous = active;
    const next = previous
      ? {
          source: `product-next-${++sequence}`,
          layer: `product-raster-next-${sequence}`,
          signature,
        }
      : { source: "product", layer: "product-raster", signature };
    const opacity = result.tileSampling === "nearest" ? 1 : 0.9;
    const source: RasterSourceSpecification = {
      type: "raster",
      tiles: [
        projectUrl(versionedRasterTileUrl(result.tileUrl))
          .replace(/%7B/g, "{")
          .replace(/%7D/g, "}"),
      ],
      tileSize: 256,
      minzoom: result.minZoom,
      maxzoom: result.maxZoom,
      bounds: result.bounds4326 as [number, number, number, number],
    };
    map.addSource(next.source, source);
    map.addLayer({
      id: next.layer,
      type: "raster",
      source: next.source,
      paint: {
        "raster-opacity": previous ? 0 : opacity,
        "raster-resampling": result.tileSampling,
        "raster-fade-duration": result.tileSampling === "nearest" ? 0 : 300,
      },
    });
    if (!previous) {
      active = next;
      return Promise.resolve();
    }
    return new Promise<void>((resolve, reject) => {
      let finished = false;
      let rendered = false;
      const viewport = map.getBounds();
      let contentReady = false;
      if (viewport) {
        const [[west, south], [east, north]] = viewport.toArray();
        const [left, bottom, right, top] = result.bounds4326 as [
          number,
          number,
          number,
          number,
        ];
        const shift = 360 * Math.floor((west + 180) / 360);
        const longitudeIntersects = [-360, 0, 360].some(
          (offset) =>
            east - shift >= left + offset && west - shift <= right + offset,
        );
        contentReady = north < bottom || south > top || !longitudeIntersects;
      }
      let timer: ReturnType<typeof setTimeout>;
      const clean = () => {
        clearTimeout(timer);
        map.off("sourcedata", data);
        map.off("render", render);
        signal.removeEventListener("abort", cancel);
        if (cancelPending === cancel) cancelPending = undefined;
      };
      const cancel = () => {
        if (finished) return;
        finished = true;
        clean();
        remove(next);
        reject(new DOMException("Display update cancelled", "AbortError"));
      };
      const check = () => {
        if (
          finished ||
          !rendered ||
          !contentReady ||
          !map.isSourceLoaded(next.source)
        )
          return;
        finished = true;
        clean();
        map.setPaintProperty(next.layer, "raster-opacity", opacity);
        remove(previous);
        active = next;
        resolve();
      };
      const data = (event: {
        sourceId?: string;
        sourceDataType?: string;
        coord?: unknown;
      }) => {
        if (
          event.sourceId === next.source &&
          (event.coord ||
            event.sourceDataType === "content" ||
            event.sourceDataType === "idle")
        )
          contentReady = true;
        check();
      };
      const render = () => {
        rendered = true;
        check();
      };
      map.on("sourcedata", data);
      map.on("render", render);
      signal.addEventListener("abort", cancel, { once: true });
      cancelPending = cancel;
      timer = setTimeout(() => {
        if (finished) return;
        finished = true;
        clean();
        remove(next);
        reject(new Error("显示更新超时"));
      }, 20000);
    });
  };
  return {
    show,
    clear,
    cancel: () => cancelPending?.(),
    hasActive: () => Boolean(active),
  };
}
