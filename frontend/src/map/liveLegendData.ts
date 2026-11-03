import { isGraduatedRenderer, isUniqueValueRenderer } from "../symbolization";
import type { LoadedLayer } from "../types";

export interface LiveLegendEntry {
  id: string;
  label: string;
  color: string;
  shape: "point" | "line" | "polygon" | "raster";
}
export interface LiveLayerLegend {
  id: string;
  title: string;
  opacity: number;
  entries: LiveLegendEntry[];
  gradient?: { colors: string[]; low: string; high: string };
  note?: string;
  updating: boolean;
}

// Matches the palettes used by the raster renderer; these colors describe the
// returned rendered tiles and are never used to recolor raster pixels locally.
const palettes: Record<string, string[]> = {
  poplar: ["#183f39", "#5f9360", "#e8ba5e"],
  viridis: ["#440154", "#31688e", "#35b779", "#fde725"],
  terrain: ["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#8c510a"],
  thermal: ["#23344c", "#c45c46", "#f6cd70"],
};

// Numeric codes read in order; names sort as Chinese readers expect.
function legendOrder<T>(items: T[], key: (item: T) => string): T[] {
  const numeric = items.every((item) => Number.isFinite(Number(key(item))));
  return [...items].sort((left, right) =>
    numeric
      ? Number(key(left)) - Number(key(right))
      : key(left).localeCompare(key(right), "zh-CN", { numeric: true }),
  );
}

export function workbenchLegends(
  layers: LoadedLayer[],
  english = false,
): LiveLayerLegend[] {
  return layers
    .filter(
      (layer) =>
        layer.visible &&
        layer.symbolization.opacity > 0 &&
        (layer.layerType !== "raster" || Boolean(layer.tileUrl)),
    )
    .map((layer): LiveLayerLegend => {
      const base: LiveLayerLegend = {
        id: layer.id,
        title: layer.name,
        opacity: layer.symbolization.opacity / 100,
        entries: [],
        updating: false,
      };
      if (layer.layerType === "raster") {
        const style = layer.symbolization;
        base.updating = ["pending", "queued", "running"].includes(
          layer.renderStatus ?? "",
        );
        if (style.mode === "unique") {
          base.entries = legendOrder(style.uniqueValues, (item) =>
            String(item.value),
          ).map((item) => ({
            id: String(item.value),
            color: item.color,
            label: item.label || String(item.value),
            shape: "raster",
          }));
          if (base.entries.length === 0)
            base.note = english
              ? "No category legend was returned"
              : "当前渲染未提供分类图例";
        } else if (style.mode === "rgb") {
          base.note = `RGB ${english ? "composite" : "合成"}  R: ${style.bands[0] ?? "—"}  G: ${style.bands[1] ?? "—"}  B: ${style.bands[2] ?? "—"}`;
        } else {
          const band = style.bands[0] ?? 1;
          const range = style.stretch.perBand[String(band)];
          const hasRange =
            range &&
            Number.isFinite(range.min) &&
            Number.isFinite(range.max) &&
            range.max > range.min;
          base.gradient = {
            colors:
              style.mode === "gray"
                ? ["#000000", "#ffffff"]
                : (palettes[style.palette] ?? palettes.viridis!),
            low: hasRange ? String(range.min) : english ? "Low" : "低",
            high: hasRange ? String(range.max) : english ? "High" : "高",
          };
          base.note = english
            ? `Band ${band}${hasRange ? "" : " / rendered stretch"}`
            : `第 ${band} 波段${hasRange ? "" : " / 当前拉伸色带"}`;
        }
        return base;
      }
      const style = layer.symbolization;
      const geometry = layer.geometryType.toLowerCase();
      const shape = geometry.includes("line")
        ? "line"
        : geometry.includes("polygon")
          ? "polygon"
          : "point";
      const renderer = style.renderer;
      if (
        renderer &&
        (isUniqueValueRenderer(renderer) || isGraduatedRenderer(renderer))
      ) {
        // Graduated classes keep their range order; the default class stays last.
        const classes = isUniqueValueRenderer(renderer)
          ? legendOrder(renderer.classes, (item) => item.label)
          : renderer.classes;
        base.entries = [...classes, renderer.defaultClass]
          .filter((item) => item.visible)
          .map((item) => ({
            id: item.id,
            label: item.label,
            color: item.color,
            shape,
          }));
        base.note = `${english ? "Field" : "分类字段"}: ${renderer.field}`;
      } else if (shape === "point" && style.pointMode === "heatmap") {
        const colors = style.heatmap.heatmapColor.filter(
          (value): value is string =>
            typeof value === "string" && /^(#|rgb|hsl)/.test(value),
        );
        if (colors.length >= 2)
          base.gradient = {
            colors,
            low: english ? "Low density" : "低密度",
            high: english ? "High density" : "高密度",
          };
      } else {
        const color =
          shape === "line"
            ? style.line.lineColor
            : shape === "polygon"
              ? style.fill.fillColor
              : style.pointMode === "symbol"
                ? style.symbol.iconColor
                : style.circle.circleColor;
        base.entries = [
          {
            id: layer.id,
            label: english ? "Layer features" : "图层要素",
            color,
            shape,
          },
        ];
      }
      return base;
    });
}
