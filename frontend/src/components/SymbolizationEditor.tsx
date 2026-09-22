import {
  Alert,
  App,
  Button,
  Card,
  ColorPicker,
  Divider,
  Input,
  InputNumber,
  Modal,
  Popover,
  Segmented,
  Select,
  Slider,
  Space,
  Spin,
  Switch,
  Tag,
  Tabs,
  Typography,
} from "antd";
import type { ReactNode } from "react";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import i18n, { currentLocale } from "../i18n";
import {
  defaultVectorSymbolization,
  normalizeSymbolIconImage,
  platformSymbolIconGroups,
  type Anchor,
  type CircleSymbolization,
  type ClusterSymbolization,
  type FillSymbolization,
  type GraduatedClassificationMethod,
  type GraduatedColorRamp,
  type GraduatedRenderer,
  type GraduatedSymbolClass,
  type HeatmapSymbolization,
  type LineSymbolization,
  type RasterSymbolization,
  type SymbolLayerSymbolization,
  type UniqueValueRenderer,
  type UniqueValueSymbolClass,
  type VectorSymbolization,
  isGraduatedRenderer,
  isUniqueValueRenderer,
} from "../symbolization";
import {
  buildGraduatedRenderer,
  buildUniqueValueRenderer,
  classValuesLabel,
  formatGraduatedRangeLabel,
  fieldValueOptions,
  germplasmDnaSexRenderer,
  germplasmDnaSexTemplateId,
  graduatedColorRamps,
  graduatedRangeLabel,
  numericValuesFromCounts,
  rebuildGraduatedRenderer,
  refreshGraduatedCounts,
  refreshUniqueValueCounts,
} from "../symbolizationTemplates";
import {
  parseRasterSymbolizationJson,
  parseVectorSymbolizationJson,
} from "../symbolizationImport";
import type {
  RasterBandMetadata,
  ResourceField,
  ResourceVisualizationSummary,
} from "../types";
import { copyText } from "../utils/clipboard";

const anchorOptions: Anchor[] = [
  "center",
  "left",
  "right",
  "top",
  "bottom",
  "top-left",
  "top-right",
  "bottom-left",
  "bottom-right",
];

type IconPickerGroup = {
  label: string;
  options: readonly { value: string; label: string }[];
};

type VectorExpressionMode = "single" | "uniqueValue" | "graduated" | "heatmap";
type RecommendedSymbolizationTemplate =
  ResourceVisualizationSummary["recommendedSymbolizations"][number];

const rgbBandLabels = ["R", "G", "B"] as const;
const heatmapPalettes = [
  {
    labelKey: "symbolization.paletteEcology",
    value: [
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
  {
    labelKey: "symbolization.paletteThermal",
    value: [
      "interpolate",
      ["linear"],
      ["heatmap-density"],
      0,
      "rgba(0, 0, 0, 0)",
      0.25,
      "#3b82f6",
      0.55,
      "#22c55e",
      0.78,
      "#facc15",
      1,
      "#ef4444",
    ],
  },
  {
    labelKey: "symbolization.paletteMono",
    value: [
      "interpolate",
      ["linear"],
      ["heatmap-density"],
      0,
      "rgba(0, 0, 0, 0)",
      0.35,
      "rgba(34, 197, 143, 0.35)",
      0.7,
      "rgba(34, 197, 143, 0.72)",
      1,
      "#eafff8",
    ],
  },
] as const;

const symbolizationLabels: Record<string, string> = {
  A: "Alpha 透明度",
  "circle-color": "圆点颜色",
  "circle-radius": "圆点半径",
  "circle-blur": "圆点模糊",
  "circle-opacity": "圆点不透明度",
  "circle-stroke-color": "圆点描边颜色",
  "circle-stroke-width": "圆点描边宽度",
  "circle-stroke-opacity": "圆点描边不透明度",
  "circle-pitch-alignment": "圆点俯仰对齐方式",
  "circle-pitch-scale": "圆点俯仰缩放基准",
  "circle-translate": "圆点平移偏移",
  "circle-translate-anchor": "圆点平移锚点",
  "circle-emissive-strength": "圆点自发光强度",
  "circle-sort-key": "圆点排序键",
  "symbol-placement": "符号放置方式",
  "symbol-spacing": "符号间距",
  "symbol-sort-key": "符号排序键",
  "symbol-z-order": "符号层级顺序",
  "symbol-avoid-edges": "避开瓦片边缘",
  "icon-image": "图标名称",
  "icon-size": "图标大小",
  "icon-size-scale-range": "图标缩放范围",
  "icon-anchor": "图标锚点",
  "icon-offset": "图标偏移",
  "icon-padding": "图标碰撞留白",
  "icon-rotate": "图标旋转角度",
  "icon-pitch-alignment": "图标俯仰对齐方式",
  "icon-rotation-alignment": "图标旋转对齐方式",
  "icon-text-fit": "图标适配文字",
  "icon-text-fit-padding": "图标适配文字留白",
  "icon-allow-overlap": "允许图标重叠",
  "icon-ignore-placement": "图标忽略避让",
  "icon-optional": "图标可选显示",
  "icon-keep-upright": "图标保持正向",
  "icon-color": "图标颜色",
  "icon-opacity": "图标不透明度",
  "icon-halo-color": "图标光晕颜色",
  "icon-halo-width": "图标光晕宽度",
  "icon-halo-blur": "图标光晕模糊",
  "icon-translate": "图标平移偏移",
  "icon-translate-anchor": "图标平移锚点",
  "icon-emissive-strength": "图标自发光强度",
  "icon-color-brightness-min": "图标最低亮度",
  "icon-color-brightness-max": "图标最高亮度",
  "icon-color-contrast": "图标对比度",
  "icon-color-saturation": "图标饱和度",
  "icon-occlusion-opacity": "图标遮挡不透明度",
  "text-field": "标注字段",
  "text-font": "标注字体",
  "text-size": "标注字号",
  "text-max-width": "标注最大宽度",
  "text-line-height": "标注行高",
  "text-letter-spacing": "标注字距",
  "text-justify": "标注对齐方式",
  "text-anchor": "标注锚点",
  "text-offset": "标注偏移",
  "text-radial-offset": "标注径向偏移",
  "text-variable-anchor": "标注可变锚点",
  "text-writing-mode": "标注书写方向",
  "text-padding": "标注碰撞留白",
  "text-rotate": "标注旋转角度",
  "text-pitch-alignment": "标注俯仰对齐方式",
  "text-rotation-alignment": "标注旋转对齐方式",
  "text-transform": "标注大小写转换",
  cluster: "点位聚合",
  "cluster-enabled": "启用点位聚合",
  "cluster-max-zoom": "聚合最大缩放级别",
  "cluster-radius": "聚合半径",
  "text-allow-overlap": "允许标注重叠",
  "text-ignore-placement": "标注忽略避让",
  "text-optional": "标注可选显示",
  "text-keep-upright": "标注保持正向",
  "text-color": "标注颜色",
  "text-opacity": "标注不透明度",
  "text-halo-color": "标注光晕颜色",
  "text-halo-width": "标注光晕宽度",
  "text-halo-blur": "标注光晕模糊",
  "text-translate": "标注平移偏移",
  "text-translate-anchor": "标注平移锚点",
  "text-emissive-strength": "标注自发光强度",
  "text-occlusion-opacity": "标注遮挡不透明度",
  "heatmap-weight": "热力权重",
  "heatmap-intensity": "热力强度",
  "heatmap-radius": "热力半径",
  "heatmap-opacity": "热力不透明度",
  "heatmap-color": "热力色带",
  "line-color": "线颜色",
  "line-width": "线宽",
  "line-opacity": "线不透明度",
  "line-blur": "线模糊",
  "line-cap": "线端点样式",
  "line-join": "线连接样式",
  "line-miter-limit": "斜接限制",
  "line-round-limit": "圆角限制",
  "line-offset": "线偏移",
  "line-gap-width": "线间隙宽度",
  "line-dasharray": "虚线数组",
  "line-translate": "线平移偏移",
  "line-translate-anchor": "线平移锚点",
  "line-emissive-strength": "线自发光强度",
  "fill-color": "填充颜色",
  "fill-opacity": "填充不透明度",
  "fill-outline-color": "填充描边颜色",
  "fill-antialias": "填充抗锯齿",
  "fill-sort-key": "填充排序键",
  "fill-translate": "填充平移偏移",
  "fill-translate-anchor": "填充平移锚点",
  "fill-emissive-strength": "填充自发光强度",
  "启用 nodata": "启用无数据值",
};

const symbolizationOptionLabels: Record<string, string> = {
  auto: "自动",
  map: "地图",
  viewport: "视口",
  center: "中心",
  left: "左侧",
  right: "右侧",
  top: "上方",
  bottom: "下方",
  "top-left": "左上",
  "top-right": "右上",
  "bottom-left": "左下",
  "bottom-right": "右下",
  point: "点",
  line: "沿线",
  "line-center": "线中心",
  "viewport-y": "视口 Y 轴",
  source: "数据源顺序",
  none: "无",
  width: "宽度",
  height: "高度",
  both: "宽高",
  horizontal: "水平",
  vertical: "垂直",
  uppercase: "大写",
  lowercase: "小写",
  butt: "平头",
  round: "圆头",
  square: "方头",
  bevel: "斜角",
  miter: "尖角",
  mask: "掩膜",
  poplar: "胡杨专题",
  viridis: "Viridis 连续色带",
  terrain: "地形色带",
  thermal: "热力色带",
};

function displaySymbolizationLabel(label: string) {
  if (currentLocale() === "en-US") {
    return label === "启用 nodata"
      ? i18n.t("symbolization.enableNoData")
      : label;
  }
  return symbolizationLabels[label] ?? label;
}

function displaySymbolizationOption(option: string) {
  if (currentLocale() === "en-US") return option;
  return symbolizationOptionLabels[option] ?? option;
}

function isNumericResourceField(field: ResourceField) {
  const type = field.type.toLowerCase();
  return (
    type.includes("int") ||
    type.includes("float") ||
    type.includes("double") ||
    type.includes("decimal") ||
    type.includes("number") ||
    type.includes("numeric") ||
    type.includes("real")
  );
}

function isPreferredGraduatedField(fieldName: string) {
  const normalized = fieldName.toLowerCase();
  return [
    "海拔",
    "高程",
    "ndvi",
    "盐分",
    "含盐",
    "salinity",
    "elevation",
    "altitude",
  ].some((keyword) => normalized.includes(keyword));
}

export function VectorSymbolizationEditor({
  value,
  fields,
  fieldValueCounts,
  geometryType,
  recommendedSymbolizations = [],
  recommendedSymbolizationsLoading = false,
  recommendedSymbolizationsError = null,
  readOnly = false,
  canApplyRecommendedSymbolizations = true,
  onChange,
  onApply,
}: {
  value: VectorSymbolization;
  fields: ResourceField[];
  fieldValueCounts?: Record<string, Record<string, number>>;
  geometryType?: string;
  recommendedSymbolizations?: ResourceVisualizationSummary["recommendedSymbolizations"];
  recommendedSymbolizationsLoading?: boolean;
  recommendedSymbolizationsError?: string | null;
  readOnly?: boolean;
  canApplyRecommendedSymbolizations?: boolean;
  onChange: (value: VectorSymbolization) => void;
  onApply?: () => void;
}) {
  useTranslation();
  const { message } = App.useApp();
  const [iconPickerOpen, setIconPickerOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [activeIconGroupLabel, setActiveIconGroupLabel] = useState<
    string | null
  >(null);

  const copyJson = useCallback(async () => {
    try {
      await copyText(JSON.stringify(value, null, 2));
      message.success(i18n.t("symbolization.jsonCopied"));
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : i18n.t("symbolization.copyFailed"),
      );
    }
  }, [value, message]);

  function importJson(text: string) {
    const imported = parseVectorSymbolizationJson(text, fields);
    let renderer = markRendererUpdated(imported.renderer);
    if (isUniqueValueRenderer(renderer) && fieldValueCounts?.[renderer.field]) {
      renderer = refreshUniqueValueCounts(
        renderer,
        countsForField(renderer.field),
      );
    }
    if (isGraduatedRenderer(renderer) && fieldValueCounts?.[renderer.field]) {
      const { values, nonNumericCount } = numericDataForField(renderer.field);
      renderer = refreshGraduatedCounts(renderer, values, nonNumericCount);
    }
    onChange({ ...imported, renderer });
    setImportOpen(false);
    message.success(i18n.t("symbolization.importedToEditor"));
  }
  function updateRoot<Key extends keyof VectorSymbolization>(
    key: Key,
    nextValue: VectorSymbolization[Key],
  ) {
    onChange({ ...value, [key]: nextValue });
  }

  function updateCircle<Key extends keyof CircleSymbolization>(
    key: Key,
    nextValue: CircleSymbolization[Key],
  ) {
    onChange({ ...value, circle: { ...value.circle, [key]: nextValue } });
  }

  function updateSymbol<Key extends keyof SymbolLayerSymbolization>(
    key: Key,
    nextValue: SymbolLayerSymbolization[Key],
  ) {
    onChange({ ...value, symbol: { ...value.symbol, [key]: nextValue } });
  }

  function updateLine<Key extends keyof LineSymbolization>(
    key: Key,
    nextValue: LineSymbolization[Key],
  ) {
    onChange({ ...value, line: { ...value.line, [key]: nextValue } });
  }

  function updateFill<Key extends keyof FillSymbolization>(
    key: Key,
    nextValue: FillSymbolization[Key],
  ) {
    onChange({ ...value, fill: { ...value.fill, [key]: nextValue } });
  }

  function updateHeatmap<Key extends keyof HeatmapSymbolization>(
    key: Key,
    nextValue: HeatmapSymbolization[Key],
  ) {
    onChange({ ...value, heatmap: { ...value.heatmap, [key]: nextValue } });
  }

  function updateCluster<Key extends keyof ClusterSymbolization>(
    key: Key,
    nextValue: ClusterSymbolization[Key],
  ) {
    onChange({
      ...value,
      cluster: {
        ...(value.cluster ?? defaultVectorSymbolization.cluster),
        [key]: nextValue,
      },
    });
  }

  function updateRenderer(renderer: VectorSymbolization["renderer"]) {
    onChange({ ...value, renderer });
  }

  function applyRecommendedSymbolization(
    template: RecommendedSymbolizationTemplate,
  ) {
    if (!canApplyRecommendedSymbolizations) return;
    const next = mergeRecommendedSymbolization(value, template);
    onChange(next);
    message.success(
      i18n.t("symbolization.recommendationApplied", { name: template.name }),
    );
  }

  function countsForField(fieldName: string) {
    return new Map(
      Object.entries(fieldValueCounts?.[fieldName] ?? {}).map(
        ([fieldValue, count]) => [fieldValue, Number(count)] as const,
      ),
    );
  }

  function numericDataForField(fieldName: string) {
    return numericValuesFromCounts(countsForField(fieldName));
  }

  function hasGermplasmSexField(fieldName: string) {
    return ["性别", "雌雄", "雌/雄"].some((name) => fieldName.includes(name));
  }

  function createRendererForField(fieldName: string): UniqueValueRenderer {
    const counts = countsForField(fieldName);
    if (hasGermplasmSexField(fieldName)) {
      return germplasmDnaSexRenderer(fieldName, counts);
    }
    return buildUniqueValueRenderer(
      fieldName,
      counts,
      selectedIconImage || value.symbol.iconImage,
    );
  }

  function updateUniqueRenderer(
    updater: (renderer: UniqueValueRenderer) => UniqueValueRenderer,
  ) {
    const current = isUniqueValueRenderer(value.renderer)
      ? value.renderer
      : createRendererForField(defaultClassifyField);
    const next = updater(current);
    updateRenderer({ ...next, updatedByUser: true });
  }

  function updateUniqueClass(
    classId: string,
    patch: Partial<UniqueValueSymbolClass>,
  ) {
    updateUniqueRenderer((renderer) => {
      const nextValues =
        patch.values?.map((item) => item.trim()).filter(Boolean) ?? null;
      const nextClasses = renderer.classes.map((item) => {
        if (item.id === classId) {
          return { ...item, ...patch, values: nextValues ?? item.values };
        }
        if (nextValues) {
          return {
            ...item,
            values: item.values.filter((raw) => !nextValues.includes(raw)),
          };
        }
        return item;
      });
      return refreshUniqueValueCounts(
        { ...renderer, classes: nextClasses },
        countsForField(renderer.field),
      );
    });
  }

  function updateDefaultUniqueClass(patch: Partial<UniqueValueSymbolClass>) {
    updateUniqueRenderer((renderer) => ({
      ...renderer,
      defaultClass: { ...renderer.defaultClass, ...patch, values: [] },
    }));
  }

  function changeUniqueField(fieldName: string) {
    const nextRenderer = createRendererForField(fieldName);
    onChange({
      ...value,
      pointMode: "symbol",
      renderer: { ...nextRenderer, updatedByUser: true },
      symbol: {
        ...value.symbol,
        iconImage: nextRenderer.classes[0]?.iconImage ?? value.symbol.iconImage,
      },
    });
  }

  function createGraduatedRendererForField(
    fieldName: string,
  ): GraduatedRenderer {
    const { values, nonNumericCount } = numericDataForField(fieldName);
    const renderer = buildGraduatedRenderer(fieldName, values, {
      iconImage: selectedIconImage || value.symbol.iconImage,
    });
    return refreshGraduatedCounts(renderer, values, nonNumericCount);
  }

  function rebuildGraduatedWith(
    renderer: GraduatedRenderer,
    patch: Partial<
      Pick<
        GraduatedRenderer,
        "field" | "method" | "classCount" | "colorRamp" | "precision"
      >
    >,
  ) {
    const nextField = patch.field ?? renderer.field;
    const { values, nonNumericCount } = numericDataForField(nextField);
    return refreshGraduatedCounts(
      rebuildGraduatedRenderer(renderer, values, patch),
      values,
      nonNumericCount,
    );
  }

  function updateGraduatedRenderer(
    updater: (renderer: GraduatedRenderer) => GraduatedRenderer,
  ) {
    const current = isGraduatedRenderer(value.renderer)
      ? value.renderer
      : createGraduatedRendererForField(defaultGraduatedField);
    const next = updater(current);
    updateRenderer({ ...next, updatedByUser: true });
  }

  function updateGraduatedClass(
    classId: string,
    patch: Partial<GraduatedSymbolClass>,
  ) {
    updateGraduatedRenderer((renderer) => {
      const nextRenderer = {
        ...renderer,
        classes: renderer.classes.map((item) =>
          item.id === classId ? { ...item, ...patch } : item,
        ),
      };
      const { values, nonNumericCount } = numericDataForField(renderer.field);
      return refreshGraduatedCounts(nextRenderer, values, nonNumericCount);
    });
  }

  function updateManualGraduatedRange(
    classId: string,
    key: "min" | "max",
    nextValue: number | null,
  ) {
    updateGraduatedRenderer((renderer) => {
      const precision = renderer.precision;
      const nextClasses = renderer.classes.map((item) => {
        if (item.id !== classId) return item;
        const oldAutoLabel = formatGraduatedRangeLabel(
          item.min ?? 0,
          item.max ?? 0,
          precision,
        );
        const nextItem = {
          ...item,
          [key]: typeof nextValue === "number" ? nextValue : item[key],
        };
        const shouldSyncLabel = !item.label || item.label === oldAutoLabel;
        return {
          ...nextItem,
          label: shouldSyncLabel
            ? formatGraduatedRangeLabel(
                nextItem.min ?? 0,
                nextItem.max ?? 0,
                precision,
              )
            : nextItem.label,
        };
      });
      const nextRenderer = { ...renderer, classes: nextClasses };
      const { values, nonNumericCount } = numericDataForField(renderer.field);
      return refreshGraduatedCounts(nextRenderer, values, nonNumericCount);
    });
  }

  function updateDefaultGraduatedClass(patch: Partial<GraduatedSymbolClass>) {
    updateGraduatedRenderer((renderer) => ({
      ...renderer,
      defaultClass: {
        ...renderer.defaultClass,
        ...patch,
        min: null,
        max: null,
      },
    }));
  }

  function changeGraduatedField(fieldName: string) {
    const nextRenderer = createGraduatedRendererForField(fieldName);
    onChange({
      ...value,
      pointMode: geometry.hasPoint ? "symbol" : value.pointMode,
      renderer: { ...nextRenderer, updatedByUser: true },
      symbol: {
        ...value.symbol,
        iconImage: nextRenderer.classes[0]?.iconImage ?? value.symbol.iconImage,
      },
    });
  }

  function changeExpressionMode(mode: VectorExpressionMode) {
    if (mode === "heatmap") {
      onChange({
        ...value,
        pointMode: "heatmap",
        renderer: { type: "single", updatedByUser: true },
        heatmap: {
          ...value.heatmap,
          heatmapWeight: 0.72,
          heatmapWeightField: "",
          heatmapWeightFieldMax: 1,
          heatmapIntensity: 0.9,
          heatmapRadius: 24,
          heatmapOpacity: 0.78,
          heatmapColor: [
            ...(heatmapPalettes[0]?.value ?? value.heatmap.heatmapColor),
          ],
        },
      });
      return;
    }
    if (mode === "graduated") {
      const nextRenderer = isGraduatedRenderer(value.renderer)
        ? (() => {
            const { values, nonNumericCount } = numericDataForField(
              value.renderer.field,
            );
            return refreshGraduatedCounts(
              value.renderer,
              values,
              nonNumericCount,
            );
          })()
        : createGraduatedRendererForField(defaultGraduatedField);
      onChange({
        ...value,
        pointMode: geometry.hasPoint ? "symbol" : value.pointMode,
        renderer: { ...nextRenderer, updatedByUser: true },
        symbol: {
          ...value.symbol,
          iconImage:
            nextRenderer.classes[0]?.iconImage ?? value.symbol.iconImage,
        },
      });
      return;
    }
    if (mode === "uniqueValue") {
      const nextRenderer = isUniqueValueRenderer(value.renderer)
        ? refreshUniqueValueCounts(
            value.renderer,
            countsForField(value.renderer.field),
          )
        : createRendererForField(defaultClassifyField);
      onChange({
        ...value,
        pointMode: "symbol",
        renderer: { ...nextRenderer, updatedByUser: true },
        symbol: {
          ...value.symbol,
          iconImage:
            nextRenderer.classes[0]?.iconImage ?? value.symbol.iconImage,
        },
      });
      return;
    }
    onChange({
      ...value,
      pointMode: value.pointMode === "heatmap" ? "circle" : value.pointMode,
      renderer: { type: "single", updatedByUser: true },
    });
  }

  function applyPreset(kind: "line" | "fill") {
    if (kind === "line") {
      onChange({
        ...value,
        line: {
          ...value.line,
          lineColor: "#2f7d62",
          lineWidth: 2.4,
          lineDasharray: [1, 0],
        },
      });
    } else {
      onChange({
        ...value,
        fill: {
          ...value.fill,
          fillColor: "#2f7d62",
          fillOpacity: 0.42,
          fillOutlineColor: "#f4cb68",
        },
      });
    }
  }

  const textFieldOptions = [
    { value: "", label: i18n.t("symbolization.hidden") },
    ...fields.map((field) => ({
      value: "{" + field.name + "}",
      label: field.name,
    })),
  ];
  const labelFieldOptions =
    value.symbol.textField &&
    !textFieldOptions.some((option) => option.value === value.symbol.textField)
      ? [
          { value: value.symbol.textField, label: value.symbol.textField },
          ...textFieldOptions,
        ]
      : textFieldOptions;
  const defaultLabelField =
    labelFieldOptions.find((option) => option.value)?.value ?? "";
  const labelEnabled = value.symbol.textField.trim().length > 0;
  const cluster = value.cluster ?? defaultVectorSymbolization.cluster;
  const selectedHeatmapWeightField = value.heatmap.heatmapWeightField ?? "";
  const heatmapWeightFieldOptions = [
    { value: "", label: i18n.t("symbolization.byPointCount") },
    ...fields.filter(isNumericResourceField).map((field) => ({
      value: field.name,
      label: field.description
        ? `${field.name} · ${field.description}`
        : field.name,
    })),
  ];
  const categoricalFieldOptions = fields
    .filter((field) => !isNumericResourceField(field))
    .map((field) => ({
      value: field.name,
      label: field.description
        ? `${field.name} · ${field.description}`
        : field.name,
    }));
  const fallbackClassifyField =
    categoricalFieldOptions[0]?.value ?? fields[0]?.name ?? "";
  const defaultClassifyField =
    categoricalFieldOptions.find((option) => hasGermplasmSexField(option.value))
      ?.value ?? fallbackClassifyField;
  const uniqueRenderer = isUniqueValueRenderer(value.renderer)
    ? refreshUniqueValueCounts(
        value.renderer,
        countsForField(value.renderer.field),
      )
    : null;
  const rawGraduatedRenderer = isGraduatedRenderer(value.renderer)
    ? value.renderer
    : null;
  const graduatedData = rawGraduatedRenderer
    ? numericDataForField(rawGraduatedRenderer.field)
    : null;
  const graduatedRenderer =
    rawGraduatedRenderer && graduatedData
      ? refreshGraduatedCounts(
          rawGraduatedRenderer,
          graduatedData.values,
          graduatedData.nonNumericCount,
        )
      : null;
  const expressionMode =
    value.pointMode === "heatmap"
      ? "heatmap"
      : uniqueRenderer
        ? "uniqueValue"
        : graduatedRenderer
          ? "graduated"
          : "single";
  const normalizedGeometry = (geometryType ?? "").toLowerCase();
  const geometryUnknown =
    !normalizedGeometry ||
    normalizedGeometry.includes("mixed") ||
    normalizedGeometry.includes("geometrycollection");
  const geometry = {
    hasPoint: geometryUnknown || normalizedGeometry.includes("point"),
    hasLine: geometryUnknown || normalizedGeometry.includes("line"),
    hasPolygon: geometryUnknown || normalizedGeometry.includes("polygon"),
  };
  const geometrySummary = geometryUnknown
    ? i18n.t("symbolization.autoExpression")
    : geometryType;
  const selectedIconImage =
    normalizeSymbolIconImage(value.symbol.iconImage).trim() ||
    defaultVectorSymbolization.symbol.iconImage;
  const selectedIconGroup = platformSymbolIconGroups.find((group) =>
    group.options.some((option) => option.value === selectedIconImage),
  );
  const selectedIconLabel =
    selectedIconGroup?.options.find(
      (option) => option.value === selectedIconImage,
    )?.label ?? selectedIconImage;
  const iconPickerGroups: IconPickerGroup[] = [
    ...(selectedIconGroup
      ? []
      : [
          {
            label: i18n.t("symbolization.currentIcon"),
            options: [{ value: selectedIconImage, label: selectedIconImage }],
          },
        ]),
    ...platformSymbolIconGroups,
  ];
  const resolvedActiveIconGroup =
    activeIconGroupLabel &&
    iconPickerGroups.some((group) => group.label === activeIconGroupLabel)
      ? activeIconGroupLabel
      : (selectedIconGroup?.label ?? iconPickerGroups[0]?.label ?? "");
  const currentHeatmapColor = JSON.stringify(value.heatmap.heatmapColor);
  const heatmapPaletteOptions: Array<{ label: string; value: string }> =
    heatmapPalettes.map((palette) => ({
      label: i18n.t(palette.labelKey),
      value: JSON.stringify(palette.value),
    }));
  if (
    !heatmapPaletteOptions.some(
      (option) => option.value === currentHeatmapColor,
    )
  ) {
    heatmapPaletteOptions.unshift({
      label: i18n.t("symbolization.currentPalette"),
      value: currentHeatmapColor,
    });
  }

  const visibleRecommendedSymbolizations = recommendedSymbolizations
    .filter((item) => item.matchStatus !== "unavailable")
    .slice(0, 4);
  const showRecommendedSection =
    readOnly ||
    recommendedSymbolizationsLoading ||
    Boolean(recommendedSymbolizationsError) ||
    visibleRecommendedSymbolizations.length > 0;

  type LinePattern = "solid" | "dash" | "dot";
  const dashHead = value.line.lineDasharray[0] ?? 1;
  const dashGap = value.line.lineDasharray[1] ?? 0;
  const linePattern: LinePattern =
    dashGap <= 0 ? "solid" : dashHead <= 1 ? "dot" : "dash";

  function updateLinePattern(pattern: LinePattern) {
    const nextDasharray: [number, number] =
      pattern === "solid" ? [1, 0] : pattern === "dash" ? [3, 2] : [1, 2];
    updateLine("lineDasharray", nextDasharray);
  }

  function updateLabelEnabled(enabled: boolean) {
    updateSymbol("textField", enabled ? defaultLabelField : "");
  }

  function updateLabelCollision(mode: "avoid" | "overlap") {
    const allowOverlap = mode === "overlap";
    onChange({
      ...value,
      symbol: {
        ...value.symbol,
        textAllowOverlap: allowOverlap,
        textIgnorePlacement: allowOverlap,
      },
    });
  }

  const uniqueFieldOptions =
    categoricalFieldOptions.length > 0
      ? categoricalFieldOptions
      : fields.map((field) => ({ value: field.name, label: field.name }));
  const uniqueValueOptions = uniqueRenderer
    ? fieldValueOptions(countsForField(uniqueRenderer.field))
    : [];
  const uniqueIconOptions = platformSymbolIconGroups.flatMap((group) =>
    group.options.map((option) => {
      const label = `${group.label} / ${option.label}`;
      return {
        value: option.value,
        label,
        title: label,
      };
    }),
  );
  const numericFieldOptions = fields
    .filter((field) => {
      if (isNumericResourceField(field)) return true;
      return numericDataForField(field.name).values.length > 0;
    })
    .map((field) => ({
      value: field.name,
      label: field.description
        ? `${field.name} · ${field.description}`
        : field.name,
    }));
  const graduatedFieldOptions =
    numericFieldOptions.length > 0
      ? numericFieldOptions
      : fields.map((field) => ({ value: field.name, label: field.name }));
  const defaultGraduatedField =
    graduatedFieldOptions.find((option) =>
      isPreferredGraduatedField(option.value),
    )?.value ??
    graduatedFieldOptions[0]?.value ??
    fields[0]?.name ??
    "";
  const graduatedRampOptions = Object.entries(graduatedColorRamps).map(
    ([rampKey, ramp]) => ({
      value: rampKey,
      label: (
        <span className="graduated-ramp-option">
          <span className="graduated-ramp-preview" aria-hidden="true">
            {ramp.colors.map((color) => (
              <i key={color} style={{ backgroundColor: color }} />
            ))}
          </span>
          <span>{ramp.label}</span>
        </span>
      ),
    }),
  );

  return (
    <Card
      className="symbolization-card symbolization-card-redesigned"
      size="small"
      title={
        <SymbolizationTitle
          title={i18n.t("symbolization.layerStyle")}
          onApply={readOnly ? undefined : onApply}
          onCopy={copyJson}
          onImport={readOnly ? undefined : () => setImportOpen(true)}
        />
      }
    >
      <Space orientation="vertical" className="full-width symbolization-stack">
        {showRecommendedSection && (
          <section className="symbolization-section recommended-symbolization-section">
            <div className="symbolization-section-head">
              <div>
                <Typography.Text strong>
                  {i18n.t("symbolization.recommendations")}
                </Typography.Text>
                <Typography.Text type="secondary">
                  {i18n.t("symbolization.recommendationsDescription")}
                </Typography.Text>
              </div>
            </div>
            {recommendedSymbolizationsLoading && (
              <div className="recommended-symbolization-loading">
                <Spin size="small" />
                <Typography.Text type="secondary">
                  {i18n.t("symbolization.loadingRecommendations")}
                </Typography.Text>
              </div>
            )}
            {recommendedSymbolizationsError && (
              <Alert
                type="warning"
                showIcon
                title={i18n.t("symbolization.recommendationUnavailable")}
                description={recommendedSymbolizationsError}
              />
            )}
            {visibleRecommendedSymbolizations.length > 0 && (
              <div className="recommended-symbolization-list">
                {visibleRecommendedSymbolizations.map((template) => (
                  <div
                    className="recommended-symbolization-item"
                    key={template.templateId}
                  >
                    <div className="recommended-symbolization-main">
                      <div className="recommended-symbolization-title-row">
                        <Typography.Text strong>
                          {template.name}
                        </Typography.Text>
                        <Space size={4}>
                          {template.isPrimary && (
                            <Tag color="green">
                              {i18n.t("symbolization.primary")}
                            </Tag>
                          )}
                          <Tag>
                            {recommendedRendererLabel(template.rendererType)}
                          </Tag>
                        </Space>
                      </div>
                      <Typography.Text type="secondary">
                        {template.primaryField
                          ? i18n.t("symbolization.primaryField", {
                              field: template.primaryField,
                            })
                          : i18n.t("symbolization.noPrimaryField")}
                      </Typography.Text>
                      <Typography.Paragraph
                        className="recommended-symbolization-description"
                        type="secondary"
                      >
                        {template.description}
                      </Typography.Paragraph>
                      {template.warnings.length > 0 && (
                        <Typography.Text type="warning">
                          {template.warnings[0]}
                        </Typography.Text>
                      )}
                      <div className="recommended-symbolization-preview">
                        {recommendedClassPreviews(template).map((item) => (
                          <span
                            className="recommended-symbolization-chip"
                            key={item.id}
                            title={item.label}
                          >
                            <i style={{ backgroundColor: item.color }} />
                            <span>{item.label}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                    {canApplyRecommendedSymbolizations ? (
                      <Button
                        size="small"
                        type={template.isPrimary ? "primary" : "default"}
                        onClick={() => applyRecommendedSymbolization(template)}
                      >
                        {i18n.t("symbolization.apply")}
                      </Button>
                    ) : (
                      <Tag color="blue">
                        {i18n.t("symbolization.previewOnly")}
                      </Tag>
                    )}
                  </div>
                ))}
              </div>
            )}
            {!recommendedSymbolizationsLoading &&
              !recommendedSymbolizationsError &&
              visibleRecommendedSymbolizations.length === 0 && (
                <Typography.Text type="secondary">
                  {i18n.t("symbolization.noRecommendations")}
                </Typography.Text>
              )}
          </section>
        )}

        {readOnly ? (
          <Alert
            type="info"
            showIcon
            title={i18n.t("symbolization.readOnlyTitle")}
            description={i18n.t("symbolization.readOnlyDescription")}
          />
        ) : (
          <>
            <section className="symbolization-section">
              <div className="symbolization-section-head">
                <div>
                  <Typography.Text strong>
                    {i18n.t("symbolization.expression")}
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    {i18n.t("symbolization.expressionDescription", {
                      geometry: geometrySummary,
                    })}
                  </Typography.Text>
                </div>
              </div>
              {(geometry.hasPoint ||
                geometry.hasLine ||
                geometry.hasPolygon) && (
                <ControlRow label={i18n.t("symbolization.fieldExpression")}>
                  <Segmented
                    block
                    value={expressionMode}
                    options={[
                      {
                        value: "single",
                        label: i18n.t("symbolization.single"),
                      },
                      {
                        value: "uniqueValue",
                        label: i18n.t("symbolization.unique"),
                      },
                      {
                        value: "graduated",
                        label: i18n.t("symbolization.graduated"),
                      },
                      ...(geometry.hasPoint
                        ? [
                            {
                              value: "heatmap",
                              label: i18n.t("symbolization.heatmap"),
                            },
                          ]
                        : []),
                    ]}
                    onChange={(mode) =>
                      changeExpressionMode(mode as VectorExpressionMode)
                    }
                  />
                </ControlRow>
              )}
              {geometry.hasPoint && expressionMode === "single" && (
                <ControlRow label={i18n.t("symbolization.pointSymbolType")}>
                  <Segmented
                    block
                    value={
                      value.pointMode === "heatmap" ? "circle" : value.pointMode
                    }
                    options={[
                      {
                        value: "circle",
                        label: i18n.t("symbolization.circleSymbol"),
                      },
                      {
                        value: "symbol",
                        label: i18n.t("symbolization.iconSymbol"),
                      },
                    ]}
                    onChange={(mode) =>
                      updateRoot(
                        "pointMode",
                        mode as VectorSymbolization["pointMode"],
                      )
                    }
                  />
                </ControlRow>
              )}
              {(geometry.hasLine || geometry.hasPolygon) && (
                <div className="symbolization-preset-grid">
                  {geometry.hasLine && (
                    <>
                      <Button
                        className="symbolization-preset-button"
                        onClick={() => applyPreset("line")}
                      >
                        <span>{i18n.t("symbolization.riverLine")}</span>
                        <small>
                          {i18n.t("symbolization.riverLineDescription")}
                        </small>
                      </Button>
                      <Button
                        className="symbolization-preset-button"
                        onClick={() => {
                          applyPreset("line");
                          updateLinePattern("dash");
                        }}
                      >
                        <span>{i18n.t("symbolization.dashedGuide")}</span>
                        <small>
                          {i18n.t("symbolization.dashedGuideDescription")}
                        </small>
                      </Button>
                    </>
                  )}
                  {geometry.hasPolygon && (
                    <>
                      <Button
                        className="symbolization-preset-button"
                        onClick={() => applyPreset("fill")}
                      >
                        <span>{i18n.t("symbolization.protectedArea")}</span>
                        <small>
                          {i18n.t("symbolization.protectedAreaDescription")}
                        </small>
                      </Button>
                      <Button
                        className="symbolization-preset-button"
                        onClick={() =>
                          onChange({
                            ...value,
                            fill: {
                              ...value.fill,
                              fillColor: "#8fb9d9",
                              fillOpacity: 0.36,
                              fillOutlineColor: "#174f46",
                            },
                          })
                        }
                      >
                        <span>{i18n.t("symbolization.zoningFill")}</span>
                        <small>
                          {i18n.t("symbolization.zoningFillDescription")}
                        </small>
                      </Button>
                    </>
                  )}
                </div>
              )}
            </section>

            {expressionMode === "uniqueValue" && uniqueRenderer && (
              <section className="symbolization-section unique-symbolization-section">
                <div className="symbolization-section-head">
                  <div>
                    <Typography.Text strong>
                      {i18n.t("symbolization.fieldClassification")}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      {i18n.t("symbolization.classificationDescription")}
                    </Typography.Text>
                  </div>
                  {uniqueRenderer.templateId === germplasmDnaSexTemplateId && (
                    <Tag color="green">
                      {i18n.t("symbolization.germplasmTemplate")}
                    </Tag>
                  )}
                </div>
                <Space
                  orientation="vertical"
                  className="full-width symbolization-stack"
                >
                  <ControlRow
                    label={i18n.t("symbolization.classificationField")}
                  >
                    <Select
                      className="full-width"
                      value={uniqueRenderer.field}
                      options={uniqueFieldOptions}
                      onChange={changeUniqueField}
                    />
                  </ControlRow>
                  {uniqueRenderer.normalizationNotes?.length ? (
                    <Alert
                      type="info"
                      showIcon
                      title={i18n.t("symbolization.mergedValues")}
                      description={uniqueRenderer.normalizationNotes.join(" ")}
                    />
                  ) : null}
                  <div className="unique-class-list">
                    {uniqueRenderer.classes.map((item) => (
                      <div className="unique-class-row" key={item.id}>
                        <div className="unique-class-preview">
                          <span
                            className="unique-class-swatch"
                            style={{ backgroundColor: item.color }}
                          />
                          <Switch
                            size="small"
                            checked={item.visible}
                            onChange={(visible) =>
                              updateUniqueClass(item.id, { visible })
                            }
                          />
                        </div>
                        <Input
                          className="unique-class-label"
                          value={item.label}
                          maxLength={24}
                          onChange={(event) =>
                            updateUniqueClass(item.id, {
                              label: event.target.value,
                            })
                          }
                        />
                        <Select
                          className="unique-class-values"
                          mode="tags"
                          value={item.values}
                          options={uniqueValueOptions}
                          placeholder={i18n.t("symbolization.includedValues")}
                          onChange={(values) =>
                            updateUniqueClass(item.id, { values })
                          }
                        />
                        <ColorPicker
                          value={item.color}
                          onChangeComplete={(color) =>
                            updateUniqueClass(item.id, {
                              color: color.toHexString(),
                            })
                          }
                        />
                        <Select
                          className="unique-class-icon"
                          value={item.iconImage}
                          showSearch
                          optionFilterProp="label"
                          popupMatchSelectWidth={false}
                          options={uniqueIconOptions}
                          onChange={(iconImage) =>
                            updateUniqueClass(item.id, { iconImage })
                          }
                        />
                        <InputNumber
                          className="unique-class-size"
                          aria-label={i18n.t("symbolization.iconScaleLabel", {
                            name: item.label,
                          })}
                          title={i18n.t("symbolization.iconScaleHelp")}
                          value={item.size}
                          min={0.2}
                          max={5}
                          step={0.05}
                          onChange={(size) =>
                            updateUniqueClass(item.id, {
                              size: typeof size === "number" ? size : 1,
                            })
                          }
                        />
                        <Typography.Text className="unique-class-count">
                          {i18n.t("symbolization.recordCount", {
                            count: item.count,
                          })}
                        </Typography.Text>
                      </div>
                    ))}
                    <div className="unique-class-row unique-class-row-default">
                      <div className="unique-class-preview">
                        <span
                          className="unique-class-swatch"
                          style={{
                            backgroundColor: uniqueRenderer.defaultClass.color,
                          }}
                        />
                        <Switch
                          size="small"
                          checked={uniqueRenderer.defaultClass.visible}
                          onChange={(visible) =>
                            updateDefaultUniqueClass({ visible })
                          }
                        />
                      </div>
                      <Input
                        className="unique-class-label"
                        value={uniqueRenderer.defaultClass.label}
                        maxLength={24}
                        onChange={(event) =>
                          updateDefaultUniqueClass({
                            label: event.target.value,
                          })
                        }
                      />
                      <Typography.Text className="unique-class-values-readonly">
                        {classValuesLabel(uniqueRenderer.defaultClass)}
                      </Typography.Text>
                      <ColorPicker
                        value={uniqueRenderer.defaultClass.color}
                        onChangeComplete={(color) =>
                          updateDefaultUniqueClass({
                            color: color.toHexString(),
                          })
                        }
                      />
                      <Select
                        className="unique-class-icon"
                        value={uniqueRenderer.defaultClass.iconImage}
                        showSearch
                        optionFilterProp="label"
                        popupMatchSelectWidth={false}
                        options={uniqueIconOptions}
                        onChange={(iconImage) =>
                          updateDefaultUniqueClass({ iconImage })
                        }
                      />
                      <InputNumber
                        className="unique-class-size"
                        aria-label={i18n.t("symbolization.iconScaleLabel", {
                          name: uniqueRenderer.defaultClass.label,
                        })}
                        title={i18n.t("symbolization.iconScaleHelp")}
                        value={uniqueRenderer.defaultClass.size}
                        min={0.2}
                        max={5}
                        step={0.05}
                        onChange={(size) =>
                          updateDefaultUniqueClass({
                            size: typeof size === "number" ? size : 1,
                          })
                        }
                      />
                      <Typography.Text className="unique-class-count">
                        {i18n.t("symbolization.recordCount", {
                          count: uniqueRenderer.defaultClass.count,
                        })}
                      </Typography.Text>
                    </div>
                  </div>
                </Space>
              </section>
            )}

            {expressionMode === "graduated" && graduatedRenderer && (
              <section className="symbolization-section unique-symbolization-section graduated-symbolization-section">
                <div className="symbolization-section-head">
                  <div>
                    <Typography.Text strong>
                      {i18n.t("symbolization.graduated")}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      {i18n.t("symbolization.graduatedDescription")}
                    </Typography.Text>
                  </div>
                </div>
                <Space
                  orientation="vertical"
                  className="full-width symbolization-stack"
                >
                  <ControlRow label={i18n.t("symbolization.graduatedField")}>
                    <Select
                      className="full-width"
                      value={graduatedRenderer.field}
                      options={graduatedFieldOptions}
                      onChange={changeGraduatedField}
                    />
                  </ControlRow>
                  <ControlRow label={i18n.t("symbolization.graduatedMethod")}>
                    <Segmented
                      block
                      value={graduatedRenderer.method}
                      options={[
                        {
                          value: "equalInterval",
                          label: i18n.t("symbolization.equalInterval"),
                        },
                        {
                          value: "quantile",
                          label: i18n.t("symbolization.quantile"),
                        },
                        {
                          value: "manual",
                          label: i18n.t("symbolization.custom"),
                        },
                      ]}
                      onChange={(method) =>
                        updateGraduatedRenderer((renderer) =>
                          rebuildGraduatedWith(renderer, {
                            method: method as GraduatedClassificationMethod,
                          }),
                        )
                      }
                    />
                  </ControlRow>
                  <div className="graduated-control-grid">
                    <ControlRow label={i18n.t("symbolization.classCount")}>
                      <InputNumber
                        className="full-width"
                        value={graduatedRenderer.classCount}
                        min={graduatedRenderer.method === "manual" ? 1 : 3}
                        max={graduatedRenderer.method === "manual" ? 24 : 9}
                        step={1}
                        onChange={(classCount) =>
                          updateGraduatedRenderer((renderer) =>
                            rebuildGraduatedWith(renderer, {
                              classCount:
                                typeof classCount === "number"
                                  ? classCount
                                  : renderer.classes.length || 5,
                            }),
                          )
                        }
                      />
                    </ControlRow>
                    <ControlRow label={i18n.t("symbolization.decimals")}>
                      <InputNumber
                        className="full-width"
                        value={graduatedRenderer.precision}
                        min={0}
                        max={6}
                        step={1}
                        onChange={(precision) =>
                          updateGraduatedRenderer((renderer) =>
                            rebuildGraduatedWith(renderer, {
                              precision:
                                typeof precision === "number" ? precision : 2,
                            }),
                          )
                        }
                      />
                    </ControlRow>
                  </div>
                  <ControlRow
                    label={
                      graduatedRenderer.method === "manual"
                        ? i18n.t("symbolization.newRamp")
                        : i18n.t("symbolization.colorRamp")
                    }
                  >
                    <Select
                      className="full-width"
                      value={graduatedRenderer.colorRamp}
                      options={graduatedRampOptions}
                      onChange={(colorRamp) =>
                        updateGraduatedRenderer((renderer) =>
                          rebuildGraduatedWith(renderer, {
                            colorRamp: colorRamp as GraduatedColorRamp,
                          }),
                        )
                      }
                    />
                  </ControlRow>
                  {graduatedRenderer.classes.length === 0 && (
                    <Alert
                      type="warning"
                      showIcon
                      title={i18n.t("symbolization.noNumericValues")}
                      description={i18n.t(
                        "symbolization.noNumericValuesDescription",
                      )}
                    />
                  )}
                  <div className="unique-class-list">
                    {graduatedRenderer.classes.map((item) => (
                      <div
                        className="unique-class-row graduated-class-row"
                        key={item.id}
                      >
                        <div className="unique-class-preview">
                          <span
                            className="unique-class-swatch"
                            style={{ backgroundColor: item.color }}
                          />
                          <Switch
                            size="small"
                            checked={item.visible}
                            onChange={(visible) =>
                              updateGraduatedClass(item.id, { visible })
                            }
                          />
                        </div>
                        <Input
                          className="unique-class-label"
                          value={item.label}
                          maxLength={32}
                          onChange={(event) =>
                            updateGraduatedClass(item.id, {
                              label: event.target.value,
                            })
                          }
                        />
                        {graduatedRenderer.method === "manual" ? (
                          <Space.Compact className="graduated-range-editor">
                            <InputNumber
                              value={item.min}
                              step={1}
                              onChange={(next) =>
                                updateManualGraduatedRange(
                                  item.id,
                                  "min",
                                  typeof next === "number" ? next : null,
                                )
                              }
                            />
                            <InputNumber
                              value={item.max}
                              step={1}
                              onChange={(next) =>
                                updateManualGraduatedRange(
                                  item.id,
                                  "max",
                                  typeof next === "number" ? next : null,
                                )
                              }
                            />
                          </Space.Compact>
                        ) : (
                          <Typography.Text
                            className="unique-class-values-readonly graduated-class-range"
                            title={graduatedRangeLabel(item)}
                          >
                            {graduatedRangeLabel(item)}
                          </Typography.Text>
                        )}
                        <ColorPicker
                          value={item.color}
                          onChangeComplete={(color) =>
                            updateGraduatedClass(item.id, {
                              color: color.toHexString(),
                            })
                          }
                        />
                        <Select
                          className="unique-class-icon"
                          value={item.iconImage}
                          showSearch
                          optionFilterProp="label"
                          popupMatchSelectWidth={false}
                          options={uniqueIconOptions}
                          onChange={(iconImage) =>
                            updateGraduatedClass(item.id, { iconImage })
                          }
                        />
                        <InputNumber
                          className="unique-class-size"
                          aria-label={i18n.t("symbolization.iconScaleLabel", {
                            name: item.label,
                          })}
                          title={i18n.t("symbolization.iconScaleHelp")}
                          value={item.size}
                          min={0.2}
                          max={5}
                          step={0.05}
                          onChange={(size) =>
                            updateGraduatedClass(item.id, {
                              size: typeof size === "number" ? size : 1,
                            })
                          }
                        />
                        <Typography.Text className="unique-class-count">
                          {i18n.t("symbolization.recordCount", {
                            count: item.count,
                          })}
                        </Typography.Text>
                      </div>
                    ))}
                    <div className="unique-class-row unique-class-row-default graduated-class-row">
                      <div className="unique-class-preview">
                        <span
                          className="unique-class-swatch"
                          style={{
                            backgroundColor:
                              graduatedRenderer.defaultClass.color,
                          }}
                        />
                        <Switch
                          size="small"
                          checked={graduatedRenderer.defaultClass.visible}
                          onChange={(visible) =>
                            updateDefaultGraduatedClass({ visible })
                          }
                        />
                      </div>
                      <Input
                        className="unique-class-label"
                        value={graduatedRenderer.defaultClass.label}
                        maxLength={24}
                        onChange={(event) =>
                          updateDefaultGraduatedClass({
                            label: event.target.value,
                          })
                        }
                      />
                      <Typography.Text className="unique-class-values-readonly graduated-class-range">
                        {graduatedRangeLabel(graduatedRenderer.defaultClass)}
                      </Typography.Text>
                      <ColorPicker
                        value={graduatedRenderer.defaultClass.color}
                        onChangeComplete={(color) =>
                          updateDefaultGraduatedClass({
                            color: color.toHexString(),
                          })
                        }
                      />
                      <Select
                        className="unique-class-icon"
                        value={graduatedRenderer.defaultClass.iconImage}
                        showSearch
                        optionFilterProp="label"
                        popupMatchSelectWidth={false}
                        options={uniqueIconOptions}
                        onChange={(iconImage) =>
                          updateDefaultGraduatedClass({ iconImage })
                        }
                      />
                      <InputNumber
                        className="unique-class-size"
                        aria-label={i18n.t("symbolization.iconScaleLabel", {
                          name: graduatedRenderer.defaultClass.label,
                        })}
                        title={i18n.t("symbolization.iconScaleHelp")}
                        value={graduatedRenderer.defaultClass.size}
                        min={0.2}
                        max={5}
                        step={0.05}
                        onChange={(size) =>
                          updateDefaultGraduatedClass({
                            size: typeof size === "number" ? size : 1,
                          })
                        }
                      />
                      <Typography.Text className="unique-class-count">
                        {i18n.t("symbolization.recordCount", {
                          count: graduatedRenderer.defaultClass.count,
                        })}
                      </Typography.Text>
                    </div>
                  </div>
                </Space>
              </section>
            )}

            <section className="symbolization-section">
              <div className="symbolization-section-head">
                <div>
                  <Typography.Text strong>
                    {i18n.t("symbolization.baseStyle")}
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    {i18n.t("symbolization.baseStyleDescription")}
                  </Typography.Text>
                </div>
              </div>
              <Space
                orientation="vertical"
                className="full-width symbolization-stack"
              >
                <ControlRow label={i18n.t("symbolization.layerOpacity")}>
                  <Slider
                    value={value.opacity}
                    min={5}
                    max={100}
                    onChange={(opacity) => updateRoot("opacity", opacity)}
                  />
                </ControlRow>

                {geometry.hasPoint &&
                  expressionMode === "single" &&
                  value.pointMode === "circle" && (
                    <>
                      <ColorField
                        label={i18n.t("symbolization.pointColor")}
                        value={value.circle.circleColor}
                        onChange={(next) => updateCircle("circleColor", next)}
                      />
                      <NumberField
                        label={i18n.t("symbolization.pointSize")}
                        value={value.circle.circleRadius}
                        min={2}
                        max={80}
                        step={0.5}
                        onChange={(next) => updateCircle("circleRadius", next)}
                      />
                      <ColorField
                        label={i18n.t("symbolization.strokeColor")}
                        value={value.circle.circleStrokeColor}
                        onChange={(next) =>
                          updateCircle("circleStrokeColor", next)
                        }
                      />
                      <NumberField
                        label={i18n.t("symbolization.strokeWidth")}
                        value={value.circle.circleStrokeWidth}
                        min={0}
                        max={20}
                        step={0.2}
                        onChange={(next) =>
                          updateCircle("circleStrokeWidth", next)
                        }
                      />
                    </>
                  )}

                {geometry.hasPoint &&
                  expressionMode === "single" &&
                  value.pointMode === "symbol" && (
                    <>
                      <ControlRow label={i18n.t("symbolization.iconType")}>
                        <Popover
                          trigger="click"
                          placement="bottomLeft"
                          arrow={false}
                          open={iconPickerOpen}
                          onOpenChange={(open) => {
                            setIconPickerOpen(open);
                            if (open) {
                              setActiveIconGroupLabel(resolvedActiveIconGroup);
                            }
                          }}
                          overlayClassName="symbol-icon-picker-popover"
                          content={
                            <div className="symbol-icon-picker-menu">
                              {iconPickerGroups.map((group) => {
                                const isActive =
                                  group.label === resolvedActiveIconGroup;
                                return (
                                  <div
                                    className={
                                      isActive
                                        ? "symbol-icon-picker-group is-active"
                                        : "symbol-icon-picker-group"
                                    }
                                    key={group.label}
                                  >
                                    <button
                                      type="button"
                                      className="symbol-icon-picker-group-button"
                                      aria-expanded={isActive}
                                      onClick={() =>
                                        setActiveIconGroupLabel(group.label)
                                      }
                                    >
                                      <span>{group.label}</span>
                                      <small>
                                        {i18n.t("symbolization.optionCount", {
                                          count: group.options.length,
                                        })}
                                      </small>
                                    </button>
                                    {isActive && (
                                      <div className="symbol-icon-picker-options">
                                        {group.options.map((option) => {
                                          const isSelected =
                                            option.value === selectedIconImage;
                                          return (
                                            <button
                                              type="button"
                                              key={option.value}
                                              className={
                                                isSelected
                                                  ? "symbol-icon-picker-option is-selected"
                                                  : "symbol-icon-picker-option"
                                              }
                                              aria-pressed={isSelected}
                                              onClick={() => {
                                                updateSymbol(
                                                  "iconImage",
                                                  option.value,
                                                );
                                                setActiveIconGroupLabel(
                                                  group.label,
                                                );
                                                setIconPickerOpen(false);
                                              }}
                                            >
                                              {option.label}
                                            </button>
                                          );
                                        })}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          }
                        >
                          <button
                            type="button"
                            className="symbol-icon-picker-trigger"
                            aria-haspopup="menu"
                            aria-expanded={iconPickerOpen}
                          >
                            <span className="symbol-icon-picker-value">
                              {selectedIconGroup
                                ? `${selectedIconGroup.label} / ${selectedIconLabel}`
                                : selectedIconLabel}
                            </span>
                            <span
                              className="symbol-icon-picker-caret"
                              aria-hidden
                            >
                              ▾
                            </span>
                          </button>
                        </Popover>
                      </ControlRow>
                      <ColorField
                        label={i18n.t("symbolization.iconColor")}
                        value={value.symbol.iconColor}
                        onChange={(next) => updateSymbol("iconColor", next)}
                      />
                      <NumberField
                        label={i18n.t("symbolization.iconSize")}
                        value={value.symbol.iconSize}
                        min={0.2}
                        max={5}
                        step={0.05}
                        onChange={(next) => updateSymbol("iconSize", next)}
                      />
                    </>
                  )}

                {geometry.hasPoint && value.pointMode === "heatmap" && (
                  <>
                    <Alert
                      type="info"
                      showIcon
                      title={
                        selectedHeatmapWeightField
                          ? i18n.t("symbolization.heatmapWeighted", {
                              field: selectedHeatmapWeightField,
                            })
                          : i18n.t("symbolization.heatmapByCount")
                      }
                    />
                    <ControlRow label={i18n.t("symbolization.weightField")}>
                      <Select
                        className="full-width"
                        value={selectedHeatmapWeightField}
                        options={heatmapWeightFieldOptions}
                        onChange={(next) =>
                          updateHeatmap("heatmapWeightField", next)
                        }
                      />
                    </ControlRow>
                    {selectedHeatmapWeightField && (
                      <NumberField
                        label={i18n.t("symbolization.weightMaximum")}
                        value={value.heatmap.heatmapWeightFieldMax ?? 1}
                        min={1}
                        max={100000}
                        step={1}
                        onChange={(next) =>
                          updateHeatmap("heatmapWeightFieldMax", next)
                        }
                      />
                    )}
                    <ControlRow label={i18n.t("symbolization.heatmapPalette")}>
                      <Select
                        className="full-width"
                        value={currentHeatmapColor}
                        options={heatmapPaletteOptions}
                        onChange={(next) =>
                          updateHeatmap("heatmapColor", JSON.parse(next))
                        }
                      />
                    </ControlRow>
                    <NumberField
                      label={i18n.t("symbolization.radius")}
                      value={value.heatmap.heatmapRadius ?? 24}
                      min={1}
                      max={80}
                      step={1}
                      onChange={(next) => updateHeatmap("heatmapRadius", next)}
                    />
                    <NumberField
                      label={i18n.t("symbolization.intensity")}
                      value={value.heatmap.heatmapIntensity ?? 0.9}
                      min={0}
                      max={3}
                      step={0.1}
                      onChange={(next) =>
                        updateHeatmap("heatmapIntensity", next)
                      }
                    />
                    <NumberField
                      label={i18n.t("symbolization.heatmapOpacity")}
                      value={value.heatmap.heatmapOpacity ?? 0.78}
                      min={0}
                      max={1}
                      step={0.05}
                      onChange={(next) => updateHeatmap("heatmapOpacity", next)}
                    />
                  </>
                )}

                {geometry.hasPoint && expressionMode === "single" && (
                  <ControlRow label={i18n.t("symbolization.clustering")}>
                    <Switch
                      checked={cluster.enabled}
                      checkedChildren={i18n.t("symbolization.on")}
                      unCheckedChildren={i18n.t("symbolization.off")}
                      onChange={(enabled) => updateCluster("enabled", enabled)}
                    />
                  </ControlRow>
                )}

                {geometry.hasLine && (
                  <>
                    <Divider className="symbolization-divider" />
                    <ColorField
                      label={i18n.t("symbolization.lineColor")}
                      value={value.line.lineColor}
                      onChange={(next) => updateLine("lineColor", next)}
                    />
                    <NumberField
                      label={i18n.t("symbolization.lineWidth")}
                      value={value.line.lineWidth}
                      min={0}
                      max={40}
                      step={0.2}
                      onChange={(next) => updateLine("lineWidth", next)}
                    />
                    <ControlRow label={i18n.t("symbolization.lineStyle")}>
                      <Segmented
                        block
                        value={linePattern}
                        options={[
                          {
                            value: "solid",
                            label: i18n.t("symbolization.solid"),
                          },
                          {
                            value: "dash",
                            label: i18n.t("symbolization.dashed"),
                          },
                          {
                            value: "dot",
                            label: i18n.t("symbolization.dotted"),
                          },
                        ]}
                        onChange={(next) =>
                          updateLinePattern(next as LinePattern)
                        }
                      />
                    </ControlRow>
                  </>
                )}

                {geometry.hasPolygon && (
                  <>
                    <Divider className="symbolization-divider" />
                    <ColorField
                      label={i18n.t("symbolization.fillColor")}
                      value={value.fill.fillColor}
                      onChange={(next) => updateFill("fillColor", next)}
                    />
                    <NumberField
                      label={i18n.t("symbolization.fillOpacity")}
                      value={value.fill.fillOpacity}
                      min={0}
                      max={1}
                      step={0.05}
                      onChange={(next) => updateFill("fillOpacity", next)}
                    />
                    <ColorField
                      label={i18n.t("symbolization.boundaryColor")}
                      value={value.fill.fillOutlineColor}
                      onChange={(next) => updateFill("fillOutlineColor", next)}
                    />
                  </>
                )}
              </Space>
            </section>

            {geometry.hasPoint && value.pointMode !== "heatmap" && (
              <section className="symbolization-section">
                <div className="symbolization-section-head">
                  <div>
                    <Typography.Text strong>
                      {i18n.t("symbolization.labels")}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      {i18n.t("symbolization.labelsDescription")}
                    </Typography.Text>
                  </div>
                </div>
                <Space
                  orientation="vertical"
                  className="full-width symbolization-stack"
                >
                  <ControlRow label={i18n.t("symbolization.showLabels")}>
                    <Switch
                      checked={labelEnabled}
                      disabled={!defaultLabelField && !labelEnabled}
                      onChange={updateLabelEnabled}
                    />
                  </ControlRow>
                  <ControlRow label={i18n.t("symbolization.labelField")}>
                    <Select
                      className="full-width"
                      disabled={!labelEnabled}
                      value={value.symbol.textField}
                      options={labelFieldOptions}
                      onChange={(next) => updateSymbol("textField", next)}
                    />
                  </ControlRow>
                  <NumberField
                    label={i18n.t("symbolization.fontSize")}
                    value={value.symbol.textSize}
                    min={8}
                    max={48}
                    step={1}
                    onChange={(next) => updateSymbol("textSize", next)}
                  />
                  <ColorField
                    label={i18n.t("symbolization.textColor")}
                    value={value.symbol.textColor}
                    onChange={(next) => updateSymbol("textColor", next)}
                  />
                  <ColorField
                    label={i18n.t("symbolization.strokeColor")}
                    value={value.symbol.textHaloColor}
                    onChange={(next) => updateSymbol("textHaloColor", next)}
                  />
                  <ControlRow label={i18n.t("symbolization.collisionStrategy")}>
                    <Segmented
                      block
                      value={
                        value.symbol.textAllowOverlap ? "overlap" : "avoid"
                      }
                      options={[
                        {
                          value: "avoid",
                          label: i18n.t("symbolization.avoid"),
                        },
                        {
                          value: "overlap",
                          label: i18n.t("symbolization.overlap"),
                        },
                      ]}
                      onChange={(next) =>
                        updateLabelCollision(next as "avoid" | "overlap")
                      }
                    />
                  </ControlRow>
                </Space>
              </section>
            )}

            <details className="symbolization-advanced">
              <summary>
                <span>{i18n.t("symbolization.advanced")}</span>
              </summary>
              <Space
                orientation="vertical"
                className="full-width symbolization-stack"
              >
                <Button size="small" onClick={copyJson}>
                  {i18n.t("symbolization.copySymbolizationJson")}
                </Button>

                {geometry.hasPoint && value.pointMode === "circle" && (
                  <>
                    <Typography.Text strong>
                      {i18n.t("symbolization.circleAdvanced")}
                    </Typography.Text>
                    <NumberField
                      label="circle-blur"
                      value={value.circle.circleBlur}
                      min={0}
                      max={1}
                      step={0.05}
                      onChange={(next) => updateCircle("circleBlur", next)}
                    />
                    <NumberField
                      label="circle-opacity"
                      value={value.circle.circleOpacity}
                      min={0}
                      max={1}
                      step={0.05}
                      onChange={(next) => updateCircle("circleOpacity", next)}
                    />
                    <NumberField
                      label="circle-sort-key"
                      value={value.circle.circleSortKey}
                      step={1}
                      onChange={(next) => updateCircle("circleSortKey", next)}
                    />
                    <Tuple2Field
                      label="circle-translate"
                      value={value.circle.circleTranslate}
                      onChange={(next) => updateCircle("circleTranslate", next)}
                    />
                  </>
                )}

                {geometry.hasPoint && value.pointMode === "symbol" && (
                  <>
                    <Typography.Text strong>
                      {i18n.t("symbolization.iconAdvanced")}
                    </Typography.Text>
                    <TextField
                      label="icon-image"
                      value={value.symbol.iconImage}
                      onChange={(next) => updateSymbol("iconImage", next)}
                    />
                    <SelectField
                      label="symbol-placement"
                      value={value.symbol.symbolPlacement}
                      options={["point", "line", "line-center"]}
                      onChange={(next) => updateSymbol("symbolPlacement", next)}
                    />
                    <NumberField
                      label="symbol-spacing"
                      value={value.symbol.symbolSpacing}
                      min={1}
                      step={1}
                      onChange={(next) => updateSymbol("symbolSpacing", next)}
                    />
                    <NumberField
                      label="icon-padding"
                      value={value.symbol.iconPadding}
                      min={0}
                      step={1}
                      onChange={(next) => updateSymbol("iconPadding", next)}
                    />
                    <NumberField
                      label="icon-rotate"
                      value={value.symbol.iconRotate}
                      min={-360}
                      max={360}
                      step={1}
                      onChange={(next) => updateSymbol("iconRotate", next)}
                    />
                    <SelectField
                      label="icon-anchor"
                      value={value.symbol.iconAnchor}
                      options={anchorOptions}
                      onChange={(next) => updateSymbol("iconAnchor", next)}
                    />
                    <Tuple2Field
                      label="icon-offset"
                      value={value.symbol.iconOffset}
                      onChange={(next) => updateSymbol("iconOffset", next)}
                    />
                    <Tuple4Field
                      label="icon-text-fit-padding"
                      value={value.symbol.iconTextFitPadding}
                      onChange={(next) =>
                        updateSymbol("iconTextFitPadding", next)
                      }
                    />
                    <BooleanField
                      label="icon-allow-overlap"
                      value={value.symbol.iconAllowOverlap}
                      onChange={(next) =>
                        updateSymbol("iconAllowOverlap", next)
                      }
                    />
                  </>
                )}

                {geometry.hasPoint && value.pointMode === "heatmap" && (
                  <>
                    <Typography.Text strong>
                      {i18n.t("symbolization.heatmapAdvanced")}
                    </Typography.Text>
                    <NumberField
                      label="heatmap-weight"
                      value={value.heatmap.heatmapWeight ?? 0.72}
                      min={0}
                      max={1}
                      step={0.05}
                      onChange={(next) => updateHeatmap("heatmapWeight", next)}
                    />
                  </>
                )}

                {geometry.hasPoint && value.pointMode !== "heatmap" && (
                  <>
                    <Divider className="symbolization-divider" />
                    <Typography.Text strong>
                      {i18n.t("symbolization.clusterAdvanced")}
                    </Typography.Text>
                    <BooleanField
                      label="cluster-enabled"
                      value={cluster.enabled}
                      onChange={(next) => updateCluster("enabled", next)}
                    />
                    {cluster.enabled && (
                      <>
                        <NumberField
                          label="cluster-max-zoom"
                          value={cluster.maxZoom}
                          min={0}
                          max={22}
                          step={1}
                          onChange={(next) => updateCluster("maxZoom", next)}
                        />
                        <NumberField
                          label="cluster-radius"
                          value={cluster.radius}
                          min={1}
                          max={200}
                          step={1}
                          onChange={(next) => updateCluster("radius", next)}
                        />
                      </>
                    )}
                    <Divider className="symbolization-divider" />
                    <Typography.Text strong>
                      {i18n.t("symbolization.labelAdvanced")}
                    </Typography.Text>
                    <TextListField
                      label="text-font"
                      value={value.symbol.textFont}
                      onChange={(next) => updateSymbol("textFont", next)}
                    />
                    <NumberField
                      label="text-max-width"
                      value={value.symbol.textMaxWidth}
                      min={0}
                      step={0.5}
                      onChange={(next) => updateSymbol("textMaxWidth", next)}
                    />
                    <Tuple2Field
                      label="text-offset"
                      value={value.symbol.textOffset}
                      onChange={(next) => updateSymbol("textOffset", next)}
                    />
                    <MultiSelectField
                      label="text-variable-anchor"
                      value={value.symbol.textVariableAnchor}
                      options={anchorOptions}
                      onChange={(next) =>
                        updateSymbol(
                          "textVariableAnchor",
                          next as SymbolLayerSymbolization["textVariableAnchor"],
                        )
                      }
                    />
                    <MultiSelectField
                      label="text-writing-mode"
                      value={value.symbol.textWritingMode}
                      options={["horizontal", "vertical"]}
                      onChange={(next) =>
                        updateSymbol(
                          "textWritingMode",
                          next as SymbolLayerSymbolization["textWritingMode"],
                        )
                      }
                    />
                    <NumberField
                      label="text-halo-width"
                      value={value.symbol.textHaloWidth}
                      min={0}
                      max={20}
                      step={0.5}
                      onChange={(next) => updateSymbol("textHaloWidth", next)}
                    />
                  </>
                )}

                {geometry.hasLine && (
                  <>
                    <Divider className="symbolization-divider" />
                    <Typography.Text strong>
                      {i18n.t("symbolization.lineAdvanced")}
                    </Typography.Text>
                    <NumberField
                      label="line-opacity"
                      value={value.line.lineOpacity}
                      min={0}
                      max={1}
                      step={0.05}
                      onChange={(next) => updateLine("lineOpacity", next)}
                    />
                    <SelectField
                      label="line-cap"
                      value={value.line.lineCap}
                      options={["butt", "round", "square"]}
                      onChange={(next) => updateLine("lineCap", next)}
                    />
                    <SelectField
                      label="line-join"
                      value={value.line.lineJoin}
                      options={["bevel", "round", "miter", "none"]}
                      onChange={(next) => updateLine("lineJoin", next)}
                    />
                    <Tuple2Field
                      label="line-dasharray"
                      value={value.line.lineDasharray}
                      onChange={(next) => updateLine("lineDasharray", next)}
                    />
                    <Tuple2Field
                      label="line-translate"
                      value={value.line.lineTranslate}
                      onChange={(next) => updateLine("lineTranslate", next)}
                    />
                  </>
                )}

                {geometry.hasPolygon && (
                  <>
                    <Divider className="symbolization-divider" />
                    <Typography.Text strong>
                      {i18n.t("symbolization.fillAdvanced")}
                    </Typography.Text>
                    <BooleanField
                      label="fill-antialias"
                      value={value.fill.fillAntialias}
                      onChange={(next) => updateFill("fillAntialias", next)}
                    />
                    <NumberField
                      label="fill-sort-key"
                      value={value.fill.fillSortKey}
                      step={1}
                      onChange={(next) => updateFill("fillSortKey", next)}
                    />
                    <Tuple2Field
                      label="fill-translate"
                      value={value.fill.fillTranslate}
                      onChange={(next) => updateFill("fillTranslate", next)}
                    />
                  </>
                )}
              </Space>
            </details>
          </>
        )}
      </Space>
      <SymbolizationImportDialog
        open={importOpen}
        kind={i18n.t("symbolization.vectorKind")}
        onCancel={() => setImportOpen(false)}
        onImport={importJson}
      />
    </Card>
  );
}

function mergeRecommendedSymbolization(
  current: VectorSymbolization,
  template: RecommendedSymbolizationTemplate,
): VectorSymbolization {
  const symbolization = template.symbolization as Partial<VectorSymbolization>;
  const renderer = symbolization.renderer
    ? markRendererUpdated(
        symbolization.renderer as VectorSymbolization["renderer"],
      )
    : current.renderer;
  return {
    ...current,
    ...symbolization,
    pointMode: symbolization.pointMode ?? current.pointMode,
    renderer,
    circle: {
      ...current.circle,
      ...symbolization.circle,
    },
    symbol: {
      ...current.symbol,
      ...symbolization.symbol,
    },
    heatmap: {
      ...current.heatmap,
      ...symbolization.heatmap,
    },
    cluster: {
      ...(current.cluster ?? defaultVectorSymbolization.cluster),
      ...symbolization.cluster,
    },
    line: {
      ...current.line,
      ...symbolization.line,
    },
    fill: {
      ...current.fill,
      ...symbolization.fill,
    },
  };
}

function markRendererUpdated(
  renderer: VectorSymbolization["renderer"],
): VectorSymbolization["renderer"] {
  if (!renderer) return renderer;
  return { ...renderer, updatedByUser: true };
}

function recommendedRendererLabel(
  rendererType: RecommendedSymbolizationTemplate["rendererType"],
) {
  if (rendererType === "uniqueValue") {
    return i18n.t("symbolization.rendererUnique");
  }
  if (rendererType === "graduated") {
    return i18n.t("symbolization.rendererGraduated");
  }
  return i18n.t("symbolization.rendererSingle");
}

function recommendedClassPreviews(template: RecommendedSymbolizationTemplate) {
  const renderer = (template.symbolization as Partial<VectorSymbolization>)
    .renderer as VectorSymbolization["renderer"];
  if (isUniqueValueRenderer(renderer)) {
    return [...renderer.classes, renderer.defaultClass]
      .filter((item) => item.visible)
      .slice(0, 5)
      .map((item) => ({
        id: item.id,
        label: item.label,
        color: item.color,
      }));
  }
  if (isGraduatedRenderer(renderer)) {
    return [...renderer.classes, renderer.defaultClass]
      .filter((item) => item.visible)
      .slice(0, 5)
      .map((item) => ({
        id: item.id,
        label: item.label,
        color: item.color,
      }));
  }
  const symbolization = template.symbolization as Partial<VectorSymbolization>;
  return [
    {
      id: "single",
      label: template.name,
      color:
        symbolization.circle?.circleColor ??
        symbolization.symbol?.iconColor ??
        "#2F7D62",
    },
  ];
}

export function RasterSymbolizationEditor({
  value,
  bands,
  onChange,
  onApply,
  onRestoreDefault,
  restoringDefault = false,
  datasetId,
}: {
  value: RasterSymbolization;
  bands: RasterBandMetadata[];
  onChange: (value: RasterSymbolization) => void;
  onApply?: () => void;
  onRestoreDefault?: () => void;
  restoringDefault?: boolean;
  datasetId?: number;
}) {
  useTranslation();
  const { message } = App.useApp();
  const [classifying, setClassifying] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const bandOptions = (
    bands.length > 0
      ? bands
      : [
          {
            band: 1,
            description: i18n.t("symbolization.bandDefault"),
            type: "Byte",
          } as RasterBandMetadata,
        ]
  ).map((band) => ({
    value: band.band,
    label: `${band.band} · ${band.description || band.type}`,
  }));
  const alphaBandOptions = [
    { value: "mask", label: i18n.t("symbolization.mask") },
    { value: "none", label: i18n.t("symbolization.noData") },
    ...bandOptions,
  ];
  const selectedBands =
    value.mode === "rgb"
      ? [value.bands[0] ?? 1, value.bands[1] ?? 1, value.bands[2] ?? 1]
      : [value.bands[0] ?? 1];
  const uniqueBand = selectedBands[0] ?? 1;
  const uniqueBandMeta = bands.find((band) => band.band === uniqueBand);
  const uniqueBandIsInteger = uniqueBandMeta
    ? isIntegerRasterBand(uniqueBandMeta)
    : true;

  function update(next: Partial<RasterSymbolization>) {
    onChange({ ...value, ...next });
  }

  function updateBand(index: number, band: number) {
    const nextBands =
      value.mode === "rgb"
        ? [value.bands[0] ?? 1, value.bands[1] ?? 1, value.bands[2] ?? 1]
        : [value.bands[0] ?? 1];
    nextBands[index] = band;
    update({ bands: nextBands });
  }

  function updateMode(mode: RasterSymbolization["mode"]) {
    const current = value.bands.length > 0 ? value.bands : [1];
    const nextBands =
      mode === "rgb"
        ? [
            current[0] ?? 1,
            current[1] ?? current[0] ?? 1,
            current[2] ?? current[1] ?? current[0] ?? 1,
          ]
        : [current[0] ?? 1];
    update({ mode, bands: nextBands });
  }

  const copyJson = useCallback(async () => {
    try {
      await copyText(JSON.stringify(value, null, 2));
      message.success(i18n.t("symbolization.jsonCopied"));
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : i18n.t("symbolization.copyFailed"),
      );
    }
  }, [value, message]);

  function importJson(text: string) {
    const imported = parseRasterSymbolizationJson(text, bands);
    onChange(imported);
    setImportOpen(false);
    message.success(i18n.t("symbolization.importedToEditor"));
  }

  async function classifyUniqueValues() {
    if (!datasetId) {
      message.warning(i18n.t("symbolization.missingRasterId"));
      return;
    }
    if (!uniqueBandIsInteger) {
      message.warning(i18n.t("symbolization.integerBandOnly"));
      return;
    }
    setClassifying(true);
    try {
      const result = await api.classifyRasterUniqueValues(
        datasetId,
        uniqueBand,
      );
      update({
        mode: "unique",
        bands: [uniqueBand],
        uniqueValues: result.items,
      });
      message.success(
        i18n.t("symbolization.classifiedValues", {
          count: result.items.length,
        }),
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : i18n.t("symbolization.classificationFailed"),
      );
    } finally {
      setClassifying(false);
    }
  }

  function updateStretchBand(
    band: number,
    key: "min" | "max",
    nextValue: number,
  ) {
    const bandKey = String(band);
    const current = value.stretch.perBand[bandKey] ?? { min: 0, max: 255 };
    update({
      stretch: {
        ...value.stretch,
        perBand: {
          ...value.stretch.perBand,
          [bandKey]: { ...current, [key]: nextValue },
        },
      },
    });
  }

  function updateUniqueColor(index: number, color: string) {
    update({
      uniqueValues: replaceRasterUniqueValueColor(
        value.uniqueValues,
        index,
        color,
      ),
    });
  }

  return (
    <Card
      className="symbolization-card"
      size="small"
      title={
        <SymbolizationTitle
          title={i18n.t("symbolization.rasterTitle")}
          onApply={onApply}
          onCopy={copyJson}
          onImport={() => setImportOpen(true)}
        />
      }
    >
      {onRestoreDefault ? (
        <Button
          block
          className="symbolization-restore-default"
          loading={restoringDefault}
          onClick={onRestoreDefault}
        >
          {i18n.t("symbolization.restoreDefault")}
        </Button>
      ) : null}
      <Tabs
        size="small"
        items={[
          {
            key: "render",
            label: i18n.t("symbolization.render"),
            children: (
              <Space
                orientation="vertical"
                className="full-width symbolization-stack"
              >
                <ControlRow label={i18n.t("symbolization.opacity")}>
                  <Slider
                    value={value.opacity}
                    min={5}
                    max={100}
                    onChange={(opacity) => update({ opacity })}
                  />
                </ControlRow>
                <ControlRow label={i18n.t("symbolization.mode")}>
                  <Segmented
                    block
                    value={value.mode}
                    options={[
                      {
                        value: "gray",
                        label: i18n.t("symbolization.grayscale"),
                      },
                      { value: "rgb", label: "RGB" },
                      {
                        value: "pseudocolor",
                        label: i18n.t("symbolization.pseudocolor"),
                      },
                      {
                        value: "unique",
                        label: i18n.t("symbolization.rendererUnique"),
                      },
                    ]}
                    onChange={(mode) =>
                      updateMode(mode as RasterSymbolization["mode"])
                    }
                  />
                </ControlRow>
                {selectedBands.map((band, index) => {
                  const label =
                    value.mode === "rgb"
                      ? (rgbBandLabels[index] ?? "band")
                      : i18n.t("symbolization.band");
                  return (
                    <ControlRow key={label} label={label}>
                      <Select
                        className="full-width"
                        value={band}
                        options={bandOptions}
                        onChange={(nextBand) => updateBand(index, nextBand)}
                      />
                    </ControlRow>
                  );
                })}
                {value.mode === "rgb" && (
                  <ControlRow label="A">
                    <Select
                      className="full-width"
                      value={value.alphaBand ?? "none"}
                      options={alphaBandOptions}
                      onChange={(nextBand) =>
                        update({
                          alphaBand:
                            nextBand === "none"
                              ? null
                              : (nextBand as RasterSymbolization["alphaBand"]),
                        })
                      }
                    />
                  </ControlRow>
                )}
                <BooleanField
                  label={i18n.t("symbolization.enableNoData")}
                  value={value.nodata.enabled}
                  onChange={(enabled) =>
                    update({ nodata: { ...value.nodata, enabled } })
                  }
                />
                {value.mode === "pseudocolor" && (
                  <SelectField
                    label={i18n.t("symbolization.palette")}
                    value={value.palette}
                    options={
                      ["poplar", "viridis", "terrain", "thermal"] as const
                    }
                    onChange={(palette) => update({ palette })}
                  />
                )}
              </Space>
            ),
          },
          {
            key: "stretch",
            label: i18n.t("symbolization.stretch"),
            children: (
              <Space
                orientation="vertical"
                className="full-width symbolization-stack"
              >
                <BooleanField
                  label={i18n.t("symbolization.enableStretch")}
                  value={value.stretch.enabled}
                  onChange={(enabled) =>
                    update({ stretch: { ...value.stretch, enabled } })
                  }
                />
                {Array.from(new Set(selectedBands)).map((band) => {
                  const stretch = value.stretch.perBand[String(band)] ?? {
                    min: 0,
                    max: 255,
                  };
                  return (
                    <Space.Compact key={band} className="full-width">
                      <Input
                        className="stretch-band-label"
                        value={i18n.t("symbolization.bandNumber", { band })}
                        disabled
                      />
                      <InputNumber
                        value={stretch.min}
                        step={1}
                        onChange={(next) =>
                          updateStretchBand(
                            band,
                            "min",
                            typeof next === "number" ? next : 0,
                          )
                        }
                      />
                      <InputNumber
                        value={stretch.max}
                        step={1}
                        onChange={(next) =>
                          updateStretchBand(
                            band,
                            "max",
                            typeof next === "number" ? next : 255,
                          )
                        }
                      />
                    </Space.Compact>
                  );
                })}
              </Space>
            ),
          },
          {
            key: "unique",
            label: i18n.t("symbolization.rendererUnique"),
            children: (
              <Space
                orientation="vertical"
                className="full-width symbolization-stack"
              >
                <ControlRow label={i18n.t("symbolization.classificationField")}>
                  <Select
                    className="full-width"
                    value={uniqueBand}
                    options={bandOptions}
                    onChange={(nextBand) =>
                      update({ mode: "unique", bands: [nextBand] })
                    }
                  />
                </ControlRow>
                {!uniqueBandIsInteger && (
                  <Alert
                    type="warning"
                    showIcon
                    title={i18n.t("symbolization.integerBandHelp")}
                  />
                )}
                <Button
                  block
                  loading={classifying}
                  disabled={!datasetId || !uniqueBandIsInteger}
                  onClick={classifyUniqueValues}
                >
                  {i18n.t("symbolization.classify")}
                </Button>
                {value.uniqueValues.length === 0 && (
                  <Typography.Text type="secondary">
                    {i18n.t("symbolization.classifyHint")}
                  </Typography.Text>
                )}
                {value.uniqueValues.map((item, index) => (
                  <ControlRow
                    key={item.value}
                    label={item.label || String(item.value)}
                  >
                    <ColorPicker
                      value={item.color}
                      showText
                      onChange={(color) =>
                        updateUniqueColor(
                          index,
                          rasterColorToHex8(color.toRgb()),
                        )
                      }
                    />
                  </ControlRow>
                ))}
              </Space>
            ),
          },
        ]}
      />
      <SymbolizationImportDialog
        open={importOpen}
        kind={i18n.t("symbolization.rasterKind")}
        onCancel={() => setImportOpen(false)}
        onImport={importJson}
      />
    </Card>
  );
}

export function replaceRasterUniqueValueColor(
  items: RasterSymbolization["uniqueValues"],
  index: number,
  color: string,
) {
  return items.map((item, itemIndex) =>
    itemIndex === index ? { ...item, color } : item,
  );
}

export function rasterColorToHex8({
  r,
  g,
  b,
  a,
}: {
  r: number;
  g: number;
  b: number;
  a?: number;
}) {
  const channels = [r, g, b, Math.round((a ?? 1) * 255)];
  return `#${channels
    .map((channel) =>
      Math.max(0, Math.min(255, Math.round(channel)))
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`;
}

function isIntegerRasterBand(band: RasterBandMetadata) {
  const type = band.type.toLowerCase();
  return (
    band.isInteger ||
    ((type.includes("int") || type.includes("byte")) && !type.includes("float"))
  );
}

function SymbolizationImportDialog({
  open,
  kind,
  onCancel,
  onImport,
}: {
  open: boolean;
  kind: string;
  onCancel: () => void;
  onImport: (text: string) => void;
}) {
  const [jsonText, setJsonText] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  function resetAndCancel() {
    setJsonText("");
    setValidationError(null);
    onCancel();
  }

  function submitImport() {
    try {
      onImport(jsonText);
      setJsonText("");
      setValidationError(null);
    } catch (error) {
      setValidationError(
        error instanceof Error
          ? error.message
          : i18n.t("symbolization.validationFailed"),
      );
    }
  }

  return (
    <Modal
      title={i18n.t("symbolization.importTitle", { kind })}
      open={open}
      rootClassName="symbolization-import-modal"
      width="min(640px, calc(100vw - 32px))"
      destroyOnHidden
      mask={{ closable: false }}
      onCancel={resetAndCancel}
      footer={
        <Space>
          <Button onClick={resetAndCancel}>{i18n.t("common.cancel")}</Button>
          <Button type="primary" onClick={submitImport}>
            {i18n.t("symbolization.validateAndImport")}
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" className="full-width" size="middle">
        <Alert
          type="info"
          showIcon
          title={i18n.t("symbolization.pasteTitle")}
          description={i18n.t("symbolization.pasteDescription")}
        />
        <Input.TextArea
          autoFocus
          aria-label={i18n.t("symbolization.jsonLabel")}
          value={jsonText}
          rows={12}
          placeholder={i18n.t("symbolization.jsonPlaceholder")}
          status={validationError ? "error" : undefined}
          onChange={(event) => {
            setJsonText(event.target.value);
            if (validationError) setValidationError(null);
          }}
        />
        {validationError && (
          <Alert
            type="error"
            showIcon
            title={i18n.t("symbolization.cannotImport")}
            description={validationError}
          />
        )}
      </Space>
    </Modal>
  );
}

function SymbolizationTitle({
  title,
  onApply,
  onCopy,
  onImport,
}: {
  title: string;
  onApply?: () => void;
  onCopy?: () => void;
  onImport?: () => void;
}) {
  return (
    <div className="symbolization-title">
      <span>{title}</span>
      <Space size={4} wrap>
        {onCopy && (
          <Button size="small" autoInsertSpace={false} onClick={onCopy}>
            {i18n.t("symbolization.copyJson")}
          </Button>
        )}
        {onImport && (
          <Button size="small" autoInsertSpace={false} onClick={onImport}>
            {i18n.t("symbolization.importJson")}
          </Button>
        )}
        {onApply && (
          <Button
            type="primary"
            size="small"
            autoInsertSpace={false}
            onClick={onApply}
          >
            {i18n.t("common.confirm")}
          </Button>
        )}
      </Space>
    </div>
  );
}

function ControlRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="symbolization-control-row">
      <span title={label}>{displaySymbolizationLabel(label)}</span>
      <div>{children}</div>
    </div>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onChange: (value: number) => void;
}) {
  return (
    <ControlRow label={label}>
      <InputNumber
        className="full-width"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(next) => onChange(typeof next === "number" ? next : 0)}
      />
    </ControlRow>
  );
}

function TextField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <ControlRow label={label}>
      <Input value={value} onChange={(event) => onChange(event.target.value)} />
    </ControlRow>
  );
}

function TextListField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string[];
  onChange: (value: string[]) => void;
}) {
  return (
    <ControlRow label={label}>
      <Select
        className="full-width"
        mode="tags"
        value={value}
        onChange={onChange}
      />
    </ControlRow>
  );
}

function ColorField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <ControlRow label={label}>
      <ColorPicker
        value={value}
        showText
        onChangeComplete={(color) => onChange(color.toHexString())}
      />
    </ControlRow>
  );
}

function SelectField<Option extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: Option;
  options: readonly Option[];
  onChange: (value: Option) => void;
}) {
  return (
    <ControlRow label={label}>
      <Select
        className="full-width"
        value={value}
        options={options.map((option) => ({
          value: option,
          label: displaySymbolizationOption(option),
        }))}
        onChange={onChange}
      />
    </ControlRow>
  );
}

function MultiSelectField<Option extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: Option[];
  options: readonly Option[];
  onChange: (value: Option[]) => void;
}) {
  return (
    <ControlRow label={label}>
      <Select
        className="full-width"
        mode="multiple"
        value={value}
        options={options.map((option) => ({
          value: option,
          label: displaySymbolizationOption(option),
        }))}
        onChange={onChange}
      />
    </ControlRow>
  );
}

function BooleanField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <ControlRow label={label}>
      <Switch checked={value} onChange={onChange} />
    </ControlRow>
  );
}

function Tuple2Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: [number, number];
  onChange: (value: [number, number]) => void;
}) {
  return (
    <ControlRow label={label}>
      <Space.Compact className="full-width">
        <InputNumber
          value={value[0]}
          onChange={(next) =>
            onChange([typeof next === "number" ? next : 0, value[1]])
          }
        />
        <InputNumber
          value={value[1]}
          onChange={(next) =>
            onChange([value[0], typeof next === "number" ? next : 0])
          }
        />
      </Space.Compact>
    </ControlRow>
  );
}

function Tuple4Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: [number, number, number, number];
  onChange: (value: [number, number, number, number]) => void;
}) {
  function update(index: number, next: number | null) {
    const tuple: [number, number, number, number] = [...value];
    tuple[index] = typeof next === "number" ? next : 0;
    onChange(tuple);
  }

  return (
    <ControlRow label={label}>
      <Space.Compact className="full-width">
        <InputNumber value={value[0]} onChange={(next) => update(0, next)} />
        <InputNumber value={value[1]} onChange={(next) => update(1, next)} />
        <InputNumber value={value[2]} onChange={(next) => update(2, next)} />
        <InputNumber value={value[3]} onChange={(next) => update(3, next)} />
      </Space.Compact>
    </ControlRow>
  );
}
