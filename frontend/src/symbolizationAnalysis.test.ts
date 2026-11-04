import { describe, expect, it } from "vitest";
import {
  cloneDefaultVectorSymbolization,
  isUniqueValueRenderer,
} from "./symbolization";
import { vectorSymbolizationWithDefaultTemplate } from "./symbolizationTemplates";
import type {
  GeoJsonFeatureCollection,
  ResourceField,
  ResourceListItem,
} from "./types";

it("普通工作台优先使用资源默认name分类，保留手动样式", () => {
  const resource = { dataType: "vector" } as ResourceListItem;
  const geojson: GeoJsonFeatureCollection = {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: { name: "全新世冲积物qhal" },
        geometry: { type: "Polygon", coordinates: [] },
      },
    ],
  };
  const defaultVisualization = {
    symbolization: {
      opacity: 85,
      renderer: {
        type: "uniqueValue",
        field: "name",
        classes: [
          {
            value: "全新世冲积物qhal",
            label: "全新世冲积物qhal",
            color: "#ffffd8",
          },
        ],
        defaultClass: { color: "#cbd5e1" },
      },
    },
  };
  const result = vectorSymbolizationWithDefaultTemplate({
    resource,
    fields: [],
    geojson,
    defaultVisualization,
  });
  expect(result.renderer).toMatchObject({
    type: "uniqueValue",
    field: "name",
    classes: [
      {
        values: ["全新世冲积物qhal"],
        label: "全新世冲积物qhal",
        color: "#ffffd8",
        count: 1,
      },
    ],
  });
  const base = cloneDefaultVectorSymbolization();
  base.renderer = { type: "single", updatedByUser: true };
  expect(
    vectorSymbolizationWithDefaultTemplate({
      resource,
      fields: [],
      geojson,
      defaultVisualization,
      base,
    }).renderer,
  ).toEqual(base.renderer);
});

function styleFor(rows: Array<Record<string, unknown>>) {
  const fields: ResourceField[] = Object.keys(rows[0] ?? {}).map((name) => ({
    name,
    type: "String",
    nullable: true,
    sampleValues: [],
    description: name,
  }));
  const geojson = {
    type: "FeatureCollection",
    features: rows.map((properties, index) => ({
      type: "Feature",
      id: index + 1,
      properties,
      geometry: { type: "Point", coordinates: [87, 43] },
    })),
  } as GeoJsonFeatureCollection;
  const resource = {
    id: 1,
    name: "分析成果",
    code: "analysis",
    dataType: "vector",
  } as ResourceListItem;
  return { fields, geojson, resource };
}

function colors(rows: Array<Record<string, unknown>>) {
  const style = vectorSymbolizationWithDefaultTemplate(styleFor(rows));
  if (!isUniqueValueRenderer(style.renderer))
    throw Error("Expected result classification");
  return {
    style,
    renderer: style.renderer,
    values: Object.fromEntries(
      style.renderer.classes.flatMap((item) =>
        item.values.map((value) => [value, item.color]),
      ),
    ),
  };
}

describe("analysis result map styles", () => {
  it("colors priorities by actual ranking even when zone identities and row order differ", () => {
    const result = colors([
      { zone_id: "Z9", priority_rank: 3, priority_class: "low" },
      { zone_id: "Z1", priority_rank: 2, priority_class: "medium" },
      { zone_id: "Z4", priority_rank: 1, priority_class: "high" },
    ]);
    expect(result.renderer.field).toBe("priority_rank");
    expect(result.values).toEqual({
      "1": "#245A91",
      "2": "#E09A43",
      "3": "#A9CBE6",
    });
  });

  it("uses grey for a region whose valid coverage leaves it unranked", () => {
    const result = colors([
      { zone_id: "Z4", priority_rank: null, priority_class: "needs_data" },
      { zone_id: "Z9", priority_rank: 1, priority_class: "high" },
    ]);
    expect(result.renderer.defaultClass).toMatchObject({
      color: "#A2ADB8",
      count: 1,
    });
    expect(result.renderer.defaultClass.label).toContain("补资料");
  });

  it("distinguishes corrected, unchanged and pending geological features", () => {
    const result = colors([
      { check_status: "corrected" },
      { check_status: "unchanged" },
      { check_status: "needs_review" },
    ]);
    expect(result.values).toEqual({
      corrected: "#245A91",
      unchanged: "#BBCEDA",
      needs_review: "#E09A43",
    });
  });

  it("highlights recorded attribute changes while preserving blank unchanged objects", () => {
    const rows = [
      { change_fields: "contact_type, age" },
      { change_fields: "" },
    ];
    const original = structuredClone(rows);
    const result = colors(rows);
    expect(result.values["contact_type, age"]).toBe("#245A91");
    expect(result.renderer.defaultClass.count).toBe(1);
    expect(rows).toEqual(original);
  });

  it("classifies initial maps by their actual geological contact type", () => {
    const result = colors([
      { contact_type: "conformable" },
      { contact_type: "fault" },
      { contact_type: "unconformable" },
      { contact_type: "unknown" },
    ]);
    expect(result.values).toEqual({
      conformable: "#84B4D5",
      fault: "#E09A43",
      unconformable: "#8B86BE",
      unknown: "#A2ADB8",
    });
  });

  it("supports the Chinese contact labels used in the actual geological inputs", () => {
    expect(
      colors([
        { contact_type: "整合" },
        { contact_type: "断层" },
        { contact_type: "不整合" },
      ]).values,
    ).toEqual({ 整合: "#84B4D5", 断层: "#E09A43", 不整合: "#8B86BE" });
  });

  it("preserves a renderer customized by the user", () => {
    const input = styleFor([{ contact_type: "fault" }]);
    const base = colors([{ contact_type: "fault" }]).style;
    base.renderer!.updatedByUser = true;
    base.fill.fillColor = "#123456";
    expect(vectorSymbolizationWithDefaultTemplate({ ...input, base })).toEqual(
      base,
    );
  });

  it("leaves an unrelated generic resource unchanged", () => {
    expect(
      vectorSymbolizationWithDefaultTemplate(styleFor([{ sample: "soil" }])),
    ).toEqual(cloneDefaultVectorSymbolization());
  });
});
