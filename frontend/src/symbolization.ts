export type Anchor =
  | "center"
  | "left"
  | "right"
  | "top"
  | "bottom"
  | "top-left"
  | "top-right"
  | "bottom-left"
  | "bottom-right";

export type Alignment = "map" | "viewport" | "auto";
export type MapViewport = "map" | "viewport";
type PointSymbolMode = "circle" | "symbol" | "heatmap";
type SymbolPlacement = "point" | "line" | "line-center";
type SymbolZOrder = "auto" | "viewport-y" | "source";
type TextJustify = "auto" | "left" | "center" | "right";
type TextTransform = "none" | "uppercase" | "lowercase";
type IconTextFit = "none" | "width" | "height" | "both";
type LineCap = "butt" | "round" | "square";
type LineJoin = "bevel" | "round" | "miter" | "none";

export const platformSymbolIconIds = [
  "gm-marker",
  "gm-point",
  "gm-sample",
  "gm-plot",
  "gm-transect",
  "gm-collection",
  "gm-revisit",
  "gm-populus",
  "gm-tree",
  "gm-leaf",
  "gm-seed",
  "gm-species",
  "gm-community",
  "gm-ancient-tree",
  "gm-station",
  "gm-water",
  "gm-groundwater",
  "gm-soil",
  "gm-salinity",
  "gm-climate",
  "gm-sensor",
  "gm-satellite",
  "gm-pixel",
  "gm-ndvi",
  "gm-npp",
  "gm-imagery",
  "gm-zonal",
  "gm-dna",
  "gm-tube",
  "gm-vial",
  "gm-core-germplasm",
  "gm-germplasm",
  "gm-alert",
  "gm-error",
  "gm-pending",
  "gm-confirmed",
  "gm-quality",
  "gm-priority",
] as const;

export type PlatformSymbolIconId = (typeof platformSymbolIconIds)[number];

export const platformSymbolIconGroups = [
  {
    label: "调查采样",
    options: [
      { value: "gm-marker", label: "定位标记" },
      { value: "gm-point", label: "普通样点" },
      { value: "gm-sample", label: "调查样点" },
      { value: "gm-plot", label: "样方" },
      { value: "gm-transect", label: "样线点" },
      { value: "gm-collection", label: "采集点" },
      { value: "gm-revisit", label: "复测点" },
    ],
  },
  {
    label: "生态植被",
    options: [
      { value: "gm-populus", label: "胡杨" },
      { value: "gm-tree", label: "植株" },
      { value: "gm-leaf", label: "叶片" },
      { value: "gm-seed", label: "种子" },
      { value: "gm-species", label: "物种分布" },
      { value: "gm-community", label: "群落" },
      { value: "gm-ancient-tree", label: "古树" },
    ],
  },
  {
    label: "环境监测",
    options: [
      { value: "gm-station", label: "监测站" },
      { value: "gm-water", label: "水文点" },
      { value: "gm-groundwater", label: "地下水" },
      { value: "gm-soil", label: "土壤点" },
      { value: "gm-salinity", label: "盐分点" },
      { value: "gm-climate", label: "气候点" },
      { value: "gm-sensor", label: "传感器" },
    ],
  },
  {
    label: "遥感栅格",
    options: [
      { value: "gm-satellite", label: "卫星" },
      { value: "gm-pixel", label: "栅格像元" },
      { value: "gm-ndvi", label: "NDVI" },
      { value: "gm-npp", label: "NPP" },
      { value: "gm-imagery", label: "遥感影像点" },
      { value: "gm-zonal", label: "区域统计" },
    ],
  },
  {
    label: "DNA 种质",
    options: [
      { value: "gm-dna", label: "DNA 样品" },
      { value: "gm-tube", label: "试管" },
      { value: "gm-vial", label: "样品瓶" },
      { value: "gm-core-germplasm", label: "核心种质" },
      { value: "gm-germplasm", label: "种质资源" },
    ],
  },
  {
    label: "状态管理",
    options: [
      { value: "gm-alert", label: "风险预警" },
      { value: "gm-error", label: "异常点" },
      { value: "gm-pending", label: "待核验" },
      { value: "gm-confirmed", label: "已确认" },
      { value: "gm-quality", label: "数据质量" },
      { value: "gm-priority", label: "重点点位" },
    ],
  },
] as const satisfies readonly {
  label: string;
  options: readonly { value: PlatformSymbolIconId; label: string }[];
}[];

export const legacySymbolIconAliases = {
  "marker-15": "gm-marker",
  "harbor-15": "gm-station",
  "circle-15": "gm-sample",
  "triangle-15": "gm-alert",
  "star-15": "gm-priority",
} as const satisfies Record<string, PlatformSymbolIconId>;

export function normalizeSymbolIconImage(iconImage: string) {
  return (
    legacySymbolIconAliases[
      iconImage as keyof typeof legacySymbolIconAliases
    ] ?? iconImage
  );
}

export interface GroupSymbolization {
  opacity: number;
}

export interface CircleSymbolization {
  circleColor: string;
  circleRadius: number;
  circleBlur: number;
  circleOpacity: number;
  circlePitchAlignment: MapViewport;
  circlePitchScale: MapViewport;
  circleSortKey: number;
  circleStrokeColor: string;
  circleStrokeOpacity: number;
  circleStrokeWidth: number;
  circleTranslate: [number, number];
  circleTranslateAnchor: MapViewport;
  circleEmissiveStrength: number;
}

export interface SymbolLayerSymbolization {
  symbolPlacement: SymbolPlacement;
  symbolSpacing: number;
  symbolAvoidEdges: boolean;
  symbolSortKey: number;
  symbolZOrder: SymbolZOrder;
  iconImage: string;
  iconSize: number;
  iconSizeScaleRange: [number, number];
  iconAllowOverlap: boolean;
  iconIgnorePlacement: boolean;
  iconOptional: boolean;
  iconAnchor: Anchor;
  iconOffset: [number, number];
  iconPadding: number;
  iconKeepUpright: boolean;
  iconRotate: number;
  iconPitchAlignment: Alignment;
  iconRotationAlignment: Alignment;
  iconTextFit: IconTextFit;
  iconTextFitPadding: [number, number, number, number];
  iconColor: string;
  iconOpacity: number;
  iconHaloColor: string;
  iconHaloWidth: number;
  iconHaloBlur: number;
  iconTranslate: [number, number];
  iconTranslateAnchor: MapViewport;
  iconEmissiveStrength: number;
  iconColorBrightnessMin: number;
  iconColorBrightnessMax: number;
  iconColorContrast: number;
  iconColorSaturation: number;
  iconOcclusionOpacity: number;
  textField: string;
  textFont: string[];
  textSize: number;
  textMaxWidth: number;
  textLineHeight: number;
  textLetterSpacing: number;
  textJustify: TextJustify;
  textAnchor: Anchor;
  textOffset: [number, number];
  textRadialOffset: number;
  textVariableAnchor: Anchor[];
  textWritingMode: Array<"horizontal" | "vertical">;
  textPadding: number;
  textKeepUpright: boolean;
  textAllowOverlap: boolean;
  textIgnorePlacement: boolean;
  textOptional: boolean;
  textRotate: number;
  textPitchAlignment: Alignment;
  textRotationAlignment: Alignment;
  textTransform: TextTransform;
  textColor: string;
  textOpacity: number;
  textHaloColor: string;
  textHaloWidth: number;
  textHaloBlur: number;
  textTranslate: [number, number];
  textTranslateAnchor: MapViewport;
  textEmissiveStrength: number;
  textOcclusionOpacity: number;
}

export interface LineSymbolization {
  lineColor: string;
  lineOpacity: number;
  lineWidth: number;
  lineBlur: number;
  lineCap: LineCap;
  lineJoin: LineJoin;
  lineMiterLimit: number;
  lineRoundLimit: number;
  lineOffset: number;
  lineGapWidth: number;
  lineDasharray: [number, number];
  lineTranslate: [number, number];
  lineTranslateAnchor: MapViewport;
  lineEmissiveStrength: number;
}

export interface FillSymbolization {
  fillColor: string;
  fillOpacity: number;
  fillOutlineColor: string;
  fillAntialias: boolean;
  fillSortKey: number;
  fillTranslate: [number, number];
  fillTranslateAnchor: MapViewport;
  fillEmissiveStrength: number;
}

export interface HeatmapSymbolization {
  heatmapWeight: number;
  heatmapWeightField: string;
  heatmapWeightFieldMax: number;
  heatmapIntensity: number;
  heatmapRadius: number;
  heatmapOpacity: number;
  heatmapColor: unknown[];
}

export interface ClusterSymbolization {
  enabled: boolean;
  maxZoom: number;
  radius: number;
}

export interface SingleSymbolRenderer {
  type: "single";
  templateId?: string;
  businessType?: string;
  updatedByUser?: boolean;
}

export interface UniqueValueSymbolClass {
  id: string;
  label: string;
  values: string[];
  color: string;
  iconImage: string;
  size: number;
  count: number;
  visible: boolean;
}

export interface UniqueValueRenderer {
  type: "uniqueValue";
  field: string;
  templateId?: string;
  businessType?: string;
  updatedByUser?: boolean;
  classes: UniqueValueSymbolClass[];
  defaultClass: UniqueValueSymbolClass;
  normalizationNotes?: string[];
}

export type GraduatedClassificationMethod =
  | "equalInterval"
  | "quantile"
  | "manual";
export type GraduatedColorRamp = "green" | "blue" | "orange" | "purple";

export interface GraduatedSymbolClass {
  id: string;
  label: string;
  min: number | null;
  max: number | null;
  color: string;
  iconImage: string;
  size: number;
  count: number;
  visible: boolean;
}

export interface GraduatedRenderer {
  type: "graduated";
  field: string;
  method: GraduatedClassificationMethod;
  classCount: number;
  precision: number;
  colorRamp: GraduatedColorRamp;
  templateId?: string;
  businessType?: string;
  updatedByUser?: boolean;
  classes: GraduatedSymbolClass[];
  defaultClass: GraduatedSymbolClass;
}

export type VectorRenderer =
  | SingleSymbolRenderer
  | UniqueValueRenderer
  | GraduatedRenderer;

export interface VectorSymbolization {
  opacity: number;
  pointMode: PointSymbolMode;
  renderer?: VectorRenderer;
  circle: CircleSymbolization;
  symbol: SymbolLayerSymbolization;
  heatmap: HeatmapSymbolization;
  cluster: ClusterSymbolization;
  line: LineSymbolization;
  fill: FillSymbolization;
}

type RasterRenderMode = "gray" | "rgb" | "pseudocolor" | "unique";

interface RasterStretchBand {
  min: number;
  max: number;
}

interface RasterUniqueValue {
  value: number;
  color: string;
  label: string;
}

export interface RasterSymbolization {
  opacity: number;
  mode: RasterRenderMode;
  bands: number[];
  alphaBand: number | "mask" | null;
  nodata: {
    enabled: boolean;
  };
  stretch: {
    enabled: boolean;
    type: "minmax";
    perBand: Record<string, RasterStretchBand>;
  };
  palette: "poplar" | "viridis" | "terrain" | "thermal";
  uniqueValues: RasterUniqueValue[];
}

export const defaultGroupSymbolization: GroupSymbolization = {
  opacity: 100,
};

export const defaultVectorSymbolization: VectorSymbolization = {
  opacity: 90,
  pointMode: "circle",
  renderer: {
    type: "single",
    updatedByUser: false,
  },
  circle: {
    circleColor: "#d9a441",
    circleRadius: 6,
    circleBlur: 0,
    circleOpacity: 1,
    circlePitchAlignment: "viewport",
    circlePitchScale: "map",
    circleSortKey: 0,
    circleStrokeColor: "#ffffff",
    circleStrokeOpacity: 1,
    circleStrokeWidth: 1.2,
    circleTranslate: [0, 0],
    circleTranslateAnchor: "map",
    circleEmissiveStrength: 0,
  },
  symbol: {
    symbolPlacement: "point",
    symbolSpacing: 250,
    symbolAvoidEdges: false,
    symbolSortKey: 0,
    symbolZOrder: "auto",
    iconImage: "gm-marker",
    iconSize: 1,
    iconSizeScaleRange: [0.8, 2],
    iconAllowOverlap: true,
    iconIgnorePlacement: false,
    iconOptional: false,
    iconAnchor: "center",
    iconOffset: [0, 0],
    iconPadding: 2,
    iconKeepUpright: false,
    iconRotate: 0,
    iconPitchAlignment: "auto",
    iconRotationAlignment: "auto",
    iconTextFit: "none",
    iconTextFitPadding: [0, 0, 0, 0],
    iconColor: "#2f7d62",
    iconOpacity: 1,
    iconHaloColor: "#ffffff",
    iconHaloWidth: 0,
    iconHaloBlur: 0,
    iconTranslate: [0, 0],
    iconTranslateAnchor: "map",
    iconEmissiveStrength: 0,
    iconColorBrightnessMin: 0,
    iconColorBrightnessMax: 1,
    iconColorContrast: 0,
    iconColorSaturation: 0,
    iconOcclusionOpacity: 1,
    textField: "",
    textFont: ["Open Sans Regular", "Arial Unicode MS Regular"],
    textSize: 12,
    textMaxWidth: 10,
    textLineHeight: 1.2,
    textLetterSpacing: 0,
    textJustify: "auto",
    textAnchor: "center",
    textOffset: [0, 1.2],
    textRadialOffset: 0,
    textVariableAnchor: [],
    textWritingMode: ["horizontal"],
    textPadding: 2,
    textKeepUpright: true,
    textAllowOverlap: false,
    textIgnorePlacement: false,
    textOptional: false,
    textRotate: 0,
    textPitchAlignment: "auto",
    textRotationAlignment: "auto",
    textTransform: "none",
    textColor: "#173f39",
    textOpacity: 1,
    textHaloColor: "#ffffff",
    textHaloWidth: 1,
    textHaloBlur: 0,
    textTranslate: [0, 0],
    textTranslateAnchor: "map",
    textEmissiveStrength: 0,
    textOcclusionOpacity: 1,
  },
  heatmap: {
    heatmapWeight: 0.72,
    heatmapWeightField: "",
    heatmapWeightFieldMax: 1,
    heatmapIntensity: 0.9,
    heatmapRadius: 24,
    heatmapOpacity: 0.78,
    heatmapColor: [
      "interpolate",
      ["linear"],
      ["heatmap-density"],
      0,
      "rgba(0, 0, 0, 0)",
      0.12,
      "rgba(72, 202, 228, 0.22)",
      0.32,
      "#48cae4",
      0.55,
      "#80ed99",
      0.76,
      "#ffd166",
      0.92,
      "#f77f00",
      1,
      "#d62828",
    ],
  },
  cluster: {
    enabled: false,
    maxZoom: 12,
    radius: 50,
  },
  line: {
    lineColor: "#174f46",
    lineOpacity: 1,
    lineWidth: 1.4,
    lineBlur: 0,
    lineCap: "round",
    lineJoin: "round",
    lineMiterLimit: 2,
    lineRoundLimit: 1.05,
    lineOffset: 0,
    lineGapWidth: 0,
    lineDasharray: [1, 0],
    lineTranslate: [0, 0],
    lineTranslateAnchor: "map",
    lineEmissiveStrength: 0,
  },
  fill: {
    fillColor: "#2f7d62",
    fillOpacity: 0.72,
    fillOutlineColor: "#174f46",
    fillAntialias: true,
    fillSortKey: 0,
    fillTranslate: [0, 0],
    fillTranslateAnchor: "map",
    fillEmissiveStrength: 0,
  },
};

export const defaultUniqueValueClass: UniqueValueSymbolClass = {
  id: "other",
  label: "其他/未知",
  values: [],
  color: "#8A8F98",
  iconImage: "gm-tree",
  size: 1,
  count: 0,
  visible: true,
};

export const defaultGraduatedClass: GraduatedSymbolClass = {
  id: "no-data",
  label: "无数值/空值",
  min: null,
  max: null,
  color: "#8A8F98",
  iconImage: "gm-marker",
  size: 0.9,
  count: 0,
  visible: true,
};

export const defaultRasterSymbolization: RasterSymbolization = {
  opacity: 90,
  mode: "gray",
  bands: [1],
  alphaBand: "mask",
  nodata: {
    enabled: true,
  },
  stretch: {
    enabled: true,
    type: "minmax",
    perBand: {
      "1": { min: 0, max: 255 },
    },
  },
  palette: "poplar",
  uniqueValues: [],
};

export function cloneDefaultGroupSymbolization(): GroupSymbolization {
  return { ...defaultGroupSymbolization };
}

export function cloneDefaultVectorSymbolization(): VectorSymbolization {
  return {
    ...defaultVectorSymbolization,
    renderer: cloneVectorRenderer(defaultVectorSymbolization.renderer),
    circle: { ...defaultVectorSymbolization.circle },
    symbol: {
      ...defaultVectorSymbolization.symbol,
      iconOffset: [...defaultVectorSymbolization.symbol.iconOffset],
      iconSizeScaleRange: [
        ...defaultVectorSymbolization.symbol.iconSizeScaleRange,
      ],
      iconTextFitPadding: [
        ...defaultVectorSymbolization.symbol.iconTextFitPadding,
      ],
      iconTranslate: [...defaultVectorSymbolization.symbol.iconTranslate],
      textFont: [...defaultVectorSymbolization.symbol.textFont],
      textOffset: [...defaultVectorSymbolization.symbol.textOffset],
      textTranslate: [...defaultVectorSymbolization.symbol.textTranslate],
      textVariableAnchor: [
        ...defaultVectorSymbolization.symbol.textVariableAnchor,
      ],
      textWritingMode: [...defaultVectorSymbolization.symbol.textWritingMode],
    },
    heatmap: {
      ...defaultVectorSymbolization.heatmap,
      heatmapColor: [...defaultVectorSymbolization.heatmap.heatmapColor],
    },
    cluster: { ...defaultVectorSymbolization.cluster },
    line: {
      ...defaultVectorSymbolization.line,
      lineDasharray: [...defaultVectorSymbolization.line.lineDasharray],
      lineTranslate: [...defaultVectorSymbolization.line.lineTranslate],
    },
    fill: {
      ...defaultVectorSymbolization.fill,
      fillTranslate: [...defaultVectorSymbolization.fill.fillTranslate],
    },
  };
}

export function cloneVectorRenderer(
  renderer: VectorRenderer | undefined,
): VectorRenderer {
  if (!renderer || renderer.type === "single") {
    return {
      type: "single",
      templateId: renderer?.templateId,
      businessType: renderer?.businessType,
      updatedByUser: renderer?.updatedByUser ?? false,
    };
  }
  if (renderer.type === "graduated") {
    return {
      ...renderer,
      classes: renderer.classes.map((item) => ({ ...item })),
      defaultClass: { ...renderer.defaultClass },
    };
  }
  return {
    ...renderer,
    classes: renderer.classes.map((item) => ({
      ...item,
      values: [...item.values],
    })),
    defaultClass: {
      ...renderer.defaultClass,
      values: [...renderer.defaultClass.values],
    },
    normalizationNotes: [...(renderer.normalizationNotes ?? [])],
  };
}

export function isUniqueValueRenderer(
  renderer: VectorRenderer | undefined,
): renderer is UniqueValueRenderer {
  return renderer?.type === "uniqueValue";
}

export function isGraduatedRenderer(
  renderer: VectorRenderer | undefined,
): renderer is GraduatedRenderer {
  return renderer?.type === "graduated";
}

export function rasterSymbolizationFromRules(
  rules: Partial<RasterSymbolization> | Record<string, unknown> | undefined,
): RasterSymbolization {
  const raw = (rules ?? {}) as Partial<RasterSymbolization>;
  const defaultOpacity =
    raw.mode === "unique" ? 100 : defaultRasterSymbolization.opacity;
  return {
    ...defaultRasterSymbolization,
    ...raw,
    opacity: typeof raw.opacity === "number" ? raw.opacity : defaultOpacity,
    mode: raw.mode ?? defaultRasterSymbolization.mode,
    bands:
      Array.isArray(raw.bands) && raw.bands.length > 0
        ? raw.bands.map(Number)
        : [...defaultRasterSymbolization.bands],
    alphaBand:
      raw.alphaBand === null ||
      raw.alphaBand === "mask" ||
      typeof raw.alphaBand === "number"
        ? raw.alphaBand
        : defaultRasterSymbolization.alphaBand,
    nodata: {
      ...defaultRasterSymbolization.nodata,
      ...raw.nodata,
    },
    stretch: {
      ...defaultRasterSymbolization.stretch,
      ...raw.stretch,
      perBand: {
        ...defaultRasterSymbolization.stretch.perBand,
        ...raw.stretch?.perBand,
      },
    },
    uniqueValues: Array.isArray(raw.uniqueValues)
      ? raw.uniqueValues.map((item) => ({ ...item }))
      : defaultRasterSymbolization.uniqueValues.map((item) => ({ ...item })),
  };
}

export function cloneDefaultRasterSymbolization(): RasterSymbolization {
  return rasterSymbolizationFromRules(defaultRasterSymbolization);
}
