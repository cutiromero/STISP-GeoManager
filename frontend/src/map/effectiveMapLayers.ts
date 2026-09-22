import type { LoadedLayer, LoadedLayerGroup } from "../types";

export function effectiveMapLayers(groups: LoadedLayerGroup[]): LoadedLayer[] {
  return groups.flatMap((group) =>
    group.children.map(
      (layer) =>
        ({
          ...layer,
          visible: group.visible && layer.visible,
          symbolization: {
            ...layer.symbolization,
            opacity: Math.round(
              (layer.symbolization.opacity * group.symbolization.opacity) / 100,
            ),
          },
        }) as LoadedLayer,
    ),
  );
}
