import { expect, it } from "vitest";
import type { GeoJsonFeatureCollection } from "../api/generated/types.gen";
import {
  defaultUniqueValueClass,
  type UniqueValueRenderer,
} from "../symbolization";
import {
  sharedComparisonMaps,
  sharedComparisonRenderer,
} from "./comparisonColors";
import { beforeReviewMap } from "./geologyReview.testFixtures";

function renderer(
  field: string,
  colors: Record<string, string>,
): UniqueValueRenderer {
  return {
    type: "uniqueValue",
    field,
    classes: Object.entries(colors).map(([value, color]) => ({
      ...defaultUniqueValueClass,
      id: value,
      label: value,
      values: [value],
      color,
    })),
    defaultClass: { ...defaultUniqueValueClass },
  };
}

function collection(
  colors: Record<string, string>,
  field = "name",
): GeoJsonFeatureCollection {
  return {
    type: "FeatureCollection",
    features: Object.entries(colors).map(([value, color]) => ({
      ...beforeReviewMap.features[0]!,
      id: value,
      properties: {
        [field]: value,
        fill_color: color,
        _review_classification_field: field,
        fill_opacity: 1,
        stroke_color: "#202938",
      },
    })),
  };
}

it("uses the result mapping unchanged, including pale and nearby library colors, without mutating sources", () => {
  const before = collection({
    ptw3: "#b98a5b",
    ptw1: "#b87943",
    old: "#ffdfa4",
  });
  const after = collection({ ptw3: "#ffdfa4", ptw1: "#ffca7b" });
  const snapshot = structuredClone([before, after]);
  const [left, right] = sharedComparisonMaps(before, after);
  expect(
    left.features.slice(0, 2).map((feature) => feature.properties.fill_color),
  ).toEqual(["#ffdfa4", "#ffca7b"]);
  expect(right).toEqual(after);
  expect(left.features[2]!.properties.fill_color).not.toBe("#ffdfa4");
  expect(sharedComparisonMaps(before, after)).toEqual([left, right]);
  expect([before, after]).toEqual(snapshot);
});

it("does not couple different classification fields or workflows without a result", () => {
  const before = collection({ old: "#b98a5b" }, "geo_sym");
  const after = collection({ old: "#ffdfa4" }, "name");
  expect(sharedComparisonMaps(before, after)).toEqual([before, after]);
  expect(sharedComparisonMaps(before, null)).toEqual([before, null]);
  const first = renderer("geo_sym", { old: "#b98a5b" });
  expect(
    sharedComparisonRenderer(first, renderer("name", { old: "#ffdfa4" })),
  ).toBe(first);
});

it("supplements input-only classes deterministically without changing result classes", () => {
  const before = renderer("name", {
    ptw3: "#b98a5b",
    old: "#ffdfa4",
    extra: "#ffdfa4",
  });
  const after = renderer("name", { ptw3: "#ffdfa4", ptw1: "#ffca7b" });
  const snapshot = structuredClone(after);
  const shared = sharedComparisonRenderer(before, after);
  expect(shared.classes.slice(0, 2)).toEqual(after.classes);
  expect(new Set(shared.classes.map((item) => item.color)).size).toBe(4);
  expect(
    sharedComparisonRenderer(
      { ...before, classes: [...before.classes].reverse() },
      after,
    ),
  ).toEqual(shared);
  expect(after).toEqual(snapshot);
});
