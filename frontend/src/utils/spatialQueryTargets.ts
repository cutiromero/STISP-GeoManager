import type {
  LoadedLayer,
  LoadedVectorLayer,
  ResourceListItem,
} from "../types";

export function isQueryableLoadedLayer(
  layer: LoadedLayer,
): layer is LoadedVectorLayer {
  return (
    layer.layerType === "vector" &&
    layer.sourceResource.dataType === "vector" &&
    layer.sourceResource.id > 0 &&
    layer.sourceResource.isQueryable
  );
}

export function loadedQueryResources(
  layers: LoadedLayer[],
): ResourceListItem[] {
  const resources = new Map<number, ResourceListItem>();
  for (const layer of layers) {
    if (isQueryableLoadedLayer(layer))
      resources.set(layer.sourceResource.id, layer.sourceResource);
  }
  return [...resources.values()];
}
