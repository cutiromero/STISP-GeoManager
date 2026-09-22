import type { Map as MapboxMap, RasterSourceSpecification } from "mapbox-gl";
import type { LoadedRasterLayer } from "../types";
import {
  boundsFromImageCoordinates,
  clamp,
  rasterSourceKey,
} from "../utils/geometry";
import { getMapState } from "./mapState";
import { upsertLayer } from "./styleHelpers";
import { removeLoadedLayerGroup } from "./vectorLayerSync";

export const rasterTileRendererVersion = 4;

export function versionedRasterTileUrl(tileUrl: string) {
  const fragmentIndex = tileUrl.indexOf("#");
  const url = fragmentIndex >= 0 ? tileUrl.slice(0, fragmentIndex) : tileUrl;
  const fragment = fragmentIndex >= 0 ? tileUrl.slice(fragmentIndex + 1) : null;
  const versioned = /([?&])rv=[^&#]*/.test(url)
    ? url.replace(/([?&])rv=[^&#]*/, `$1rv=${rasterTileRendererVersion}`)
    : `${url}${url.includes("?") ? "&" : "?"}rv=${rasterTileRendererVersion}`;
  return fragment === null ? versioned : `${versioned}#${fragment}`;
}

export function addRasterLayer(
  map: MapboxMap,
  sourceId: string,
  layer: LoadedRasterLayer,
) {
  const style = layer.symbolization;
  const layerId = `${sourceId}-raster`;
  const tileUrl = layer.tileUrl
    ? versionedRasterTileUrl(layer.tileUrl)
    : undefined;
  const key = rasterSourceKey({ ...layer, tileUrl });
  const state = getMapState(map);

  if (
    !map.getSource(sourceId) ||
    state.rasterSourceKeys.get(sourceId) !== key
  ) {
    removeLoadedLayerGroup(map, sourceId);
    if (tileUrl) {
      const bounds = layer.imageCoordinates
        ? boundsFromImageCoordinates(layer.imageCoordinates)
        : null;
      map.addSource(sourceId, {
        type: "raster",
        tiles: [tileUrl],
        tileSize: 256,
        ...(typeof layer.tileMinZoom === "number"
          ? { minzoom: clamp(Math.floor(layer.tileMinZoom), 0, 22) }
          : {}),
        ...(typeof layer.tileMaxZoom === "number"
          ? { maxzoom: clamp(Math.ceil(layer.tileMaxZoom), 0, 22) }
          : {}),
        ...(bounds
          ? {
              bounds: [
                bounds.getWest(),
                bounds.getSouth(),
                bounds.getEast(),
                bounds.getNorth(),
              ],
            }
          : {}),
      } as RasterSourceSpecification);
    }
    state.rasterSourceKeys.set(sourceId, key);
  }
  if (!map.getSource(sourceId)) return;
  const categorical =
    layer.tileSampling === "nearest" ||
    layer.rasterKind === "categorical" ||
    style.mode === "unique";
  upsertLayer(map, {
    id: layerId,
    type: "raster",
    source: sourceId,
    paint: {
      "raster-opacity": clamp(style.opacity / 100, 0, 1),
      "raster-resampling": categorical ? "nearest" : "linear",
      // Cross-fading neighboring zoom levels blends class colors even when
      // texture sampling itself uses nearest-neighbor.
      "raster-fade-duration": categorical ? 0 : 300,
    },
  });
}
