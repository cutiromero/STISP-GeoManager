import {
  type GeoJSONSource,
  LngLatBounds,
  type Map as MapboxMap,
} from "mapbox-gl";
import type {
  FeatureInfo,
  LoadedLayer,
  LoadedRasterLayer,
  LoadedVectorLayer,
} from "../types";
import {
  boundsFromImageCoordinates,
  combinedFeatureBounds,
  sourceIdFor,
} from "../utils/geometry";
import { syncVectorInteractions } from "./featureInteraction";
import { getMapState } from "./mapState";
import { fitBoundsOptions, rasterFitBoundsOptions } from "./mapViewport";
import { addRasterLayer } from "./rasterLayerSync";
import { registerPlatformSymbolImages } from "./symbolImages";
import {
  addLoadedStyleLayers,
  removeLoadedLayerGroup,
  reorderLoadedStyleLayers,
  setLoadedLayerGroupVisibility,
} from "./vectorLayerSync";
import {
  vectorGeojsonSourceOptions,
  vectorSourceKey,
} from "./vectorSourceOptions";

export function syncLoadedLayers(
  map: MapboxMap,
  layers: LoadedLayer[],
  onFeatureSelect?: (feature: FeatureInfo | null) => void,
  options: { fitNewLayers?: boolean } = {},
) {
  registerPlatformSymbolImages(map);
  const renderableVectorLayers = layers.filter(
    (layer): layer is LoadedVectorLayer =>
      layer.layerType === "vector" && "geojson" in layer,
  );
  const renderableRasterLayers = layers.filter(
    (layer): layer is LoadedRasterLayer =>
      layer.layerType === "raster" && Boolean(layer.tileUrl),
  );
  const activeIds = new Set([
    ...renderableVectorLayers.map((layer) => sourceIdFor(layer.id)),
    ...renderableRasterLayers.map((layer) => sourceIdFor(layer.id)),
  ]);

  const state = getMapState(map);
  for (const sourceId of state.loadedSourceIds) {
    if (!activeIds.has(sourceId)) {
      removeLoadedLayerGroup(map, sourceId);
      state.sourceDataRefs.delete(sourceId);
    }
  }

  const newVectorBounds: LngLatBounds[] = [];
  for (const layer of renderableVectorLayers) {
    const sourceId = sourceIdFor(layer.id);
    if (!layer.visible && !map.getSource(sourceId)) {
      continue;
    }
    const isNew = !map.getSource(sourceId);
    const nextSourceKey = vectorSourceKey(layer);
    if (!isNew && state.vectorSourceKeys.get(sourceId) !== nextSourceKey) {
      removeLoadedLayerGroup(map, sourceId);
      state.sourceDataRefs.delete(sourceId);
    }
    const shouldCreateSource = !map.getSource(sourceId);
    if (shouldCreateSource) {
      map.addSource(sourceId, vectorGeojsonSourceOptions(layer));
      state.vectorSourceKeys.set(sourceId, nextSourceKey);
      state.sourceDataRefs.set(sourceId, layer.geojson);
      if (layer.visible) {
        const bounds = combinedFeatureBounds([layer.geojson]);
        if (bounds) newVectorBounds.push(bounds);
      }
    } else if (state.sourceDataRefs.get(sourceId) !== layer.geojson) {
      (map.getSource(sourceId) as GeoJSONSource).setData(
        layer.geojson as never,
      );
      state.sourceDataRefs.set(sourceId, layer.geojson);
    }
    addLoadedStyleLayers(map, sourceId, layer);
    setLoadedLayerGroupVisibility(map, sourceId, layer.visible);
  }

  const newRasterBounds: LngLatBounds[] = [];
  for (const layer of renderableRasterLayers) {
    const sourceId = sourceIdFor(layer.id);
    if (!layer.visible && !map.getSource(sourceId)) {
      continue;
    }
    const isNew = !map.getSource(sourceId);
    if (isNew && layer.visible && layer.imageCoordinates) {
      const bounds = boundsFromImageCoordinates(layer.imageCoordinates);
      if (bounds) newRasterBounds.push(bounds);
    }
    addRasterLayer(map, sourceId, layer);
    setLoadedLayerGroupVisibility(map, sourceId, layer.visible);
  }

  const allNewBounds = [...newVectorBounds, ...newRasterBounds];
  if (allNewBounds.length > 0 && options.fitNewLayers !== false) {
    const firstBound = allNewBounds[0];
    if (!firstBound) return;
    const combined = allNewBounds.reduce(
      (bounds, next) => bounds.extend(next),
      new LngLatBounds(firstBound.getSouthWest(), firstBound.getNorthEast()),
    );
    map.fitBounds(
      combined,
      newRasterBounds.length > 0
        ? rasterFitBoundsOptions(80)
        : fitBoundsOptions(80),
    );
  }

  reorderLoadedStyleLayers(map, [
    ...renderableVectorLayers,
    ...renderableRasterLayers,
  ]);
  syncVectorInteractions(
    map,
    renderableVectorLayers.filter((layer) => layer.visible),
    onFeatureSelect,
  );
  state.loadedSourceIds = activeIds;
}
