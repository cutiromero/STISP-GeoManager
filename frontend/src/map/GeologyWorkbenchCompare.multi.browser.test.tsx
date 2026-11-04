import { App } from "antd";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import mapboxgl from "mapbox-gl";
import { useRef, useState } from "react";
import { MemoryRouter, useSearchParams } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import type {
  GeoJsonFeatureCollection,
  ResourceProfileResponse,
} from "../api/generated/types.gen";
import type { LoadedLayerGroup, LoadedVectorLayer } from "../types";
import { resetProjectSession, setActiveProject } from "../projects/session";
import { createEmptyLayerGroup } from "../utils/layerFactory";
import { resourceLayerKey } from "../utils/uniqueLoadedLayers";
import {
  comparisonGroupId,
  displayComparisonLayers,
  upsertComparisonLayer,
} from "./comparisonLayerGroups";
import GeologyWorkbenchCompare from "./GeologyWorkbenchCompare";
import {
  beforeReviewMap,
  reviewQuery,
  reviewWorkflow,
} from "./geologyReview.testFixtures";
import platformStyles from "../styles.css?inline";
import reviewStyles from "./geology-review-workspace.css?inline";
import compareStyles from "./geology-workbench-compare.css?inline";
import tourStyles from "./multi-element-tour.css?inline";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../api/client", () => ({
  requestJson: request,
  requestForm: vi.fn(),
}));
type Feature = GeoJsonFeatureCollection["features"][number];
const collection = (features: Feature[]): GeoJsonFeatureCollection => ({
  type: "FeatureCollection",
  features,
});
const workflowId = "haide-workflow";
let observedGroups: LoadedLayerGroup[] = [];
const maps = new Set<mapboxgl.Map>();

function fixture() {
  const workflow = reviewWorkflow(true);
  workflow.id = workflowId;
  workflow.workflowType = "geology_multi_element_reasoning";
  const before = structuredClone(beforeReviewMap);
  before.features[0]!.properties = {
    feature_id: "unit-a",
    geo_sym: "Q",
    fill_color: "#edcf8a",
  };
  before.features[1]!.properties = {
    feature_id: "unit-b",
    geo_sym: "J2a",
    fill_color: "#37a7c4",
  };
  const after = structuredClone(before);
  after.features[0]!.properties.geo_sym = "T₃b";
  after.features[0]!.properties.fill_color = "#d6b3c6";
  const faults = collection([
    {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [98.402, 35.602],
          [98.428, 35.618],
        ],
      },
      properties: {
        feature_id: "fault-a",
        line_id: "fault-a",
        state: "keep",
        weight: 1,
      },
    },
  ]);
  const afterFaults = structuredClone(faults);
  afterFaults.features[0]!.properties = {
    feature_id: "fault-a",
    line_id: "fault-a",
    state: "exclude",
    weight: 0,
  };
  const minerals = collection([
    {
      ...before.features[0]!,
      properties: { feature_id: "mineral-a", state: "keep", weight: 0.8 },
    },
  ]);
  const afterMinerals = structuredClone(minerals);
  afterMinerals.features[0]!.properties = {
    feature_id: "mineral-a",
    state: "downweight",
    weight: 0.4,
  };
  const intersections = collection([
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [98.408, 35.609] },
      properties: { feature_id: "cross-a", inferred: false },
    },
  ]);
  const prospects = collection([
    {
      ...before.features[1]!,
      properties: { feature_id: "prospect-a", grade: "A", area_km2: 0.6 },
    },
  ]);
  const afterProspects = structuredClone(prospects);
  afterProspects.features[0]!.properties.grade = "B";
  const changes = [
    {
      id: "change-code",
      element: "lithology" as const,
      featureId: "unit-a",
      ruleId: "L-03",
      action: "set_code",
      title: "名称与地质代号不一致",
      geometry: before.features[0]!.geometry,
      weight: 1,
    },
    {
      id: "change-fault",
      element: "structure" as const,
      featureId: "fault-a",
      ruleId: "S-01",
      action: "exclude",
      title: "构造在覆盖层内缺少支持",
      geometry: faults.features[0]!.geometry,
      weight: 0,
    },
    {
      id: "change-mineral",
      element: "alteration" as const,
      featureId: "mineral-a",
      ruleId: "A-01",
      action: "downweight",
      title: "矿物信号受到岩石背景影响",
      geometry: minerals.features[0]!.geometry,
      weight: 0.4,
    },
  ];
  const suggestions = changes.map((item) => ({
    ...workflow.modificationReview!.suggestions[0]!,
    ...item,
    kind: "multi_element" as const,
    preview: item.geometry,
    ruleRefs: [
      {
        id: item.ruleId,
        version: "1.0.1",
        title: `${item.title}对照规则`,
        knowledgeId: 70,
        revision: 3,
        source: "海德乌拉案例整理知识",
      },
    ],
  }));
  workflow.modificationReview = {
    proposalHash: "actual-haide",
    approvedSuggestionIds: suggestions.map((item) => item.id),
    suggestions,
  };
  workflow.plan.inputs = { lithology: 101, faults: 102 };
  workflow.plan.algorithms = {
    "actual-edit": { name: "多要素获批修改", manifest: { version: "1.0.1" } },
  };
  const edits = changes.map((item) => ({
    feature_id: item.featureId,
    rule_id: item.ruleId,
    issue_id: item.id,
    action: item.action,
    target_code: item.action === "set_code" ? "T₃b" : "",
    weight: item.weight,
  }));
  workflow.plan.stages = [
    { name: "check", outputs: [{ key: "alterations", resourceId: 600 }] },
    {
      name: "apply",
      status: "completed",
      identifier: "actual-edit",
      taskId: "haide-actual-task",
      approvedEdits: edits,
      results: [
        {
          key: "changes",
          taskId: "haide-actual-task",
          outputId: 286,
          checksum: "a".repeat(64),
          scope: "all",
          rowCount: edits.length,
          rows: edits.map((item) => ({
            ...item,
            actual_changed: "True",
            old_code: "Q",
            new_code: item.target_code,
            involved_area_m2: 600000,
            geometry_change_area_m2: 0,
            class_change_area_m2: 0,
          })),
        },
      ],
    },
  ];
  workflow.plan.multiElementMap = {
    before: { lithology: 101, faults: 102 },
    after: { lithology: 201, faults: 202 },
    beforeAlterations: 600,
    alterations: 601,
    beforeIntersections: 401,
    intersections: 402,
    beforeProspects: 501,
    afterProspects: 502,
    changes: [301, 302, 303],
  };
  const datasets = new Map<number, GeoJsonFeatureCollection>([
    [101, before],
    [201, after],
    [102, faults],
    [202, afterFaults],
    [600, minerals],
    [601, afterMinerals],
    [401, intersections],
    [402, structuredClone(intersections)],
    [501, prospects],
    [502, afterProspects],
  ]);
  changes.forEach((item, index) =>
    datasets.set(
      301 + index,
      collection([
        {
          type: "Feature",
          geometry: item.geometry,
          properties: {
            issue_id: item.id,
            feature_id: item.featureId,
            rule_id: item.ruleId,
            suggested_action: item.action,
            element: item.element,
          },
        },
      ]),
    ),
  );
  const names = new Map<number, string>([
    [101, "海德原始岩性识别"],
    [201, "海德修正岩性代号"],
    [102, "海德原始构造线"],
    [202, "海德构造处置结果"],
    [600, "海德原始矿物状态"],
    [601, "海德矿物降权结果"],
    [401, "海德原始交汇点"],
    [402, "海德复算交汇点"],
    [501, "海德原始调查建议"],
    [502, "海德更新调查建议"],
    [301, "海德代号实际修改"],
    [302, "海德构造实际修改"],
    [303, "海德矿物实际修改"],
  ]);
  return { workflow, datasets, names };
}
let current: ReturnType<typeof fixture>;
function profile(id: number): ResourceProfileResponse {
  const data = current.datasets.get(id)!;
  return {
    resource: {
      ...createEmptyLayerGroup("测试").sourceResource,
      id,
      name: current.names.get(id)!,
      isQueryable: true,
    },
    fields: [],
    featureCount: data.features.length,
    geometryType: data.features[0]!.geometry.type,
    bounds: [98.4, 35.6, 98.45, 35.62],
  };
}

function Harness() {
  const [params, setParams] = useSearchParams();
  const [groups, setGroups] = useState<LoadedLayerGroup[]>([]);
  const sourceData = useRef(new Map<number, GeoJsonFeatureCollection>());
  const changeParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null) next.delete(key);
    else next.set(key, value);
    setParams(next);
  };
  return (
    <div className="workspace">
      <style>
        {platformStyles + reviewStyles + compareStyles + tourStyles}
      </style>
      <div
        className="workspace-body workspace-body-spatial-collapsed"
        style={{ width: "100%", height: 760 }}
      >
        <aside
          className="floating-panel floating-panel-left mobile-map-panel-hidden"
          aria-label="实际任务图层栏"
        >
          {groups.map((group) => (
            <section key={group.id} aria-label={group.name}>
              <strong>
                {group.name}：{group.children.length}个图层
              </strong>
              {group.children.map((layer) => (
                <div key={layer.id}>
                  {layer.name} / {String(layer.metadata.对比角色)}
                </div>
              ))}
            </section>
          ))}
        </aside>
        <main className="map-stage">
          <GeologyWorkbenchCompare
            workflowId={workflowId}
            projectId="3"
            projectTagId="3"
            suggestionId={params.get("suggestion")}
            accessToken=""
            canLoad
            comparisonVisible={params.get("mapMode") !== "single"}
            registerLayer={async (resource, result, placement) => {
              if (!placement) throw new Error("完整工作台入口缺少任务角色");
              sourceData.current.set(resource.resource.id, result.geojson);
              setGroups((previous) => {
                const next = upsertComparisonLayer(
                  previous,
                  resource,
                  result,
                  placement,
                );
                observedGroups = next;
                return next;
              });
            }}
            onLayerDisplay={(side, changes) =>
              setGroups((previous) => {
                const next = displayComparisonLayers(
                  previous,
                  workflowId,
                  side,
                  changes,
                  sourceData.current,
                );
                observedGroups = next;
                return next;
              })
            }
            onVisibilityChange={(visible) =>
              changeParam("mapMode", visible ? null : "single")
            }
            onSuggestionChange={(id) => changeParam("suggestion", id)}
          />
        </main>
        <output
          aria-label="工作台URL"
          style={{
            position: "absolute",
            width: 1,
            height: 1,
            overflow: "hidden",
          }}
        >
          {params.toString()}
        </output>
      </div>
    </div>
  );
}
function show(initial = `/map?geologyCompare=${workflowId}&projectTagId=3`) {
  return render(
    <App>
      <MemoryRouter initialEntries={[initial]}>
        <Harness />
      </MemoryRouter>
    </App>,
  );
}
function layers() {
  return observedGroups.find(
    (group) => group.id === comparisonGroupId(workflowId),
  )!.children;
}
function vector(id: number) {
  return layers().find(
    (layer) => layer.sourceResource.id === id,
  ) as LoadedVectorLayer;
}
function visibleChanges() {
  return layers()
    .filter(
      (layer) =>
        String(layer.metadata.comparisonRoles).includes("changes") &&
        layer.layerType === "vector",
    )
    .flatMap((layer) =>
      layer.layerType === "vector" ? layer.geojson.features : [],
    );
}
function liveMaps() {
  return [...maps].filter((map) => map.getCanvas()?.isConnected);
}
async function mapsReady() {
  const before = await screen.findByLabelText("待检查地质图地图");
  const after = await screen.findByLabelText("修正后地质图地图");
  await waitFor(
    () => {
      expect(before).toHaveAttribute("aria-busy", "false");
      expect(after).toHaveAttribute("aria-busy", "false");
      expect(liveMaps()).toHaveLength(2);
    },
    { timeout: 20000 },
  );
}
async function changesReady(position = 1) {
  await screen.findByText(`第 ${position} 处，共 3 处`);
  await waitFor(() => expect(layers()).toHaveLength(13));
}
function choose(control: string, label: string) {
  fireEvent.click(
    within(screen.getByLabelText(control)).getByText(label, {
      selector: ".ant-segmented-item-label",
    }),
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(mapboxgl.Map.prototype, "_authenticate").mockImplementation(
    () => {},
  );
  const original = mapboxgl.Map.prototype.addSource;
  vi.spyOn(mapboxgl.Map.prototype, "addSource").mockImplementation(function (
    this: mapboxgl.Map,
    ...args: Parameters<mapboxgl.Map["addSource"]>
  ) {
    maps.add(this);
    return original.apply(this, args);
  });
  maps.clear();
  observedGroups = [];
  current = fixture();
  request.mockReset();
  resetProjectSession();
  setActiveProject("3");
  request.mockImplementation(async (url: string) => {
    if (url.includes("/workflows/")) return structuredClone(current.workflow);
    const id = Number(url.match(/resources\/(\d+)\//)?.[1]);
    if (!current.datasets.has(id)) throw new Error(`未知资源: ${url}`);
    if (url.endsWith("/profile/")) return profile(id);
    return {
      ...reviewQuery(id, current.datasets.get(id)!),
      resourceName: current.names.get(id)!,
    };
  });
});

it("registers every real resource in one deduplicated task group and renders polygon, line and point overlays in both WebGL maps", async () => {
  show();
  await changesReady();
  await mapsReady();
  expect(observedGroups).toHaveLength(1);
  expect(layers()).toHaveLength(13);
  expect(new Set(layers().map(resourceLayerKey)).size).toBe(13);
  const panel = screen.getByLabelText("实际任务图层栏");
  for (const [id, name] of current.names) {
    expect(panel).toHaveTextContent(name);
    expect(vector(id).sourceResource.name).toBe(name);
    expect(
      request.mock.calls.filter(([url]) =>
        String(url).includes(`/${id}/query/`),
      ),
    ).toHaveLength(1);
  }
  expect(vector(401).metadata.comparisonRoles).toBe("before");
  expect(vector(402).metadata.comparisonRoles).toBe("after");
  expect(vector(600).metadata.comparisonRoles).toBe("before");
  expect(vector(601).metadata.comparisonRoles).toBe("after");
  expect(vector(101).visible).toBe(false);
  expect(vector(201).visible).toBe(true);
  expect(current.datasets.get(101)!.features[0]!.geometry).toEqual(
    current.datasets.get(201)!.features[0]!.geometry,
  );
  expect(visibleChanges()).toHaveLength(0);
  fireEvent.click(screen.getByLabelText("修正记录 / 实际修改范围"));
  await waitFor(() => expect(visibleChanges()).toHaveLength(1));
  await mapsReady();
  expect(visibleChanges()[0]!.properties.issue_id).toBe("change-code");
  expect(screen.getByLabelText("当前修改故事")).toHaveTextContent(
    "地质代号由 Q 更新为 T₃b",
  );
  for (const map of liveMaps()) {
    expect(map.getCanvas().getContext("webgl2")).toBeTruthy();
    expect(map.getLayer("units")?.type).toBe("fill");
    expect(map.getLayer("review-faults-line")?.type).toBe("line");
    expect(map.getLayer("review-intersections-point")?.type).toBe("circle");
    await waitFor(() => {
      expect(
        map.queryRenderedFeatures({ layers: ["units"] }).length,
      ).toBeGreaterThan(0);
      expect(
        map.queryRenderedFeatures({ layers: ["review-intersections-point"] })
          .length,
      ).toBeGreaterThan(0);
      expect(
        map.queryRenderedFeatures({
          layers: ["review-faults-line", "review-faults-excluded"],
        }).length,
      ).toBeGreaterThan(0);
    });
  }
  await page.screenshot({
    path: "../../test-results/geology-workbench-multi-desktop.png",
    animations: "disabled",
  });
});

it("navigates actual attribute and weight changes and changes normal-map controls without rereading", async () => {
  show();
  await changesReady();
  await mapsReady();
  const reads = request.mock.calls.length;
  fireEvent.click(screen.getByRole("button", { name: /下一处/ }));
  await screen.findByRole("heading", { name: "构造处置" });
  expect(visibleChanges()).toHaveLength(0);
  fireEvent.click(screen.getByLabelText("修正记录 / 实际修改范围"));
  await waitFor(() =>
    expect(visibleChanges()[0]!.properties.issue_id).toBe("change-fault"),
  );
  fireEvent.click(screen.getByRole("button", { name: /下一处/ }));
  await screen.findByRole("heading", { name: "矿物证据降权" });
  expect(screen.getByLabelText("当前修改故事")).toHaveTextContent(
    "证据权重 0.8 → 0.4",
  );
  expect(screen.getByLabelText("工作台URL")).toHaveTextContent(
    "suggestion=change-mineral",
  );
  await waitFor(() =>
    expect(visibleChanges()[0]!.properties.issue_id).toBe("change-mineral"),
  );
  expect(current.datasets.get(600)!.features[0]!.geometry).toEqual(
    current.datasets.get(601)!.features[0]!.geometry,
  );
  choose("地图显示方式", "单图");
  expect(screen.queryByLabelText("待检查地质图地图")).not.toBeInTheDocument();
  choose("修改显示范围", "全部修改");
  await waitFor(() => expect(visibleChanges()).toHaveLength(3));
  choose("单图成果版本", "改前");
  await waitFor(() => expect(vector(101).visible).toBe(true));
  expect(vector(201).visible).toBe(false);
  choose("单图成果版本", "改后");
  await waitFor(() => expect(vector(201).visible).toBe(true));
  expect(vector(101).visible).toBe(false);
  choose("修改显示范围", "当前修改");
  await waitFor(() => expect(visibleChanges()).toHaveLength(1));
  choose("地图显示方式", "前后对比");
  await mapsReady();
  fireEvent.click(screen.getByRole("button", { name: /上一处/ }));
  await screen.findByRole("heading", { name: "构造处置" });
  expect(request).toHaveBeenCalledTimes(reads);
  expect(layers()).toHaveLength(13);
});

it("restores URL side, scope and selected change, then refreshes without duplicating resource layers", async () => {
  show(
    `/map?geologyCompare=${workflowId}&projectTagId=3&mapMode=single&compareSide=before&compareScope=all&suggestion=change-mineral`,
  );
  await screen.findByRole("heading", { name: "矿物证据降权" });
  await changesReady(3);
  expect(visibleChanges()).toHaveLength(0);
  fireEvent.click(screen.getByLabelText("修正记录 / 实际修改范围"));
  await waitFor(() => expect(visibleChanges()).toHaveLength(3));
  expect(screen.getByText("第 3 处，共 3 处")).toBeVisible();
  expect(vector(101).visible).toBe(true);
  expect(vector(201).visible).toBe(false);
  expect(screen.queryByLabelText("待检查地质图地图")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /刷新成果/ }));
  await waitFor(() =>
    expect(
      request.mock.calls.filter(([url]) => String(url).includes("/workflows/")),
    ).toHaveLength(2),
  );
  await screen.findByRole("heading", { name: "矿物证据降权" });
  expect(observedGroups).toHaveLength(1);
  expect(layers()).toHaveLength(13);
  expect(new Set(layers().map(resourceLayerKey)).size).toBe(13);
  expect(screen.getByRole("link", { name: "独立对比页" })).toHaveAttribute(
    "href",
    `/map?geologyReview=${workflowId}&projectTagId=3&suggestion=change-mineral`,
  );
});

it("keeps the full comparison, navigation and real WebGL canvases within 390 pixels", async () => {
  await page.viewport(390, 844);
  try {
    show(
      `/map?geologyCompare=${workflowId}&projectTagId=3&suggestion=change-mineral`,
    );
    await changesReady(3);
    await mapsReady();
    const comparison = screen
      .getByLabelText("地理工作台地质成果对比")
      .getBoundingClientRect();
    expect(comparison.left).toBeGreaterThanOrEqual(0);
    expect(comparison.right).toBeLessThanOrEqual(390);
    for (const map of liveMaps()) {
      const bounds = map.getCanvas().getBoundingClientRect();
      expect(bounds.width).toBeGreaterThan(100);
      expect(bounds.height).toBeGreaterThan(80);
      expect(bounds.right).toBeLessThanOrEqual(390);
    }
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390);
    expect(screen.getByText("第 3 处，共 3 处")).toBeVisible();
    expect(screen.getByRole("heading", { name: "矿物证据降权" })).toBeVisible();
    expect(visibleChanges()).toHaveLength(0);
    const navigation = screen
      .getByRole("navigation", { name: "切换修改位置" })
      .getBoundingClientRect();
    expect(navigation.top).toBeGreaterThanOrEqual(0);
    expect(navigation.bottom).toBeLessThanOrEqual(844);
    expect(navigation.left).toBeGreaterThanOrEqual(0);
    expect(navigation.right).toBeLessThanOrEqual(390);
    await page.screenshot({
      path: "../../test-results/geology-workbench-multi-390.png",
      animations: "disabled",
    });
  } finally {
    await page.viewport(1600, 900);
  }
});
