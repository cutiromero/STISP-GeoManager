import type {
  ExpressionSpecification,
  FilterSpecification,
  Map as MapboxMap,
} from "mapbox-gl";
import type { LoadedLayer, LoadedVectorLayer } from "../types";
import { clamp, sourceIdFor } from "../utils/geometry";
import {
  isGraduatedRenderer,
  isUniqueValueRenderer,
  type GraduatedRenderer,
  type GraduatedSymbolClass,
  type UniqueValueRenderer,
  type UniqueValueSymbolClass,
} from "../symbolization";
import { removeVectorInteraction } from "./featureInteraction";
import { getMapState } from "./mapState";
import {
  buildVectorPaintProperties,
  hasMapStyle,
  removeStyleLayer,
  stateColor,
  stateNumber,
  upsertLayer,
} from "./styleHelpers";
import {
  ensurePlatformSymbolImage,
  isPlatformSymbolImage,
  platformSymbolImageId,
} from "./symbolImages";
import { shouldClusterVectorLayer } from "./vectorSourceOptions";

type StyleProperties = Record<string, unknown>;

export function addLoadedStyleLayers(
  map: MapboxMap,
  sourceId: string,
  layer: LoadedVectorLayer,
) {
  const style = layer.symbolization;
  const uniqueRenderer = isUniqueValueRenderer(style.renderer)
    ? style.renderer
    : null;
  const graduatedRenderer = isGraduatedRenderer(style.renderer)
    ? style.renderer
    : null;
  const layerOpacity = clamp(style.opacity / 100, 0, 1);
  const {
    circleOpacity,
    circleStrokeOpacity,
    symbolIconOpacity,
    symbolTextOpacity,
    lineOpacity,
    fillOpacity,
  } = buildVectorPaintProperties(style, layerOpacity);
  const pointFilter = pointFeatureFilter();

  upsertLayer(map, {
    id: `${sourceId}-fill`,
    type: "fill",
    source: sourceId,
    filter: ["==", ["geometry-type"], "Polygon"],
    layout: { "fill-sort-key": style.fill.fillSortKey },
    paint: {
      "fill-color": stateColor(
        uniqueRenderer
          ? buildUniqueColorExpression(uniqueRenderer, style.fill.fillColor)
          : graduatedRenderer
            ? buildGraduatedColorExpression(
                graduatedRenderer,
                style.fill.fillColor,
              )
            : style.fill.fillColor,
      ),
      "fill-opacity": stateNumber(
        uniqueRenderer
          ? buildUniqueVisibilityExpression(uniqueRenderer, fillOpacity)
          : graduatedRenderer
            ? buildGraduatedVisibilityExpression(graduatedRenderer, fillOpacity)
            : fillOpacity,
        clamp(fillOpacity + 0.16, 0, 1),
        clamp(fillOpacity + 0.08, 0, 1),
      ),
      "fill-outline-color": style.fill.fillOutlineColor,
      "fill-antialias": style.fill.fillAntialias,
      "fill-translate": style.fill.fillTranslate,
      "fill-translate-anchor": style.fill.fillTranslateAnchor,
      "fill-emissive-strength": style.fill.fillEmissiveStrength,
    },
  });
  upsertLayer(map, {
    id: `${sourceId}-line`,
    type: "line",
    source: sourceId,
    filter: [
      "match",
      ["geometry-type"],
      ["LineString", "Polygon"],
      true,
      false,
    ],
    layout: {
      "line-cap": style.line.lineCap,
      "line-join": style.line.lineJoin,
      "line-miter-limit": style.line.lineMiterLimit,
      "line-round-limit": style.line.lineRoundLimit,
    },
    paint: {
      "line-color": stateColor(
        uniqueRenderer
          ? buildUniqueColorExpression(uniqueRenderer, style.line.lineColor)
          : graduatedRenderer
            ? buildGraduatedColorExpression(
                graduatedRenderer,
                style.line.lineColor,
              )
            : style.line.lineColor,
      ),
      "line-width": stateNumber(
        style.line.lineWidth,
        style.line.lineWidth + 2,
        style.line.lineWidth + 1,
      ),
      "line-opacity": stateNumber(
        uniqueRenderer
          ? buildUniqueVisibilityExpression(uniqueRenderer, lineOpacity)
          : graduatedRenderer
            ? buildGraduatedVisibilityExpression(graduatedRenderer, lineOpacity)
            : lineOpacity,
        clamp(lineOpacity + 0.16, 0, 1),
        clamp(lineOpacity + 0.08, 0, 1),
      ),
      "line-blur": style.line.lineBlur,
      "line-offset": style.line.lineOffset,
      "line-gap-width": style.line.lineGapWidth,
      "line-dasharray": style.line.lineDasharray,
      "line-translate": style.line.lineTranslate,
      "line-translate-anchor": style.line.lineTranslateAnchor,
      "line-emissive-strength": style.line.lineEmissiveStrength,
    },
  });

  if (shouldClusterVectorLayer(layer)) {
    addClusterStyleLayers(map, sourceId, layer, layerOpacity);
  } else {
    removeStyleLayer(map, `${sourceId}-cluster`);
    removeStyleLayer(map, `${sourceId}-cluster-count`);
  }

  if (style.pointMode === "heatmap") {
    removeStyleLayer(map, `${sourceId}-symbol`);
    upsertLayer(map, {
      id: `${sourceId}-heatmap`,
      type: "heatmap",
      source: sourceId,
      filter: pointFilter,
      paint: {
        "heatmap-weight": buildHeatmapWeight(style),
        "heatmap-intensity": buildHeatmapIntensity(style),
        "heatmap-radius": buildHeatmapRadius(style),
        "heatmap-opacity": buildHeatmapOpacity(style, layerOpacity),
        "heatmap-color": style.heatmap.heatmapColor as never,
      },
    });
    upsertLayer(map, {
      id: `${sourceId}-point`,
      type: "circle",
      source: sourceId,
      filter: pointFilter,
      layout: { "circle-sort-key": style.circle.circleSortKey },
      paint: {
        "circle-color": stateColor(style.circle.circleColor),
        "circle-radius": stateNumber(
          style.circle.circleRadius,
          style.circle.circleRadius + 3,
          style.circle.circleRadius + 1.8,
        ),
        "circle-blur": style.circle.circleBlur,
        "circle-opacity": buildHeatmapDetailOpacity(circleOpacity),
        "circle-pitch-alignment": style.circle.circlePitchAlignment,
        "circle-pitch-scale": style.circle.circlePitchScale,
        "circle-stroke-color": style.circle.circleStrokeColor,
        "circle-stroke-opacity": buildHeatmapDetailOpacity(circleStrokeOpacity),
        "circle-stroke-width": stateNumber(
          style.circle.circleStrokeWidth,
          style.circle.circleStrokeWidth + 1.2,
          style.circle.circleStrokeWidth + 0.6,
        ),
        "circle-translate": style.circle.circleTranslate,
        "circle-translate-anchor": style.circle.circleTranslateAnchor,
        "circle-emissive-strength": style.circle.circleEmissiveStrength,
      },
    });
  } else if (style.pointMode === "circle") {
    removeStyleLayer(map, `${sourceId}-heatmap`);
    removeStyleLayer(map, `${sourceId}-symbol`);
    upsertLayer(map, {
      id: `${sourceId}-point`,
      type: "circle",
      source: sourceId,
      filter: pointFilter,
      layout: { "circle-sort-key": style.circle.circleSortKey },
      paint: {
        "circle-color": stateColor(
          uniqueRenderer
            ? buildUniqueColorExpression(
                uniqueRenderer,
                style.circle.circleColor,
              )
            : graduatedRenderer
              ? buildGraduatedColorExpression(
                  graduatedRenderer,
                  style.circle.circleColor,
                )
              : style.circle.circleColor,
        ),
        "circle-radius": stateNumber(
          uniqueRenderer
            ? buildUniqueSizeExpression(
                uniqueRenderer,
                style.circle.circleRadius,
              )
            : graduatedRenderer
              ? buildGraduatedSizeExpression(
                  graduatedRenderer,
                  style.circle.circleRadius,
                )
              : style.circle.circleRadius,
          style.circle.circleRadius + 3,
          style.circle.circleRadius + 1.8,
        ),
        "circle-blur": style.circle.circleBlur,
        "circle-opacity": uniqueRenderer
          ? buildUniqueVisibilityExpression(uniqueRenderer, circleOpacity)
          : graduatedRenderer
            ? buildGraduatedVisibilityExpression(
                graduatedRenderer,
                circleOpacity,
              )
            : stateNumber(
                circleOpacity,
                clamp(circleOpacity + 0.16, 0, 1),
                clamp(circleOpacity + 0.08, 0, 1),
              ),
        "circle-pitch-alignment": style.circle.circlePitchAlignment,
        "circle-pitch-scale": style.circle.circlePitchScale,
        "circle-stroke-color": style.circle.circleStrokeColor,
        "circle-stroke-opacity": circleStrokeOpacity,
        "circle-stroke-width": stateNumber(
          style.circle.circleStrokeWidth,
          style.circle.circleStrokeWidth + 1.2,
          style.circle.circleStrokeWidth + 0.6,
        ),
        "circle-translate": style.circle.circleTranslate,
        "circle-translate-anchor": style.circle.circleTranslateAnchor,
        "circle-emissive-strength": style.circle.circleEmissiveStrength,
      },
    });
  } else {
    removeStyleLayer(map, `${sourceId}-heatmap`);
    removeStyleLayer(map, `${sourceId}-point`);
    if (uniqueRenderer) {
      ensureUniqueValueSymbolImages(map, uniqueRenderer);
    } else if (graduatedRenderer) {
      ensureGraduatedSymbolImages(map, graduatedRenderer);
    } else {
      ensurePlatformSymbolImage(
        map,
        style.symbol.iconImage,
        style.symbol.iconColor,
      );
    }
    const symbolIconImage = uniqueRenderer
      ? buildUniqueIconImageExpression(
          uniqueRenderer,
          style.symbol.iconImage,
          style.symbol.iconColor,
        )
      : graduatedRenderer
        ? buildGraduatedIconImageExpression(
            graduatedRenderer,
            style.symbol.iconImage,
            style.symbol.iconColor,
          )
        : platformSymbolImageId(style.symbol.iconImage, style.symbol.iconColor);
    const usesPlatformSymbolImage = uniqueRenderer
      ? uniqueRendererUsesPlatformImages(uniqueRenderer)
      : graduatedRenderer
        ? graduatedRendererUsesPlatformImages(graduatedRenderer)
        : isPlatformSymbolImage(style.symbol.iconImage);
    const enableSymbolText =
      style.symbol.textField.trim().length > 0 && mapStyleSupportsGlyphs(map);
    const symbolLayerId = `${sourceId}-symbol`;
    if (usesPlatformSymbolImage) {
      removeStyleLayer(map, symbolLayerId);
    }
    const symbolLayout = usesPlatformSymbolImage
      ? buildPlatformSymbolLayout(style, symbolIconImage, enableSymbolText)
      : buildExternalSymbolLayout(style, symbolIconImage, enableSymbolText);
    if (uniqueRenderer) {
      symbolLayout["icon-size"] = buildUniqueSizeExpression(
        uniqueRenderer,
        style.symbol.iconSize,
      );
    } else if (graduatedRenderer) {
      symbolLayout["icon-size"] = buildGraduatedSizeExpression(
        graduatedRenderer,
        style.symbol.iconSize,
      );
    }
    const symbolPaint = usesPlatformSymbolImage
      ? buildPlatformSymbolPaint(
          style,
          symbolIconOpacity,
          symbolTextOpacity,
          enableSymbolText,
        )
      : buildExternalSymbolPaint(
          style,
          symbolIconOpacity,
          symbolTextOpacity,
          enableSymbolText,
        );
    if (uniqueRenderer) {
      symbolPaint["icon-opacity"] = buildUniqueVisibilityExpression(
        uniqueRenderer,
        symbolIconOpacity,
      );
      if (enableSymbolText) {
        symbolPaint["text-opacity"] = buildUniqueVisibilityExpression(
          uniqueRenderer,
          symbolTextOpacity,
        );
      }
    } else if (graduatedRenderer) {
      symbolPaint["icon-opacity"] = buildGraduatedVisibilityExpression(
        graduatedRenderer,
        symbolIconOpacity,
      );
      if (enableSymbolText) {
        symbolPaint["text-opacity"] = buildGraduatedVisibilityExpression(
          graduatedRenderer,
          symbolTextOpacity,
        );
      }
    }
    upsertLayer(map, {
      id: symbolLayerId,
      type: "symbol",
      source: sourceId,
      filter: pointFilter,
      layout: symbolLayout,
      paint: symbolPaint,
    });
  }
}

function pointFeatureFilter(): FilterSpecification {
  return [
    "all",
    ["==", ["geometry-type"], "Point"],
    ["!", ["has", "point_count"]],
  ];
}

function buildUniqueColorExpression(
  renderer: UniqueValueRenderer,
  fallback: string,
) {
  return buildUniqueMatchExpression(
    renderer,
    (item) => item.color,
    renderer.defaultClass.color || fallback,
  );
}

function buildUniqueSizeExpression(
  renderer: UniqueValueRenderer,
  baseSize: number,
) {
  return buildUniqueMatchExpression(
    renderer,
    (item) => Math.max(0.01, baseSize * (item.size || 1)),
    Math.max(0.01, baseSize * (renderer.defaultClass.size || 1)),
  );
}

function buildUniqueVisibilityExpression(
  renderer: UniqueValueRenderer,
  baseOpacity: number,
) {
  return buildUniqueMatchExpression(
    renderer,
    (item) => (item.visible ? baseOpacity : 0),
    renderer.defaultClass.visible ? baseOpacity : 0,
  );
}

function buildUniqueIconImageExpression(
  renderer: UniqueValueRenderer,
  fallbackIcon: string,
  fallbackColor: string,
) {
  const fallback = uniqueClassImageId(
    renderer.defaultClass,
    fallbackIcon,
    fallbackColor,
  );
  return buildUniqueMatchExpression(
    renderer,
    (item) => uniqueClassImageId(item, fallbackIcon, fallbackColor),
    fallback,
  );
}

function buildUniqueMatchExpression<T>(
  renderer: UniqueValueRenderer,
  output: (item: UniqueValueSymbolClass) => T,
  fallback: T,
) {
  const expression: unknown[] = [
    "match",
    ["to-string", ["get", renderer.field]],
  ];
  for (const item of renderer.classes) {
    const values = item.values
      .map((value) => String(value).trim())
      .filter(Boolean);
    if (values.length === 0) continue;
    expression.push(values.length === 1 ? values[0] : values, output(item));
  }
  expression.push(fallback);
  return expression as unknown as ExpressionSpecification;
}

function uniqueClassImageId(
  item: UniqueValueSymbolClass,
  fallbackIcon: string,
  fallbackColor: string,
) {
  return platformSymbolImageId(
    item.iconImage || fallbackIcon,
    item.color || fallbackColor,
  );
}

function ensureUniqueValueSymbolImages(
  map: MapboxMap,
  renderer: UniqueValueRenderer,
) {
  for (const item of [...renderer.classes, renderer.defaultClass]) {
    ensurePlatformSymbolImage(map, item.iconImage, item.color);
  }
}

function uniqueRendererUsesPlatformImages(renderer: UniqueValueRenderer) {
  return [...renderer.classes, renderer.defaultClass].every((item) =>
    isPlatformSymbolImage(item.iconImage),
  );
}

function buildGraduatedColorExpression(
  renderer: GraduatedRenderer,
  fallback: string,
) {
  return buildGraduatedCaseExpression(
    renderer,
    (item) => item.color,
    renderer.defaultClass.color || fallback,
  );
}

function buildGraduatedSizeExpression(
  renderer: GraduatedRenderer,
  baseSize: number,
) {
  return buildGraduatedCaseExpression(
    renderer,
    (item) => Math.max(0.01, baseSize * (item.size || 1)),
    Math.max(0.01, baseSize * (renderer.defaultClass.size || 1)),
  );
}

function buildGraduatedVisibilityExpression(
  renderer: GraduatedRenderer,
  baseOpacity: number,
) {
  return buildGraduatedCaseExpression(
    renderer,
    (item) => (item.visible ? baseOpacity : 0),
    renderer.defaultClass.visible ? baseOpacity : 0,
  );
}

function buildGraduatedIconImageExpression(
  renderer: GraduatedRenderer,
  fallbackIcon: string,
  fallbackColor: string,
) {
  const fallback = graduatedClassImageId(
    renderer.defaultClass,
    fallbackIcon,
    fallbackColor,
  );
  return buildGraduatedCaseExpression(
    renderer,
    (item) => graduatedClassImageId(item, fallbackIcon, fallbackColor),
    fallback,
  );
}

function buildGraduatedCaseExpression<T>(
  renderer: GraduatedRenderer,
  output: (item: GraduatedSymbolClass) => T,
  fallback: T,
) {
  const fieldValue = [
    "to-number",
    ["get", renderer.field],
    graduatedFallbackNumber(renderer),
  ];
  const expression: unknown[] = ["case"];
  renderer.classes.forEach((item, index) => {
    if (!Number.isFinite(item.min) || !Number.isFinite(item.max)) return;
    const min = item.min as number;
    const max = item.max as number;
    const includeMax =
      index === renderer.classes.length - 1 ||
      (renderer.method === "manual" && min === max);
    expression.push(
      [
        "all",
        [">=", fieldValue, min],
        [includeMax ? "<=" : "<", fieldValue, max],
      ],
      output(item),
    );
  });
  if (expression.length === 1) return fallback;
  expression.push(fallback);
  return expression as unknown as ExpressionSpecification;
}

function graduatedFallbackNumber(renderer: GraduatedRenderer) {
  const limits = renderer.classes.flatMap((item) =>
    [item.min, item.max].filter(
      (value): value is number =>
        typeof value === "number" && Number.isFinite(value),
    ),
  );
  if (limits.length === 0) return -1;
  const min = Math.min(...limits);
  const max = Math.max(...limits);
  return min - Math.max(Math.abs(max - min), 1) - 1;
}

function graduatedClassImageId(
  item: GraduatedSymbolClass,
  fallbackIcon: string,
  fallbackColor: string,
) {
  return platformSymbolImageId(
    item.iconImage || fallbackIcon,
    item.color || fallbackColor,
  );
}

function ensureGraduatedSymbolImages(
  map: MapboxMap,
  renderer: GraduatedRenderer,
) {
  for (const item of [...renderer.classes, renderer.defaultClass]) {
    ensurePlatformSymbolImage(map, item.iconImage, item.color);
  }
}

function graduatedRendererUsesPlatformImages(renderer: GraduatedRenderer) {
  return [...renderer.classes, renderer.defaultClass].every((item) =>
    isPlatformSymbolImage(item.iconImage),
  );
}

function addClusterStyleLayers(
  map: MapboxMap,
  sourceId: string,
  layer: LoadedVectorLayer,
  layerOpacity: number,
) {
  const style = layer.symbolization;
  const baseColor =
    style.pointMode === "symbol"
      ? style.symbol.iconColor
      : style.circle.circleColor;
  const opacity = clamp(layerOpacity * 0.86, 0, 1);
  upsertLayer(map, {
    id: `${sourceId}-cluster`,
    type: "circle",
    source: sourceId,
    filter: ["has", "point_count"],
    paint: {
      "circle-color": [
        "step",
        ["get", "point_count"],
        baseColor,
        100,
        "#f2c36d",
        750,
        "#e4582b",
      ],
      "circle-opacity": opacity,
      "circle-radius": ["step", ["get", "point_count"], 14, 100, 20, 750, 28],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-opacity": opacity,
      "circle-stroke-width": 1.2,
    },
  });
  if (!mapStyleSupportsGlyphs(map)) {
    removeStyleLayer(map, `${sourceId}-cluster-count`);
    return;
  }
  upsertLayer(map, {
    id: `${sourceId}-cluster-count`,
    type: "symbol",
    source: sourceId,
    filter: ["has", "point_count"],
    layout: {
      "text-field": "{point_count_abbreviated}",
      "text-font": style.symbol.textFont,
      "text-size": 12,
      "text-allow-overlap": true,
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": "rgba(0, 0, 0, 0.28)",
      "text-halo-width": 1,
    },
  });
}

function buildHeatmapWeight(style: LoadedVectorLayer["symbolization"]) {
  const baseWeight = clamp(style.heatmap.heatmapWeight ?? 0.72, 0, 1);
  const weightField = style.heatmap.heatmapWeightField?.trim();
  if (!weightField) return baseWeight;
  const fieldMax = Math.max(style.heatmap.heatmapWeightFieldMax ?? 1, 1);
  return [
    "interpolate",
    ["linear"],
    ["to-number", ["get", weightField], 0],
    0,
    0,
    fieldMax,
    baseWeight,
  ] as unknown as ExpressionSpecification;
}

function buildHeatmapIntensity(style: LoadedVectorLayer["symbolization"]) {
  const intensity = clamp(style.heatmap.heatmapIntensity ?? 0.9, 0, 3);
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    3,
    intensity * 0.35,
    8,
    intensity * 0.85,
    11,
    intensity * 1.12,
    13,
    intensity * 0.82,
  ] as unknown as ExpressionSpecification;
}

function buildHeatmapRadius(style: LoadedVectorLayer["symbolization"]) {
  const radius = clamp(style.heatmap.heatmapRadius ?? 24, 1, 80);
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    3,
    Math.max(2, radius * 0.35),
    8,
    radius * 0.72,
    11,
    radius,
    13,
    Math.max(8, radius * 0.55),
  ] as unknown as ExpressionSpecification;
}

function buildHeatmapOpacity(
  style: LoadedVectorLayer["symbolization"],
  layerOpacity: number,
) {
  const opacity = clamp(
    (style.heatmap.heatmapOpacity ?? 0.78) * layerOpacity,
    0,
    1,
  );
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    3,
    opacity * 0.55,
    8,
    opacity,
    11,
    opacity * 0.72,
    13,
    0,
  ] as unknown as ExpressionSpecification;
}

function buildHeatmapDetailOpacity(opacity: number) {
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    10,
    0,
    12,
    clamp(opacity, 0, 1),
  ] as unknown as ExpressionSpecification;
}

function buildPlatformSymbolLayout(
  style: LoadedVectorLayer["symbolization"],
  symbolIconImage: string | ExpressionSpecification,
  enableText: boolean,
) {
  const symbolLayout: StyleProperties = {
    "symbol-placement": "point",
    "icon-image": symbolIconImage,
    "icon-size": style.symbol.iconSize,
    "icon-allow-overlap": true,
    "icon-ignore-placement": true,
    "icon-anchor": style.symbol.iconAnchor,
    "icon-offset": style.symbol.iconOffset,
    "icon-rotate": style.symbol.iconRotate,
    "icon-pitch-alignment": style.symbol.iconPitchAlignment,
    "icon-rotation-alignment": style.symbol.iconRotationAlignment,
  };
  addTextLayoutProperties(symbolLayout, style, enableText);
  return symbolLayout;
}

function buildExternalSymbolLayout(
  style: LoadedVectorLayer["symbolization"],
  symbolIconImage: string | ExpressionSpecification,
  enableText: boolean,
) {
  const symbolLayout: StyleProperties = {
    "symbol-placement": style.symbol.symbolPlacement,
    "symbol-spacing": style.symbol.symbolSpacing,
    "symbol-avoid-edges": style.symbol.symbolAvoidEdges,
    "symbol-sort-key": style.symbol.symbolSortKey,
    "symbol-z-order": style.symbol.symbolZOrder,
    "icon-image": symbolIconImage,
    "icon-size": style.symbol.iconSize,
    "icon-allow-overlap": true,
    "icon-ignore-placement": true,
    "icon-optional": style.symbol.iconOptional,
    "icon-anchor": style.symbol.iconAnchor,
    "icon-offset": style.symbol.iconOffset,
    "icon-padding": style.symbol.iconPadding,
    "icon-keep-upright": style.symbol.iconKeepUpright,
    "icon-rotate": style.symbol.iconRotate,
    "icon-pitch-alignment": style.symbol.iconPitchAlignment,
    "icon-rotation-alignment": style.symbol.iconRotationAlignment,
    "icon-text-fit": style.symbol.iconTextFit,
    "icon-text-fit-padding": style.symbol.iconTextFitPadding,
  };
  addTextLayoutProperties(symbolLayout, style, enableText);
  return symbolLayout;
}

function addTextLayoutProperties(
  symbolLayout: StyleProperties,
  style: LoadedVectorLayer["symbolization"],
  enableText: boolean,
) {
  if (!enableText) return;
  symbolLayout["text-field"] = style.symbol.textField;
  symbolLayout["text-font"] = style.symbol.textFont;
  symbolLayout["text-size"] = style.symbol.textSize;
  symbolLayout["text-max-width"] = style.symbol.textMaxWidth;
  symbolLayout["text-line-height"] = style.symbol.textLineHeight;
  symbolLayout["text-letter-spacing"] = style.symbol.textLetterSpacing;
  symbolLayout["text-justify"] = style.symbol.textJustify;
  symbolLayout["text-anchor"] = style.symbol.textAnchor;
  symbolLayout["text-offset"] = style.symbol.textOffset;
  symbolLayout["text-radial-offset"] = style.symbol.textRadialOffset;
  symbolLayout["text-writing-mode"] = style.symbol.textWritingMode;
  symbolLayout["text-padding"] = style.symbol.textPadding;
  symbolLayout["text-keep-upright"] = style.symbol.textKeepUpright;
  symbolLayout["text-allow-overlap"] = style.symbol.textAllowOverlap;
  symbolLayout["text-ignore-placement"] = style.symbol.textIgnorePlacement;
  symbolLayout["text-optional"] = style.symbol.textOptional;
  symbolLayout["text-rotate"] = style.symbol.textRotate;
  symbolLayout["text-pitch-alignment"] = style.symbol.textPitchAlignment;
  symbolLayout["text-rotation-alignment"] = style.symbol.textRotationAlignment;
  symbolLayout["text-transform"] = style.symbol.textTransform;
  if (style.symbol.textVariableAnchor.length > 0) {
    symbolLayout["text-variable-anchor"] = style.symbol.textVariableAnchor;
  }
}

function buildPlatformSymbolPaint(
  style: LoadedVectorLayer["symbolization"],
  symbolIconOpacity: number,
  symbolTextOpacity: number,
  enableText: boolean,
) {
  const symbolPaint: StyleProperties = {
    "icon-opacity": stateNumber(
      symbolIconOpacity,
      clamp(symbolIconOpacity + 0.16, 0, 1),
      clamp(symbolIconOpacity + 0.08, 0, 1),
    ),
    "icon-translate": style.symbol.iconTranslate,
    "icon-translate-anchor": style.symbol.iconTranslateAnchor,
  };
  addTextPaintProperties(symbolPaint, style, symbolTextOpacity, enableText);
  return symbolPaint;
}

function buildExternalSymbolPaint(
  style: LoadedVectorLayer["symbolization"],
  symbolIconOpacity: number,
  symbolTextOpacity: number,
  enableText: boolean,
) {
  const symbolPaint: StyleProperties = {
    "icon-opacity": stateNumber(
      symbolIconOpacity,
      clamp(symbolIconOpacity + 0.16, 0, 1),
      clamp(symbolIconOpacity + 0.08, 0, 1),
    ),
    "icon-translate": style.symbol.iconTranslate,
    "icon-translate-anchor": style.symbol.iconTranslateAnchor,
    "icon-color": stateColor(style.symbol.iconColor),
    "icon-halo-color": style.symbol.iconHaloColor,
    "icon-halo-width": style.symbol.iconHaloWidth,
    "icon-halo-blur": style.symbol.iconHaloBlur,
  };
  addTextPaintProperties(symbolPaint, style, symbolTextOpacity, enableText);
  return symbolPaint;
}

function addTextPaintProperties(
  symbolPaint: StyleProperties,
  style: LoadedVectorLayer["symbolization"],
  symbolTextOpacity: number,
  enableText: boolean,
) {
  if (!enableText) return;
  symbolPaint["text-color"] = stateColor(style.symbol.textColor);
  symbolPaint["text-opacity"] = stateNumber(
    symbolTextOpacity,
    clamp(symbolTextOpacity + 0.16, 0, 1),
    clamp(symbolTextOpacity + 0.08, 0, 1),
  );
  symbolPaint["text-halo-color"] = style.symbol.textHaloColor;
  symbolPaint["text-halo-width"] = style.symbol.textHaloWidth;
  symbolPaint["text-halo-blur"] = style.symbol.textHaloBlur;
  symbolPaint["text-translate"] = style.symbol.textTranslate;
  symbolPaint["text-translate-anchor"] = style.symbol.textTranslateAnchor;
}

function mapStyleSupportsGlyphs(map: MapboxMap) {
  return Boolean((map.getStyle() as { glyphs?: unknown }).glyphs);
}

export function removeLoadedLayerGroup(map: MapboxMap, sourceId: string) {
  removeLayerGroup(map, sourceId, loadedStyleLayerIds(sourceId));
}

export function setLoadedLayerGroupVisibility(
  map: MapboxMap,
  sourceId: string,
  visible: boolean,
) {
  if (!hasMapStyle(map)) return;
  const visibility = visible ? "visible" : "none";
  for (const layerId of loadedStyleLayerIds(sourceId)) {
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, "visibility", visibility);
    }
  }
}

export function loadedStyleLayerIds(sourceId: string) {
  return [
    `${sourceId}-raster`,
    `${sourceId}-heatmap`,
    `${sourceId}-fill`,
    `${sourceId}-line`,
    `${sourceId}-cluster`,
    `${sourceId}-cluster-count`,
    `${sourceId}-point`,
    `${sourceId}-symbol`,
  ];
}

export function removeLayerGroup(
  map: MapboxMap,
  sourceId: string,
  layerIds: string[],
  options?: { cleanInteraction?: boolean },
) {
  if (!hasMapStyle(map)) return;
  const cleanInteraction = options?.cleanInteraction ?? true;
  layerIds.forEach((id) => {
    if (cleanInteraction) removeVectorInteraction(map, id);
    if (map.getLayer(id)) map.removeLayer(id);
  });
  if (map.getSource(sourceId)) map.removeSource(sourceId);
  if (cleanInteraction) getMapState(map).vectorSourceKeys.delete(sourceId);
  if (cleanInteraction) getMapState(map).rasterSourceKeys.delete(sourceId);
}

export function reorderLoadedStyleLayers(
  map: MapboxMap,
  layers: LoadedLayer[],
) {
  if (!hasMapStyle(map)) return;
  for (const layer of [...layers].reverse()) {
    const sourceId = sourceIdFor(layer.id);
    for (const styleLayerId of loadedStyleLayerIds(sourceId)) {
      if (map.getLayer(styleLayerId)) map.moveLayer(styleLayerId);
    }
  }
}
