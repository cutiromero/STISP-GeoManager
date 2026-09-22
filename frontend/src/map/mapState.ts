import type {
  MapboxGeoJSONFeature,
  Map as MapboxMap,
  MapLayerMouseEvent,
  Popup,
} from "mapbox-gl";

export interface FeatureStateTarget {
  source: string;
  id: string | number;
}

interface VectorInteractionHandlers {
  click?: (event: MapLayerMouseEvent) => void;
  mousemove: (event: MapLayerMouseEvent) => void;
  mouseleave: () => void;
}

export interface VectorInteractionContext {
  layerBySourceId: Map<string, unknown>;
  onFeatureSelect?: (feature: unknown) => void;
}

export interface MapInternalState {
  interactiveHandlers: Map<string, VectorInteractionHandlers>;
  interactiveContexts: Map<string, VectorInteractionContext>;
  hoveredFeature: FeatureStateTarget | undefined;
  selectedFeature: FeatureStateTarget | undefined;
  popup: Popup | undefined;
  loadedSourceIds: Set<string>;
  sourceDataRefs: Map<string, unknown>;
  vectorSourceKeys: Map<string, string>;
  rasterSourceKeys: Map<string, string>;
}

const mapStates = new WeakMap<MapboxMap, MapInternalState>();

export function getMapState(map: MapboxMap): MapInternalState {
  let state = mapStates.get(map);
  if (!state) {
    state = {
      interactiveHandlers: new Map(),
      interactiveContexts: new Map(),
      hoveredFeature: undefined,
      selectedFeature: undefined,
      popup: undefined,
      loadedSourceIds: new Set(),
      sourceDataRefs: new Map(),
      vectorSourceKeys: new Map(),
      rasterSourceKeys: new Map(),
    };
    mapStates.set(map, state);
  }
  return state;
}

export function clearFeatureState(
  map: MapboxMap,
  key: "hoveredFeature" | "selectedFeature",
  stateName: string,
) {
  const state = getMapState(map);
  const target = state[key];
  if (!target || !map.getSource(target.source)) {
    state[key] = undefined;
    return;
  }
  map.setFeatureState(target, { [stateName]: false });
  state[key] = undefined;
}

export function featureStateTarget(
  feature: MapboxGeoJSONFeature,
): FeatureStateTarget | null {
  const targetFeature = feature as MapboxGeoJSONFeature & {
    id?: string | number;
    source?: string;
  };
  if (targetFeature.id === undefined || !targetFeature.source) return null;
  return { source: targetFeature.source, id: targetFeature.id };
}
