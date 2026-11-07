import mapboxgl, {
  type Map as MapboxMap,
  type MapLayerMouseEvent,
} from "mapbox-gl";
import { summaryEntries } from "./featureFields";
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
      `${sourceId}-excluded-line`,
      `${sourceId}-point`,
      `${sourceId}-symbol`,
      `${sourceId}-cluster`,
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
    if (
      (feature as FeatureWithProperties).properties?.point_count &&
      layerId.endsWith("-cluster")
    ) {
      map.easeTo({
        center: event.lngLat,
        zoom: Math.min(20, map.getZoom() + 2),
      });
      return;
    }
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
      closeFeaturePopup(map);
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
    const clickedLayer = currentLayerBySourceId.get(sourceId);
    if (clickedLayer)
      showFeaturePopup(
        map,
        layerId,
        event.lngLat,
        clickedLayer.name,
        (feature as FeatureWithProperties).properties ?? {},
      );
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
  if (popups.get(map)?.layerId === layerId) closeFeaturePopup(map);
}

const popups = new WeakMap<
  MapboxMap,
  { popup: mapboxgl.Popup; layerId: string }
>();

function closeFeaturePopup(map: MapboxMap) {
  popups.get(map)?.popup.remove();
  popups.delete(map);
}

/** A short summary where the user clicked; full attributes stay in the side panel. */
function showFeaturePopup(
  map: MapboxMap,
  layerId: string,
  lngLat: mapboxgl.LngLat,
  layerName: string,
  properties: Record<string, unknown>,
) {
  closeFeaturePopup(map);
  const body = document.createElement("div");
  body.className = "feature-click-popup";
  const title = document.createElement("strong");
  title.textContent = layerName;
  body.append(title);
  const list = document.createElement("dl");
  for (const [label, value] of summaryEntries(properties)) {
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = value;
    list.append(term, detail);
  }
  body.append(list);
  const hint = document.createElement("small");
  hint.textContent = "完整属性见右侧面板";
  body.append(hint);
  const popup = new mapboxgl.Popup({
    closeButton: true,
    closeOnClick: false,
    maxWidth: "280px",
    offset: 8,
  })
    .setLngLat(lngLat)
    .setDOMContent(body)
    .addTo(map);
  popups.set(map, { popup, layerId });
}
