import { describe, expect, it } from "vitest";
import type {
  GeoJsonFeatureCollection,
  QueryResponse,
  ResourceProfileResponse,
} from "../api/generated/types.gen";
import { isUniqueValueRenderer } from "../symbolization";
import type { LoadedLayerGroup, LoadedVectorLayer } from "../types";
import {
  createEmptyLayerGroup,
  createVectorLayerGroup,
} from "../utils/layerFactory";
import { resourceLayerKey } from "../utils/uniqueLoadedLayers";
import {
  comparisonGroupId,
  displayComparisonLayers,
  upsertComparisonLayer,
} from "./comparisonLayerGroups";
import { colorReviewMap } from "./geologyReviewData";
import type {
  ComparisonLayerPlacement,
  ComparisonRole,
} from "./geologyWorkbenchCompareData";
import {
  afterReviewMap,
  beforeReviewMap,
  reviewDifferences,
  reviewQuery,
} from "./geologyReview.testFixtures";

type Feature = GeoJsonFeatureCollection["features"][number];
const workflowId = "haide-workflow";
const collection = (features: Feature[]): GeoJsonFeatureCollection => ({
  type: "FeatureCollection",
  features,
});
const empty = collection([]);

it("蚀变分类在对比页和普通工作台沿用同一资源符号化与图例名称", () => {
  const data = collection(
    ["赤铁矿化", "绿泥石化"].map((alt, index) => ({
      ...beforeReviewMap.features[0]!,
      id: `mineral-${index}`,
      properties: { alt },
    })),
  );
  const resource = profile(601, "有效蚀变", data);
  resource.defaultVisualization = {
    symbolization: {
      renderer: {
        type: "uniqueValue",
        field: "alt",
        classes: [
          { id: "red", value: "赤铁矿化", label: "赤铁矿化", color: "#c84545" },
          {
            id: "green",
            value: "绿泥石化",
            label: "绿泥石化",
            color: "#35824b",
          },
        ],
        defaultClass: { label: "其他", color: "#64748b" },
      },
    },
  };
  const response = query(resource, data);
  const normal = createVectorLayerGroup(resource.resource, resource, response, {
    attributeFilters: [],
    spatialFilter: null,
  }).children[0] as LoadedVectorLayer;
  const comparison = upsertComparisonLayer(
    [],
    resource,
    response,
    placement(["after"], "矿物"),
  );
  const compared = vector(comparison, 601);
  expect(compared.symbolization.renderer).toEqual(
    normal.symbolization.renderer,
  );
  colorReviewMap(data, resource.defaultVisualization);
  expect(data.features.map((item) => item.properties.fill_color)).toEqual([
    "#c84545",
    "#35824b",
  ]);
  expect(data.features.map((item) => item.properties.legend_label)).toEqual([
    "赤铁矿化",
    "绿泥石化",
  ]);
});
function profile(
  id: number,
  name = `目录资源-${id}`,
  data = beforeReviewMap,
): ResourceProfileResponse {
  return {
    resource: {
      ...createEmptyLayerGroup(name).sourceResource,
      id,
      name,
      isQueryable: true,
    },
    fields: [],
    featureCount: data.features.length,
    geometryType: data.features[0]?.geometry.type ?? "Polygon",
    bounds: [98.4, 35.6, 98.45, 35.62],
  };
}
function query(
  resource: ResourceProfileResponse,
  data: GeoJsonFeatureCollection,
): QueryResponse {
  return {
    ...reviewQuery(resource.resource.id, data),
    resourceName: resource.resource.name,
  };
}
function placement(
  roles: ComparisonRole[],
  element = "地质图",
  task = workflowId,
): ComparisonLayerPlacement {
  return { workflowId: task, title: "海德乌拉综合推理", roles, element };
}
function add(
  groups: LoadedLayerGroup[],
  id: number,
  data: GeoJsonFeatureCollection,
  roles: ComparisonRole[],
  element = "地质图",
  name?: string,
) {
  const resource = profile(id, name, data);
  return upsertComparisonLayer(
    groups,
    resource,
    query(resource, data),
    placement(roles, element),
  );
}

it("对比图层不把默认按name分类的岩性覆盖为代号分类", () => {
  const resource = profile(101);
  resource.defaultVisualization = {
    symbolization: {
      renderer: {
        type: "uniqueValue",
        field: "name",
        classes: [{ value: "八宝山组", label: "八宝山组", color: "#ffffd8" }],
        defaultClass: { color: "#cbd5e1" },
      },
    },
  };
  const groups = upsertComparisonLayer(
    [],
    resource,
    query(resource, beforeReviewMap),
    placement(["before"], "岩性"),
  );
  const layer = groups
    .flatMap((group) => group.children)
    .find((item) => item.layerType === "vector") as LoadedVectorLayer;
  expect(layer.symbolization.renderer).toMatchObject({
    type: "uniqueValue",
    field: "name",
    classes: [{ label: "八宝山组", color: "#ffffd8", values: ["八宝山组"] }],
  });
});

it("干净构造使用统一线样式，有效蚀变按类型而非处理状态分类", () => {
  const faults = add(
    [],
    301,
    collection([feature({ line_id: "F1" })]),
    ["after"],
    "构造",
  );
  expect(vector(faults, 301).symbolization.renderer).toEqual({
    type: "single",
  });
  const alterations = add(
    [],
    302,
    collection([feature({ feature_id: "A1", alt: "赤铁矿化" })]),
    ["after"],
    "矿物",
  );
  expect(vector(alterations, 302).symbolization.renderer).toMatchObject({
    type: "uniqueValue",
    field: "alt",
    classes: [{ label: "赤铁矿化" }],
  });
});
function taskGroup(groups: LoadedLayerGroup[]) {
  const group = groups.find(
    (item) => item.id === comparisonGroupId(workflowId),
  );
  if (!group) throw new Error("任务图层组缺失");
  return group;
}
function vector(groups: LoadedLayerGroup[], id: number): LoadedVectorLayer {
  const layer = taskGroup(groups).children.find(
    (item) => item.sourceResource.id === id,
  );
  if (layer?.layerType !== "vector") throw new Error(`矢量图层缺失: ${id}`);
  return layer;
}
it("keeps orange changes and multi-element evidence above the opaque lithology on the ordinary map", () => {
  let groups = add([], 101, beforeReviewMap, ["before"], "岩性");
  groups = add(groups, 201, afterReviewMap, ["after"], "岩性");
  groups = add(groups, 203, beforeReviewMap, ["after"], "构造");
  groups = add(groups, 204, beforeReviewMap, ["after"], "构造交汇");
  groups = add(groups, 202, reviewDifferences, ["changes"], "修改范围");
  expect(
    taskGroup(groups)
      .children.filter((layer) => layer.visible)
      .map((layer) => layer.sourceResource.id),
  ).toEqual([202, 204, 203, 201]);
});
function feature(
  properties: Feature["properties"],
  id?: string | number,
): Feature {
  return {
    ...beforeReviewMap.features[0]!,
    ...(id === undefined ? { id: undefined } : { id }),
    properties,
  };
}

describe("upsertComparisonLayer", () => {
  it("moves the existing full resource into its task group and preserves unrelated and filtered layers", () => {
    const input = profile(101, "待检查地质图");
    const original = createVectorLayerGroup(
      input.resource,
      input,
      query(input, beforeReviewMap),
      { attributeFilters: [], spatialFilter: null },
    );
    const unrelatedProfile = profile(999, "用户原有调查点");
    const unrelated = createVectorLayerGroup(
      unrelatedProfile.resource,
      unrelatedProfile,
      query(unrelatedProfile, beforeReviewMap),
    );
    const filtered = createVectorLayerGroup(
      input.resource,
      input,
      query(input, beforeReviewMap),
      {
        attributeFilters: [{ field: "class", operator: "eq", value: "5" }],
        spatialFilter: null,
      },
    );
    filtered.id = "filtered-result";
    const manual = createEmptyLayerGroup("用户空图层组");
    const initial = [
      { ...original, children: [...original.children, ...unrelated.children] },
      filtered,
      manual,
    ];
    const saved = structuredClone(initial);
    const result = upsertComparisonLayer(
      initial,
      input,
      query(input, beforeReviewMap),
      placement(["before"]),
    );
    expect(initial).toEqual(saved);
    expect(vector(result, 101).id).toBe(original.children[0]!.id);
    expect(vector(result, 101).name).toBe(input.resource.name);
    expect(vector(result, 101).sourceResource).toEqual(input.resource);
    expect(
      result
        .flatMap((group) => group.children)
        .filter((layer) => resourceLayerKey(layer) === "resource:101"),
    ).toHaveLength(1);
    expect(result.find((group) => group.id === original.id)?.children).toEqual(
      unrelated.children,
    );
    expect(result.find((group) => group.id === filtered.id)).toEqual(filtered);
    expect(result.find((group) => group.id === manual.id)).toEqual(manual);
  });

  it("repeated registration refreshes actual features without duplicating layers or changing catalog names", () => {
    const resources = [
      profile(101, "待检查地质图"),
      profile(201, "修正后地质图"),
      profile(202, "实际修改范围"),
    ];
    const data = [beforeReviewMap, afterReviewMap, reviewDifferences];
    const roles: ComparisonRole[] = ["before", "after", "changes"];
    let groups: LoadedLayerGroup[] = [];
    for (const round of [1, 2, 3]) {
      resources.forEach((resource, index) => {
        const response = {
          ...query(resource, data[index]!),
          resourceName: `查询别名-${round}`,
        };
        groups = upsertComparisonLayer(
          groups,
          resource,
          response,
          placement([roles[index]!]),
        );
      });
    }
    expect(groups).toHaveLength(1);
    expect(taskGroup(groups).children).toHaveLength(3);
    for (const [index, resource] of resources.entries()) {
      const layer = vector(groups, resource.resource.id);
      expect(layer.name).toBe(resource.resource.name);
      expect(layer.sourceResource).toEqual(resource.resource);
      expect(layer.metadata.comparisonRoles).toBe(roles[index]);
      expect(layer.geojson).toEqual(data[index]);
    }
    const firstId = vector(groups, 201).id;
    const updated = collection([afterReviewMap.features[0]!]);
    groups = upsertComparisonLayer(
      groups,
      resources[1]!,
      query(resources[1]!, updated),
      placement(["after"]),
    );
    expect(vector(groups, 201).id).toBe(firstId);
    expect(vector(groups, 201).geojson).toEqual(updated);
    expect(taskGroup(groups).children).toHaveLength(3);
  });

  it("defaults to corrected layers after both versions are registered", () => {
    let groups = add([], 101, beforeReviewMap, ["before"]);
    groups = add(groups, 201, afterReviewMap, ["after"]);
    groups = add(groups, 202, reviewDifferences, ["changes"]);
    expect(vector(groups, 101).visible).toBe(false);
    expect(vector(groups, 201).visible).toBe(true);
    expect(vector(groups, 202).visible).toBe(true);
  });

  it.each(["岩性", "地质图"])(
    "uses each actual geo_sym color for %s without a class field",
    (element) => {
      const data = collection([
        feature({ geo_sym: "J2a", fill_color: "#37a7c4" }, "unit-a"),
        feature({ geo_sym: "Qh", fill_color: "#edcf8a" }, "unit-b"),
      ]);
      const groups = add([], 101, data, ["before"], element);
      const renderer = vector(groups, 101).symbolization.renderer;
      expect(isUniqueValueRenderer(renderer)).toBe(true);
      if (!isUniqueValueRenderer(renderer))
        throw new Error("未按真实地质符号分类");
      expect(renderer.field).toBe("geo_sym");
      expect(
        renderer.classes.map((item) => ({
          values: item.values,
          color: item.color,
          count: item.count,
        })),
      ).toEqual([
        { values: ["J2a"], color: "#37a7c4", count: 1 },
        { values: ["Qh"], color: "#edcf8a", count: 1 },
      ]);
    },
  );
});

describe("displayComparisonLayers", () => {
  it("switches before and after without changing full source data, while keeping matching changes visible", () => {
    let groups = add([], 101, beforeReviewMap, ["before"]);
    groups = add(groups, 201, afterReviewMap, ["after"]);
    groups = add(groups, 202, reviewDifferences, ["changes"]);
    const sourceData = new Map([
      [101, beforeReviewMap],
      [201, afterReviewMap],
      [202, reviewDifferences],
    ]);
    const after = displayComparisonLayers(
      groups,
      workflowId,
      "after",
      collection([reviewDifferences.features[1]!]),
      sourceData,
    );
    expect(vector(after, 101).visible).toBe(false);
    expect(vector(after, 201).visible).toBe(true);
    expect(vector(after, 202).visible).toBe(true);
    expect(vector(after, 202).geojson.features).toEqual([
      reviewDifferences.features[1],
    ]);
    const before = displayComparisonLayers(
      after,
      workflowId,
      "before",
      collection([reviewDifferences.features[0]!]),
      sourceData,
    );
    expect(vector(before, 101).visible).toBe(true);
    expect(vector(before, 201).visible).toBe(false);
    expect(vector(before, 202).geojson.features).toEqual([
      reviewDifferences.features[0],
    ]);
    expect(vector(before, 101).geojson).toEqual(beforeReviewMap);
    expect(vector(before, 201).geojson).toEqual(afterReviewMap);
    expect(sourceData.get(202)).toEqual(reviewDifferences);
  });

  it("keeps the input visible before correction outputs exist", () => {
    const groups = add([], 101, beforeReviewMap, ["before"]);
    const shown = displayComparisonLayers(
      groups,
      workflowId,
      "after",
      empty,
      new Map(),
    );
    expect(vector(shown, 101).visible).toBe(true);
  });

  const identities: Array<{
    name: string;
    original: Feature;
    selected: Feature;
    matches: boolean;
  }> = [
    {
      name: "明确相同issue_id",
      original: feature({ issue_id: "age", feature_id: "a" }),
      selected: feature({ issue_id: "age" }),
      matches: true,
    },
    {
      name: "同图斑不同issue_id",
      original: feature({ issue_id: "gap", feature_id: "a" }),
      selected: feature({ issue_id: "age", feature_id: "a" }),
      matches: false,
    },
    {
      name: "完整feature/rule/action",
      original: feature({
        feature_id: "a",
        rule_id: "age-rule",
        action: "set_age",
      }),
      selected: feature({
        feature_id: "a",
        rule_id: "age-rule",
        suggested_action: "set_age",
      }),
      matches: true,
    },
    {
      name: "同图斑不同规则",
      original: feature({
        feature_id: "a",
        rule_id: "coverage-rule",
        action: "set_age",
      }),
      selected: feature({
        feature_id: "a",
        rule_id: "age-rule",
        action: "set_age",
      }),
      matches: false,
    },
    {
      name: "同图斑同规则不同操作",
      original: feature({
        feature_id: "a",
        rule_id: "age-rule",
        action: "keep",
      }),
      selected: feature({
        feature_id: "a",
        rule_id: "age-rule",
        action: "set_age",
      }),
      matches: false,
    },
    {
      name: "无属性身份只有相同GeoJSON行id",
      original: feature({}, 1),
      selected: feature({}, 1),
      matches: false,
    },
    {
      name: "只有feature_id不构成修改身份",
      original: feature({ feature_id: "a" }),
      selected: feature({ feature_id: "a" }),
      matches: false,
    },
    {
      name: "缺少规则的feature/action",
      original: feature({ feature_id: "a", action: "set_age" }),
      selected: feature({ feature_id: "a", action: "set_age" }),
      matches: false,
    },
    {
      name: "空issue_id不构成修改身份",
      original: feature({ issue_id: "" }),
      selected: feature({ issue_id: "" }),
      matches: false,
    },
    {
      name: "完全没有身份的相同几何",
      original: feature({ old_value: "早白垩世" }),
      selected: feature({ old_value: "早白垩世" }),
      matches: false,
    },
  ];
  it.each(identities)(
    "filters highlights by $name",
    ({ original, selected, matches }) => {
      const source = collection([original]);
      const groups = add([], 202, source, ["changes"]);
      const shown = displayComparisonLayers(
        groups,
        workflowId,
        "after",
        collection([selected]),
        new Map([[202, source]]),
      );
      expect(vector(shown, 202).geojson.features).toEqual(
        matches ? [original] : [],
      );
    },
  );

  it("keeps another task and ordinary layers untouched when selecting the current task", () => {
    const resource = profile(999, "用户已有图层");
    const ordinary = createVectorLayerGroup(
      resource.resource,
      resource,
      query(resource, beforeReviewMap),
    );
    ordinary.visible = false;
    const anotherProfile = profile(888);
    const other = upsertComparisonLayer(
      [ordinary],
      anotherProfile,
      query(anotherProfile, beforeReviewMap),
      placement(["before"], "地质图", "other-workflow"),
    );
    const groups = add(other, 101, beforeReviewMap, ["before"]);
    const shown = displayComparisonLayers(
      groups,
      workflowId,
      "after",
      empty,
      new Map(),
    );
    expect(shown.find((group) => group.id === ordinary.id)).toBe(
      groups.find((group) => group.id === ordinary.id),
    );
    expect(
      shown.find((group) => group.id === comparisonGroupId("other-workflow")),
    ).toBe(
      groups.find((group) => group.id === comparisonGroupId("other-workflow")),
    );
  });
});

it("groups twelve Haide resources once, including a shared before/after source and three real change outputs", () => {
  const lithology = collection(
    beforeReviewMap.features.map((item, index) => ({
      ...item,
      properties: {
        geo_sym: index ? "Qh" : "J2a",
        fill_color: index ? "#edcf8a" : "#37a7c4",
      },
    })),
  );
  const fault = collection([
    {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [98.4, 35.6],
          [98.45, 35.62],
        ],
      },
      properties: { feature_id: "fault-a", state: "keep" },
    },
  ]);
  const minerals = collection([
    feature({ feature_id: "mineral-a", state: "keep" }),
  ]);
  const intersections = collection([
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [98.42, 35.61] },
      properties: { feature_id: "cross-a", state: "review" },
    },
  ]);
  const prospects = collection([
    feature({ feature_id: "prospect-a", grade: "A" }),
  ]);
  const definitions: Array<{
    id: number;
    name: string;
    roles: ComparisonRole[];
    element: string;
    data: GeoJsonFeatureCollection;
  }> = [
    {
      id: 1101,
      name: "海德乌拉_初始岩性识别",
      roles: ["before"],
      element: "岩性",
      data: lithology,
    },
    {
      id: 1201,
      name: "海德乌拉_岩性归并结果",
      roles: ["after"],
      element: "岩性",
      data: lithology,
    },
    {
      id: 1102,
      name: "海德乌拉_构造识别",
      roles: ["before", "after"],
      element: "构造",
      data: fault,
    },
    {
      id: 1103,
      name: "海德乌拉_原始矿物状态",
      roles: ["before"],
      element: "矿物",
      data: minerals,
    },
    {
      id: 1203,
      name: "海德乌拉_修正矿物状态",
      roles: ["after"],
      element: "矿物",
      data: minerals,
    },
    {
      id: 1104,
      name: "海德乌拉_原始交汇点",
      roles: ["before"],
      element: "构造交汇",
      data: intersections,
    },
    {
      id: 1204,
      name: "海德乌拉_修正交汇点",
      roles: ["after"],
      element: "构造交汇",
      data: intersections,
    },
    {
      id: 1105,
      name: "海德乌拉_原始调查建议",
      roles: ["before"],
      element: "调查建议",
      data: prospects,
    },
    {
      id: 1205,
      name: "海德乌拉_修正调查建议",
      roles: ["after"],
      element: "调查建议",
      data: prospects,
    },
    {
      id: 1301,
      name: "海德乌拉_岩性实际修改",
      roles: ["changes"],
      element: "修改范围",
      data: collection([feature({ issue_id: "lithology-change" })]),
    },
    {
      id: 1302,
      name: "海德乌拉_构造实际修改",
      roles: ["changes"],
      element: "修改范围",
      data: collection([feature({ issue_id: "fault-change" })]),
    },
    {
      id: 1303,
      name: "海德乌拉_矿物实际修改",
      roles: ["changes"],
      element: "修改范围",
      data: collection([feature({ issue_id: "mineral-change" })]),
    },
  ];
  let groups: LoadedLayerGroup[] = [];
  for (const _round of [1, 2]) {
    for (const item of definitions)
      groups = add(
        groups,
        item.id,
        item.data,
        item.roles,
        item.element,
        item.name,
      );
  }
  expect(groups).toHaveLength(1);
  expect(taskGroup(groups).children).toHaveLength(12);
  expect(new Set(taskGroup(groups).children.map(resourceLayerKey)).size).toBe(
    12,
  );
  for (const item of definitions) {
    expect(vector(groups, item.id).name).toBe(item.name);
    expect(vector(groups, item.id).sourceResource.name).toBe(item.name);
    expect(vector(groups, item.id).metadata.comparisonRoles).toBe(
      item.roles.join(","),
    );
  }
  const changes = collection(
    definitions
      .filter((item) => item.roles.includes("changes"))
      .flatMap((item) => item.data.features),
  );
  const sources = new Map(definitions.map((item) => [item.id, item.data]));
  for (const side of ["after", "before"] as const) {
    const shown = displayComparisonLayers(
      groups,
      workflowId,
      side,
      changes,
      sources,
    );
    expect(
      taskGroup(shown)
        .children.filter((layer) => layer.visible)
        .map((layer) => layer.sourceResource.id)
        .sort(),
    ).toEqual(
      definitions
        .filter(
          (item) => item.roles.includes(side) || item.roles.includes("changes"),
        )
        .map((item) => item.id)
        .sort(),
    );
    expect(vector(shown, 1102).visible).toBe(true);
    expect(taskGroup(shown).children).toHaveLength(12);
  }
});
