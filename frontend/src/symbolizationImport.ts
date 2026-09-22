import {
  defaultVectorSymbolization,
  type GraduatedRenderer,
  type GraduatedSymbolClass,
  type RasterSymbolization,
  type UniqueValueRenderer,
  type UniqueValueSymbolClass,
  type VectorRenderer,
  type VectorSymbolization,
} from "./symbolization";
import type { RasterBandMetadata, ResourceField } from "./types";

const maximumJsonLength = 2_000_000;
const vectorPointModes = new Set(["circle", "symbol", "heatmap"]);
const rasterModes = new Set(["gray", "rgb", "pseudocolor", "unique"]);
const rasterPalettes = new Set(["poplar", "viridis", "terrain", "thermal"]);
const graduatedMethods = new Set(["equalInterval", "quantile", "manual"]);
const graduatedColorRamps = new Set(["green", "blue", "orange", "purple"]);
const numericArrayPaths = new Set([
  "symbol.iconSizeScaleRange",
  "symbol.iconOffset",
  "symbol.iconTextFitPadding",
  "symbol.iconTranslate",
  "symbol.textOffset",
  "symbol.textTranslate",
  "line.lineDasharray",
  "line.lineTranslate",
  "fill.fillTranslate",
]);
const stringArrayPaths = new Set([
  "symbol.textFont",
  "symbol.textVariableAnchor",
  "symbol.textWritingMode",
]);
const fixedArrayLengths = new Map([
  ["symbol.iconSizeScaleRange", 2],
  ["symbol.iconOffset", 2],
  ["symbol.iconTextFitPadding", 4],
  ["symbol.iconTranslate", 2],
  ["symbol.textOffset", 2],
  ["symbol.textTranslate", 2],
  ["line.lineDasharray", 2],
  ["line.lineTranslate", 2],
  ["fill.fillTranslate", 2],
]);

type JsonRecord = Record<string, unknown>;

export function parseVectorSymbolizationJson(
  text: string,
  fields: ResourceField[] = [],
): VectorSymbolization {
  const source = parseJsonObject(text, "矢量");
  const result = validateVectorRoot(source);
  validateVectorFieldCompatibility(result, fields);
  return result;
}

export function parseRasterSymbolizationJson(
  text: string,
  availableBands: RasterBandMetadata[] = [],
): RasterSymbolization {
  const source = parseJsonObject(text, "栅格");
  const mode = enumValue(
    source.mode,
    rasterModes,
    "mode",
  ) as RasterSymbolization["mode"];
  const bands = numberArray(source.bands, "bands", true);
  const expectedBandCount = mode === "rgb" ? 3 : 1;
  if (bands.length !== expectedBandCount) {
    throw new Error(
      mode === "rgb"
        ? "RGB 方案必须且只能配置 3 个输出波段"
        : "当前栅格模式必须且只能配置 1 个输出波段",
    );
  }
  for (const [index, band] of bands.entries()) {
    if (!Number.isInteger(band) || band < 1) {
      throw new Error(`bands[${index}] 必须是大于 0 的整数`);
    }
  }

  const alphaBand = parseAlphaBand(source.alphaBand);
  const nodata = recordValue(source.nodata, "nodata");
  const stretch = recordValue(source.stretch, "stretch");
  if (stretch.type !== "minmax") {
    throw new Error("stretch.type 仅支持 minmax");
  }
  const perBand = parseStretchBands(stretch.perBand);
  const uniqueValues = parseRasterUniqueValues(source.uniqueValues);

  const result: RasterSymbolization = {
    opacity: rangedNumber(source.opacity, "opacity", 0, 100),
    mode,
    bands,
    alphaBand,
    nodata: {
      enabled: booleanValue(nodata.enabled, "nodata.enabled"),
    },
    stretch: {
      enabled: booleanValue(stretch.enabled, "stretch.enabled"),
      type: "minmax",
      perBand,
    },
    palette: enumValue(
      source.palette,
      rasterPalettes,
      "palette",
    ) as RasterSymbolization["palette"],
    uniqueValues,
  };

  validateRasterBandCompatibility(result, availableBands);
  if (result.mode === "unique" && result.uniqueValues.length === 0) {
    throw new Error("唯一值方案缺少 uniqueValues 分类色表");
  }
  return result;
}

function parseJsonObject(text: string, kind: "矢量" | "栅格"): JsonRecord {
  const normalized = text.trim();
  if (!normalized) {
    throw new Error("请先粘贴符号化方案 JSON");
  }
  if (normalized.length > maximumJsonLength) {
    throw new Error("符号化方案 JSON 超过 2 MB，无法导入");
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(normalized);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "JSON 语法错误";
    throw new Error(`JSON 格式无效：${detail}`);
  }
  if (!isRecord(parsed)) {
    throw new Error("符号化方案必须是 JSON 对象");
  }
  if (kind === "矢量" && !("pointMode" in parsed)) {
    throw new Error("该 JSON 不是完整的矢量符号化方案");
  }
  if (kind === "栅格" && !("mode" in parsed && "bands" in parsed)) {
    throw new Error("该 JSON 不是完整的栅格符号化方案");
  }
  return parsed;
}

function validateVectorRoot(source: JsonRecord): VectorSymbolization {
  const result: JsonRecord = {};
  for (const [key, templateValue] of Object.entries(
    defaultVectorSymbolization,
  )) {
    if (key === "renderer") continue;
    if (!(key in source)) {
      throw new Error(`缺少必填字段：${key}`);
    }
    result[key] = validateFromTemplate(source[key], templateValue, key);
  }
  const pointMode = enumValue(result.pointMode, vectorPointModes, "pointMode");
  const renderer = parseVectorRenderer(source.renderer);
  const symbolization = {
    ...result,
    opacity: rangedNumber(result.opacity, "opacity", 0, 100),
    pointMode,
    renderer,
  } as VectorSymbolization;
  validateVectorRanges(symbolization);
  return symbolization;
}

function validateFromTemplate(
  value: unknown,
  template: unknown,
  path: string,
): unknown {
  if (typeof template === "number") return numberValue(value, path);
  if (typeof template === "string") return stringValue(value, path);
  if (typeof template === "boolean") return booleanValue(value, path);
  if (Array.isArray(template)) {
    if (!Array.isArray(value)) throw new Error(`${path} 必须是数组`);
    const expectedLength = fixedArrayLengths.get(path);
    if (expectedLength !== undefined && value.length !== expectedLength) {
      throw new Error(`${path} 必须包含 ${expectedLength} 项`);
    }
    if (numericArrayPaths.has(path)) return numberArray(value, path);
    if (stringArrayPaths.has(path)) return stringArray(value, path);
    if (path === "heatmap.heatmapColor" && value.length === 0) {
      throw new Error("heatmap.heatmapColor 不能为空");
    }
    return cloneJsonValue(value);
  }
  if (isRecord(template)) {
    const source = recordValue(value, path);
    const result: JsonRecord = {};
    for (const [key, childTemplate] of Object.entries(template)) {
      const childPath = `${path}.${key}`;
      if (!(key in source)) {
        throw new Error(`缺少必填字段：${childPath}`);
      }
      result[key] = validateFromTemplate(source[key], childTemplate, childPath);
    }
    return result;
  }
  return cloneJsonValue(value);
}

function parseVectorRenderer(value: unknown): VectorRenderer {
  const source = recordValue(value, "renderer");
  const type = stringValue(source.type, "renderer.type");
  if (type === "single") {
    return {
      type,
      ...rendererMetadata(source),
    };
  }
  if (type === "uniqueValue") return parseUniqueValueRenderer(source);
  if (type === "graduated") return parseGraduatedRenderer(source);
  throw new Error(`renderer.type 不受支持：${type}`);
}

function parseUniqueValueRenderer(source: JsonRecord): UniqueValueRenderer {
  const classes = arrayValue(source.classes, "renderer.classes").map(
    (item, index) => parseUniqueValueClass(item, `renderer.classes[${index}]`),
  );
  if (classes.length === 0) {
    throw new Error("唯一值方案至少需要一个分类");
  }
  const normalizationNotes = source.normalizationNotes;
  return {
    type: "uniqueValue",
    field: nonEmptyString(source.field, "renderer.field"),
    ...rendererMetadata(source),
    classes,
    defaultClass: parseUniqueValueClass(
      source.defaultClass,
      "renderer.defaultClass",
    ),
    ...(normalizationNotes === undefined
      ? {}
      : {
          normalizationNotes: stringArray(
            normalizationNotes,
            "renderer.normalizationNotes",
          ),
        }),
  };
}

function parseUniqueValueClass(
  value: unknown,
  path: string,
): UniqueValueSymbolClass {
  const source = recordValue(value, path);
  return {
    id: nonEmptyString(source.id, `${path}.id`),
    label: nonEmptyString(source.label, `${path}.label`),
    values: stringArray(source.values, `${path}.values`),
    color: nonEmptyString(source.color, `${path}.color`),
    iconImage: nonEmptyString(source.iconImage, `${path}.iconImage`),
    size: positiveNumber(source.size, `${path}.size`),
    count: nonNegativeNumber(source.count, `${path}.count`),
    visible: booleanValue(source.visible, `${path}.visible`),
  };
}

function parseGraduatedRenderer(source: JsonRecord): GraduatedRenderer {
  const classes = arrayValue(source.classes, "renderer.classes").map(
    (item, index) => parseGraduatedClass(item, `renderer.classes[${index}]`),
  );
  if (classes.length === 0) {
    throw new Error("分级方案至少需要一个分类");
  }
  const classCount = positiveInteger(source.classCount, "renderer.classCount");
  if (classCount !== classes.length) {
    throw new Error("renderer.classCount 必须与实际分类数量一致");
  }
  return {
    type: "graduated",
    field: nonEmptyString(source.field, "renderer.field"),
    method: enumValue(
      source.method,
      graduatedMethods,
      "renderer.method",
    ) as GraduatedRenderer["method"],
    classCount,
    precision: nonNegativeInteger(source.precision, "renderer.precision"),
    colorRamp: enumValue(
      source.colorRamp,
      graduatedColorRamps,
      "renderer.colorRamp",
    ) as GraduatedRenderer["colorRamp"],
    ...rendererMetadata(source),
    classes,
    defaultClass: parseGraduatedClass(
      source.defaultClass,
      "renderer.defaultClass",
    ),
  };
}

function parseGraduatedClass(
  value: unknown,
  path: string,
): GraduatedSymbolClass {
  const source = recordValue(value, path);
  const minimum = nullableNumber(source.min, `${path}.min`);
  const maximum = nullableNumber(source.max, `${path}.max`);
  if (minimum !== null && maximum !== null && maximum < minimum) {
    throw new Error(`${path}.max 不能小于 min`);
  }
  return {
    id: nonEmptyString(source.id, `${path}.id`),
    label: nonEmptyString(source.label, `${path}.label`),
    min: minimum,
    max: maximum,
    color: nonEmptyString(source.color, `${path}.color`),
    iconImage: nonEmptyString(source.iconImage, `${path}.iconImage`),
    size: positiveNumber(source.size, `${path}.size`),
    count: nonNegativeNumber(source.count, `${path}.count`),
    visible: booleanValue(source.visible, `${path}.visible`),
  };
}

function rendererMetadata(source: JsonRecord) {
  return {
    ...(source.templateId === undefined
      ? {}
      : { templateId: stringValue(source.templateId, "renderer.templateId") }),
    ...(source.businessType === undefined
      ? {}
      : {
          businessType: stringValue(
            source.businessType,
            "renderer.businessType",
          ),
        }),
    ...(source.updatedByUser === undefined
      ? {}
      : {
          updatedByUser: booleanValue(
            source.updatedByUser,
            "renderer.updatedByUser",
          ),
        }),
  };
}

function validateVectorRanges(value: VectorSymbolization) {
  rangedNumber(value.circle.circleOpacity, "circle.circleOpacity", 0, 1);
  rangedNumber(
    value.circle.circleStrokeOpacity,
    "circle.circleStrokeOpacity",
    0,
    1,
  );
  rangedNumber(value.symbol.iconOpacity, "symbol.iconOpacity", 0, 1);
  rangedNumber(value.symbol.textOpacity, "symbol.textOpacity", 0, 1);
  rangedNumber(value.fill.fillOpacity, "fill.fillOpacity", 0, 1);
  rangedNumber(value.line.lineOpacity, "line.lineOpacity", 0, 1);
  rangedNumber(value.heatmap.heatmapOpacity, "heatmap.heatmapOpacity", 0, 1);
  positiveNumber(value.circle.circleRadius, "circle.circleRadius");
  positiveNumber(value.symbol.iconSize, "symbol.iconSize");
  nonNegativeNumber(value.line.lineWidth, "line.lineWidth");
  positiveInteger(value.cluster.radius, "cluster.radius");
}

function validateVectorFieldCompatibility(
  value: VectorSymbolization,
  fields: ResourceField[],
) {
  if (fields.length === 0) return;
  const available = new Set(fields.map((field) => field.name));
  const references = new Set<string>();
  if (
    value.renderer?.type === "uniqueValue" ||
    value.renderer?.type === "graduated"
  ) {
    references.add(value.renderer.field);
  }
  if (
    value.pointMode === "heatmap" &&
    value.heatmap.heatmapWeightField.trim()
  ) {
    references.add(value.heatmap.heatmapWeightField.trim());
  }
  if (value.symbol.textField.trim())
    references.add(value.symbol.textField.trim());
  const missing = [...references].filter((field) => !available.has(field));
  if (missing.length > 0) {
    throw new Error(`目标图层缺少方案引用的字段：${missing.join("、")}`);
  }
}

function parseStretchBands(value: unknown) {
  const source = recordValue(value, "stretch.perBand");
  const result: Record<string, { min: number; max: number }> = {};
  for (const [band, rawRange] of Object.entries(source)) {
    if (!/^\d+$/.test(band) || Number(band) < 1) {
      throw new Error(`stretch.perBand 的波段编号无效：${band}`);
    }
    const range = recordValue(rawRange, `stretch.perBand.${band}`);
    const minimum = numberValue(range.min, `stretch.perBand.${band}.min`);
    const maximum = numberValue(range.max, `stretch.perBand.${band}.max`);
    if (maximum <= minimum) {
      throw new Error(`stretch.perBand.${band}.max 必须大于 min`);
    }
    result[band] = { min: minimum, max: maximum };
  }
  return result;
}

function parseRasterUniqueValues(value: unknown) {
  return arrayValue(value, "uniqueValues").map((item, index) => {
    const path = `uniqueValues[${index}]`;
    const source = recordValue(item, path);
    return {
      value: integerValue(source.value, `${path}.value`),
      color: nonEmptyString(source.color, `${path}.color`),
      label: nonEmptyString(source.label, `${path}.label`),
    };
  });
}

function parseAlphaBand(value: unknown): RasterSymbolization["alphaBand"] {
  if (value === null || value === "mask") return value;
  return positiveInteger(value, "alphaBand");
}

function validateRasterBandCompatibility(
  value: RasterSymbolization,
  availableBands: RasterBandMetadata[],
) {
  if (availableBands.length === 0) return;
  const available = new Map(availableBands.map((band) => [band.band, band]));
  const referencedBands = [
    ...value.bands,
    ...(typeof value.alphaBand === "number" ? [value.alphaBand] : []),
  ];
  const missing = [...new Set(referencedBands)].filter(
    (band) => !available.has(band),
  );
  if (missing.length > 0) {
    throw new Error(`目标栅格缺少方案引用的波段：${missing.join("、")}`);
  }
  if (value.mode === "unique") {
    const selected = available.get(value.bands[0]!);
    if (selected && !isIntegerRasterBand(selected)) {
      throw new Error("唯一值方案只能应用到整型波段");
    }
  }
}

function isIntegerRasterBand(band: RasterBandMetadata) {
  const type = band.type.toLowerCase();
  return (
    band.isInteger ||
    ((type.includes("int") || type.includes("byte")) && !type.includes("float"))
  );
}

function enumValue(value: unknown, values: Set<string>, path: string) {
  const result = stringValue(value, path);
  if (!values.has(result)) {
    throw new Error(`${path} 的值不受支持：${result}`);
  }
  return result;
}

function recordValue(value: unknown, path: string): JsonRecord {
  if (!isRecord(value)) throw new Error(`${path} 必须是对象`);
  return value;
}

function arrayValue(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`${path} 必须是数组`);
  return value;
}

function stringValue(value: unknown, path: string): string {
  if (typeof value !== "string") throw new Error(`${path} 必须是字符串`);
  return value;
}

function nonEmptyString(value: unknown, path: string): string {
  const result = stringValue(value, path);
  if (!result.trim()) throw new Error(`${path} 不能为空`);
  return result;
}

function booleanValue(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${path} 必须是布尔值`);
  return value;
}

function numberValue(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${path} 必须是有限数值`);
  }
  return value;
}

function nullableNumber(value: unknown, path: string): number | null {
  return value === null ? null : numberValue(value, path);
}

function rangedNumber(
  value: unknown,
  path: string,
  minimum: number,
  maximum: number,
) {
  const result = numberValue(value, path);
  if (result < minimum || result > maximum) {
    throw new Error(`${path} 必须介于 ${minimum} 和 ${maximum} 之间`);
  }
  return result;
}

function positiveNumber(value: unknown, path: string) {
  const result = numberValue(value, path);
  if (result <= 0) throw new Error(`${path} 必须大于 0`);
  return result;
}

function nonNegativeNumber(value: unknown, path: string) {
  const result = numberValue(value, path);
  if (result < 0) throw new Error(`${path} 不能小于 0`);
  return result;
}

function integerValue(value: unknown, path: string) {
  const result = numberValue(value, path);
  if (!Number.isInteger(result)) throw new Error(`${path} 必须是整数`);
  return result;
}

function positiveInteger(value: unknown, path: string) {
  const result = integerValue(value, path);
  if (result < 1) throw new Error(`${path} 必须是大于 0 的整数`);
  return result;
}

function nonNegativeInteger(value: unknown, path: string) {
  const result = integerValue(value, path);
  if (result < 0) throw new Error(`${path} 不能小于 0`);
  return result;
}

function numberArray(value: unknown, path: string, allowEmpty = false) {
  const result = arrayValue(value, path).map((item, index) =>
    numberValue(item, `${path}[${index}]`),
  );
  if (!allowEmpty && result.length === 0) throw new Error(`${path} 不能为空`);
  return result;
}

function stringArray(value: unknown, path: string) {
  return arrayValue(value, path).map((item, index) =>
    stringValue(item, `${path}[${index}]`),
  );
}

function cloneJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(cloneJsonValue);
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.entries(value).map(([key, child]) => [key, cloneJsonValue(child)]),
    );
  }
  return value;
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
