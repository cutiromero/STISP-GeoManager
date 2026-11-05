import type { GeoJsonFeatureCollection } from "../api/generated/types.gen";
import type { UniqueValueRenderer } from "../symbolization";
import { geologicalColor } from "./geologyReviewData";

type Collection = GeoJsonFeatureCollection;

function lab(color: string) {
  const channels = [1, 3, 5].map((offset) => {
    const value = parseInt(color.slice(offset, offset + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  const [red = 0, green = 0, blue = 0] = channels;
  const xyz = [
    (0.4124564 * red + 0.3575761 * green + 0.1804375 * blue) / 0.95047,
    0.2126729 * red + 0.7151522 * green + 0.072175 * blue,
    (0.0193339 * red + 0.119192 * green + 0.9503041 * blue) / 1.08883,
  ].map((value) =>
    value > (6 / 29) ** 3
      ? Math.cbrt(value)
      : value / (3 * (6 / 29) ** 2) + 4 / 29,
  );
  const [first = 0, second = 0, third = 0] = xyz;
  return [116 * second - 16, 500 * (first - second), 200 * (second - third)];
}

function brightness(point: number[]) {
  const lightness = point[0] ?? 0;
  return lightness > 8 ? ((lightness + 16) / 116) ** 3 : lightness / 903.3;
}

function supplement(value: string, used: string[], polygon: boolean) {
  let seed = 0;
  for (const character of value)
    seed = (Math.imul(seed, 31) + character.charCodeAt(0)) >>> 0;
  const labs = used.filter((color) => /^#[\da-f]{6}$/i.test(color)).map(lab);
  let best = "#64748b",
    distance = -1;
  for (let index = 0; index < 512; index++) {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    const color = `#${(seed & 0xffffff).toString(16).padStart(6, "0")}`;
    const point = lab(color);
    const luminance = brightness(point);
    const outline = brightness(lab("#202938"));
    if ((luminance + 0.05) / (outline + 0.05) < 1.25) continue;
    if (!polygon && 1.05 / (luminance + 0.05) < 3) continue;
    if (used.some((other) => other.toLowerCase() === color)) continue;
    const separation = Math.min(
      100,
      ...labs.map((other) =>
        Math.hypot(...point.map((component, axis) => component - other[axis]!)),
      ),
    );
    if (separation >= 12) return color;
    if (separation > distance) {
      best = color;
      distance = separation;
    }
  }
  return best;
}

export function sharedComparisonRenderer(
  before: UniqueValueRenderer,
  after: UniqueValueRenderer,
  polygon = true,
): UniqueValueRenderer {
  if (before.field !== after.field) return before;
  const renderer = structuredClone(after);
  const known = new Set(
    renderer.classes.flatMap((item) => item.values.map(String)),
  );
  const used = renderer.classes.map((item) => item.color);
  for (const item of [...before.classes].sort((first, second) =>
    [...first.values]
      .sort()
      .join("|")
      .localeCompare([...second.values].sort().join("|")),
  )) {
    const values = item.values.filter((value) => !known.has(String(value)));
    if (!values.length) continue;
    const color = supplement(values.map(String).join("|"), used, polygon);
    renderer.classes.push({ ...item, values, color });
    values.forEach((value) => known.add(String(value)));
    used.push(color);
  }
  return renderer;
}

export function sharedComparisonMaps(
  before: Collection,
  after: Collection | null,
): [Collection, Collection | null] {
  if (!after) return [before, after];
  const field = (data: Collection) => {
    const explicit = data.features[0]?.properties._review_classification_field;
    return typeof explicit === "string"
      ? explicit
      : ["class", "geo_sym", "name", "alt", "grade", "state"].find((key) =>
          data.features.some(
            (feature) => feature.properties[key] !== undefined,
          ),
        );
  };
  const key = field(after);
  const beforeField =
    before.features[0]?.properties._review_classification_field;
  if (
    !key ||
    (typeof beforeField === "string" && beforeField !== key) ||
    !before.features.some((feature) => feature.properties[key] !== undefined)
  )
    return [before, after];
  const propertiesByValue = (data: Collection) =>
    new Map(
      data.features.map((feature) => [
        String(feature.properties[key]),
        feature.properties,
      ]),
    );
  const beforeStyles = propertiesByValue(before);
  const styles = propertiesByValue(after);
  const renderer = (
    properties: ReturnType<typeof propertiesByValue>,
  ): UniqueValueRenderer => ({
    type: "uniqueValue",
    field: key,
    classes: [...properties.keys()].sort().map((value) => {
      const style = properties.get(value)!;
      return {
        id: value,
        values: [value],
        label: String(style.legend_label ?? value),
        color: String(style.fill_color ?? geologicalColor(value)),
        size: 5,
        iconImage: "",
        count: 0,
        visible: true,
      };
    }),
    defaultClass: {
      id: "other",
      values: [],
      label: "其他",
      color: "#64748b",
      size: 5,
      iconImage: "",
      count: 0,
      visible: true,
    },
  });
  const shared = sharedComparisonRenderer(
    renderer(beforeStyles),
    renderer(styles),
    [...before.features, ...after.features].every((feature) =>
      ["Polygon", "MultiPolygon"].includes(feature.geometry.type),
    ),
  );
  const colors = new Map(
    shared.classes.flatMap((item) =>
      item.values.map((value) => [String(value), item.color] as const),
    ),
  );
  const project = (data: Collection): Collection => ({
    ...data,
    features: data.features.map((feature) => {
      const value = String(feature.properties[key]);
      const style = styles.get(value) ?? after.features[0]?.properties;
      return {
        ...feature,
        properties: {
          ...feature.properties,
          _review_classification_field: key,
          fill_color: colors.get(value),
          legend_label:
            styles.get(value)?.legend_label ?? feature.properties.legend_label,
          fill_opacity: style?.fill_opacity ?? 0.95,
          stroke_color: style?.stroke_color ?? "#202938",
        },
      };
    }),
  });
  return [project(before), project(after)];
}
