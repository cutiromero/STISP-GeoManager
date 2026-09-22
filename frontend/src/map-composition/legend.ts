import type { LoadedLayerGroup } from "../types";
import { isGraduatedRenderer, isUniqueValueRenderer } from "../symbolization";

export interface CompositionLegendItem {
  id: string;
  label: string;
  color: string;
  shape: "point" | "line" | "polygon" | "raster";
}

export function compositionLegendItems(
  groups: LoadedLayerGroup[],
): CompositionLegendItem[] {
  const items: CompositionLegendItem[] = [];
  for (const group of groups) {
    if (!group.visible) continue;
    for (const layer of group.children) {
      if (!layer.visible) continue;
      if (layer.layerType === "raster") {
        if (layer.symbolization.mode === "unique") {
          for (const entry of layer.symbolization.uniqueValues) {
            items.push({
              id: `${layer.id}-raster-${entry.value}`,
              label: `${layer.name} · ${entry.label || entry.value}`,
              color: entry.color,
              shape: "raster",
            });
          }
        } else {
          items.push({
            id: layer.id,
            label: layer.name,
            color: rasterPaletteColor(layer.symbolization.palette),
            shape: "raster",
          });
        }
        continue;
      }
      const renderer = layer.symbolization.renderer;
      if (renderer && isUniqueValueRenderer(renderer)) {
        for (const entry of renderer.classes.filter((item) => item.visible)) {
          items.push({
            id: `${layer.id}-${entry.id}`,
            label: `${layer.name} · ${entry.label}`,
            color: entry.color,
            shape: geometryShape(layer.geometryType),
          });
        }
        continue;
      }
      if (renderer && isGraduatedRenderer(renderer)) {
        for (const entry of renderer.classes.filter((item) => item.visible)) {
          items.push({
            id: `${layer.id}-${entry.id}`,
            label: `${layer.name} · ${entry.label}`,
            color: entry.color,
            shape: geometryShape(layer.geometryType),
          });
        }
        continue;
      }
      items.push({
        id: layer.id,
        label: layer.name,
        color: singleLayerColor(layer),
        shape: geometryShape(layer.geometryType),
      });
    }
  }
  return items.slice(0, 40);
}

function singleLayerColor(layer: LoadedLayerGroup["children"][number]): string {
  if (layer.layerType === "raster") {
    return rasterPaletteColor(layer.symbolization.palette);
  }
  const geometry = layer.geometryType.toLowerCase();
  if (geometry.includes("line")) return layer.symbolization.line.lineColor;
  if (geometry.includes("polygon")) return layer.symbolization.fill.fillColor;
  return layer.symbolization.pointMode === "symbol"
    ? layer.symbolization.symbol.iconColor
    : layer.symbolization.circle.circleColor;
}

function geometryShape(geometryType: string): CompositionLegendItem["shape"] {
  const normalized = geometryType.toLowerCase();
  if (normalized.includes("line")) return "line";
  if (normalized.includes("polygon")) return "polygon";
  return "point";
}

function rasterPaletteColor(palette: string) {
  const colors: Record<string, string> = {
    poplar: "#2f7d62",
    viridis: "#3b528b",
    terrain: "#8a9a5b",
    thermal: "#f97316",
  };
  return colors[palette] ?? "#64748b";
}
