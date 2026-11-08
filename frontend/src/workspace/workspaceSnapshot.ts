import type {
  LoadedLayer,
  LoadedLayerGroup,
  LoadedVectorLayer,
  MapViewState,
  SavedWorkspaceLayer,
  SavedWorkspaceLayerGroup,
  WorkspaceSceneSnapshot,
} from "../types";

export function workspaceSnapshot(
  groups: LoadedLayerGroup[],
  selectedLayerId: string | null,
  mapView: MapViewState | null,
  basemapId?: string,
): WorkspaceSceneSnapshot {
  return {
    version: 2,
    ...(basemapId ? { basemapId } : {}),
    groups: groups.map(toSavedWorkspaceGroup),
    selectedLayerId,
    mapView,
    savedAt: new Date().toISOString(),
  };
}

export function toSavedWorkspaceGroup(
  group: LoadedLayerGroup,
): SavedWorkspaceLayerGroup {
  return {
    ...group,
    children: group.children.map(toSavedWorkspaceLayer),
  };
}

export function toSavedWorkspaceLayer(layer: LoadedLayer): SavedWorkspaceLayer {
  const base = {
    id: layer.id,
    name: layer.name,
    layerType: layer.layerType,
    sourceResource: layer.sourceResource,
    geometryType: layer.geometryType,
    visible: layer.visible,
    summary: layer.summary,
    metadata: layer.metadata,
    symbolization: layer.symbolization,
    fields: layer.fields,
  };
  if (layer.layerType === "vector") {
    return {
      ...base,
      layerType: "vector",
      query: layer.query ?? {
        attributeFilters: [],
        spatialFilter: null,
      },
    };
  }
  return {
    ...base,
    layerType: "raster",
    tileUrl: layer.tileUrl,
    tileMinZoom: layer.tileMinZoom,
    tileMaxZoom: layer.tileMaxZoom,
    tileSampling: layer.tileSampling,
    imageCoordinates: layer.imageCoordinates,
    rasterDatasetId: layer.rasterDatasetId,
    rasterLayerId: layer.rasterLayerId,
    rasterRulesMode: layer.rasterRulesMode,
    rasterKind: layer.rasterKind,
    rasterMetadata: layer.rasterMetadata,
    renderStatus: layer.renderStatus,
    renderProgress: layer.renderProgress,
    renderMessages: layer.renderMessages,
  };
}

export function isLoadedVectorLayer(
  layer: SavedWorkspaceLayer | LoadedLayer,
): layer is LoadedVectorLayer {
  return (
    layer.layerType === "vector" &&
    "geojson" in layer &&
    typeof layer.geojson === "object" &&
    layer.geojson !== null
  );
}
