import type { Map as MapboxMap, MapLayerMouseEvent } from "mapbox-gl";
import type { FeatureInfo, LoadedVectorLayer } from "../types";
import { sourceIdFor } from "../utils/geometry";
import { clearFeatureState, featureStateTarget, getMapState } from "./mapState";

type FeatureWithProperties = {
  properties?: Record<string, unknown> | null;
};

export function syncVectorInteractions(
  map: MapboxMap,
  layers: LoadedVectorLayer[],
  onFeatureSelect?: (feature: FeatureInfo | null) => void,
) {
  const activeLayerIds = new Set<string>();
  const layerBySourceId = new Map(
    layers.map((layer) => [sourceIdFor(layer.id), layer]),
  );
  for (const layer of layers) {
    const sourceId = sourceIdFor(layer.id);
    for (const styleLayerId of [
      `${sourceId}-fill`,
      `${sourceId}-line`,
      `${sourceId}-point`,
      `${sourceId}-symbol`,
    ]) {
      if (map.getLayer(styleLayerId)) {
        activeLayerIds.add(styleLayerId);
        getMapState(map).interactiveContexts.set(styleLayerId, {
          layerBySourceId,
          onFeatureSelect: onFeatureSelect as
            | ((feature: unknown) => void)
            | undefined,
        });
        addVectorInteraction(
          map,
          styleLayerId,
          layerBySourceId,
          onFeatureSelect,
        );
      }
    }
  }
  const handlers = getMapState(map).interactiveHandlers;
  for (const layerId of handlers.keys()) {
    if (!activeLayerIds.has(layerId)) removeVectorInteraction(map, layerId);
  }
}

function addVectorInteraction(
  map: MapboxMap,
  layerId: string,
  layerBySourceId: Map<string, LoadedVectorLayer>,
  onFeatureSelect?: (feature: FeatureInfo | null) => void,
) {
  const handlers = getMapState(map).interactiveHandlers;
  if (handlers.has(layerId)) {
    return;
  }

  const click = (event: MapLayerMouseEvent) => {
    const feature = event.features?.[0];
    if (!feature) return;
    event.preventDefault();
    const target = featureStateTarget(feature);
    const state = getMapState(map);
    const selected = state.selectedFeature;
    if (
      target &&
      selected &&
      selected.source === target.source &&
      selected.id === target.id
    ) {
      clearFeatureState(map, "selectedFeature", "selected");
      onFeatureSelect?.(null);
      return;
    }
    clearFeatureState(map, "selectedFeature", "selected");
    if (target) {
      map.setFeatureState(target, { selected: true });
      state.selectedFeature = target;
    }
    const sourceId = String(feature.source ?? "");
    const context = getMapState(map).interactiveContexts.get(layerId);
    const currentLayerBySourceId =
      (context?.layerBySourceId as
        | Map<string, LoadedVectorLayer>
        | undefined) ?? layerBySourceId;
    const currentOnFeatureSelect =
      (context?.onFeatureSelect as
        | ((feature: FeatureInfo | null) => void)
        | undefined) ?? onFeatureSelect;
    const layer = currentLayerBySourceId.get(sourceId);
    currentOnFeatureSelect?.(
      layer
        ? {
            layerId: layer.id,
            layerName: layer.name,
            properties: (feature as FeatureWithProperties).properties ?? {},
          }
        : null,
    );
  };

  const mousemove = (event: MapLayerMouseEvent) => {
    const feature = event.features?.[0];
    const canvas = map.getCanvas();
    if (canvas.dataset.drawing !== "true") {
      canvas.style.cursor = feature ? "pointer" : "";
    }
    const target = feature ? featureStateTarget(feature) : null;
    const state = getMapState(map);
    const current = state.hoveredFeature;
    if (
      current &&
      (!target || current.source !== target.source || current.id !== target.id)
    ) {
      map.setFeatureState(current, { highlight: false });
      state.hoveredFeature = undefined;
    }
    if (
      target &&
      (!current || current.source !== target.source || current.id !== target.id)
    ) {
      map.setFeatureState(target, { highlight: true });
      state.hoveredFeature = target;
    }
  };

  const mouseleave = () => {
    const canvas = map.getCanvas();
    if (canvas.dataset.drawing !== "true") {
      canvas.style.cursor = "";
    }
    clearFeatureState(map, "hoveredFeature", "highlight");
  };

  map.on("click", layerId, click);
  map.on("mousemove", layerId, mousemove);
  map.on("mouseleave", layerId, mouseleave);
  handlers.set(layerId, { click, mousemove, mouseleave });
}

export function removeVectorInteraction(map: MapboxMap, layerId: string) {
  const handlers = getMapState(map).interactiveHandlers;
  const handler = handlers.get(layerId);
  if (!handler) return;
  if (handler.click) {
    map.off("click", layerId, handler.click);
  }
  map.off("mousemove", layerId, handler.mousemove);
  map.off("mouseleave", layerId, handler.mouseleave);
  handlers.delete(layerId);
  getMapState(map).interactiveContexts.delete(layerId);
}
