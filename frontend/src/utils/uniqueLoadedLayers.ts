import type { LoadedLayerGroup, LoadedVectorLayer } from "../types";

interface ResourceLayerIdentity {
  layerType: "vector" | "raster";
  sourceResource: { id: number };
  query?: LoadedVectorLayer["query"];
}

export function resourceLayerKey(layer: ResourceLayerIdentity): string {
  const query = layer.layerType === "vector" ? layer.query : undefined;
  if (!query || (!query.attributeFilters.length && !query.spatialFilter)) {
    return `resource:${layer.sourceResource.id}`;
  }
  // A spatial/attribute query is a derived result, not another copy of its
  // complete source. Keep different results and collapse identical queries.
  return `query:${layer.sourceResource.id}:${stableJson(query)}`;
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

export function findLoadedResourceLayer(
  groups: LoadedLayerGroup[],
  key: string,
) {
  for (const group of groups) {
    const layer = group.children.find(
      (candidate) => resourceLayerKey(candidate) === key,
    );
    if (layer) return { group, layer };
  }
  return null;
}

export function uniqueLoadedLayerGroups(
  groups: LoadedLayerGroup[],
  seen = new Set<string>(),
): LoadedLayerGroup[] {
  let changed = false;
  const next: LoadedLayerGroup[] = [];
  for (const group of groups) {
    const children = group.children.filter((layer) => {
      const key = resourceLayerKey(layer);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    if (children.length === group.children.length) {
      next.push(group);
    } else {
      changed = true;
      if (children.length || group.isManual) next.push({ ...group, children });
    }
  }
  return changed ? next : groups;
}
