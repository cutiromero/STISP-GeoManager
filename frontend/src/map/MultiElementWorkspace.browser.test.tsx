import { App } from "antd";
import { StrictMode } from "react";
import mapboxgl from "mapbox-gl";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import {
  beforeReviewMap,
  reviewQuery,
  reviewWorkflow,
} from "./geologyReview.testFixtures";
import type { GeoJsonFeatureCollection } from "../api/generated/types.gen";
import MultiElementWorkspace from "./MultiElementWorkspace";
import workspaceStyles from "./geology-review-workspace.css?inline";
import tourStyles from "./multi-element-tour.css?inline";
const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ bootstrap: { map: { mapboxAccessToken: "" } } }),
}));
vi.mock("../api/client", async (original) => ({
  ...(await original<typeof import("../api/client")>()),
  requestJson: request,
}));
const lines: GeoJsonFeatureCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      id: "line-1",
      geometry: {
        type: "LineString",
        coordinates: [
          [98.405, 35.603],
          [98.445, 35.617],
        ],
      },
      properties: {
        line_id: "line-1",
        rule_id: "S-02",
        reason: "沿界比例较高，建议核对影像",
        status: "review",
      },
    },
  ],
};
const points: GeoJsonFeatureCollection = {
  type: "FeatureCollection",
  features: [false, true].map((inferred, index) => ({
    type: "Feature",
    id: inferred ? "inferred" : "geometric",
    geometry: { type: "Point", coordinates: [98.42 + index * 0.01, 35.61] },
    properties: {
      inferred,
      gap_m: inferred ? 180 : 0,
      type: "主干×次级",
      rule_id: "S-05",
    },
  })),
};
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(mapboxgl.Map.prototype, "_authenticate").mockImplementation(
    () => {},
  );
  request.mockReset();
});

it("真实WebGL双图支持线点面，沿用岩性配色和Unicode代号，推测交汇用空心点", async () => {
  const workflow = reviewWorkflow();
  workflow.workflowType = "geology_multi_element_reasoning";
  workflow.plan.inputs = { lithology: 101, faults: 102 };
  workflow.plan.stages = [
    { name: "check", outputs: [{ key: "alterations", resourceId: 600 }] },
  ];
  workflow.plan.multiElementMap = {
    before: { lithology: 101, faults: 102 },
    after: { lithology: 201, faults: 202 },
    checks: [301],
    changes: [],
    intersections: 401,
    beforeProspects: 501,
    afterProspects: 502,
    alterations: 601,
  };
  const base = structuredClone(beforeReviewMap);
  base.features[0]!.properties.fill_color = "#4abb83";
  base.features[0]!.properties.geo_sym = "T₃b²";
  const zones = structuredClone(base);
  zones.features[0]!.properties = {
    zone_id: "A01",
    grade: "A",
    explanation: "本次算法确认构造、矿物组合与有利岩性条件同时满足",
    evidence_json: "构造条件：满足；蚀变类型：绿泥石、水云母",
  };
  request.mockImplementation(async (url: string) => {
    const id = Number(url.match(/resources\/(\d+)\/query/)?.[1]);
    if ([600, 601].includes(id)) {
      const minerals = structuredClone(base);
      minerals.features[0]!.properties.state =
        id === 600 ? "keep" : "downweight";
      return reviewQuery(id, minerals);
    }
    return reviewQuery(
      id,
      [102, 202, 301].includes(id)
        ? lines
        : id === 401
          ? points
          : [501, 502].includes(id)
            ? zones
            : base,
    );
  });
  const sources = vi.spyOn(mapboxgl.Map.prototype, "addSource");
  const layers = vi.spyOn(mapboxgl.Map.prototype, "addLayer");
  const fitBounds = vi.spyOn(mapboxgl.Map.prototype, "fitBounds");
  render(
    <StrictMode>
      <App>
        <MemoryRouter>
          <style>{workspaceStyles}</style>
          <MultiElementWorkspace
            workflow={workflow}
            suggestionId={null}
            onReload={() => {}}
          />
        </MemoryRouter>
      </App>
    </StrictMode>,
  );
  await waitFor(
    () =>
      expect(screen.getByLabelText("待检查地质图地图")).toHaveAttribute(
        "aria-busy",
        "false",
      ),
    { timeout: 20000 },
  );
  expect(
    screen.queryByText("地图渲染失败，请刷新或核对图件后重试。"),
  ).not.toBeInTheDocument();
  expect(screen.getByText("八宝山组 / T₃b²")).not.toBeVisible();
  fireEvent.click(screen.getByText("查看岩性配色"));
  expect(screen.getByText("八宝山组 / T₃b²")).toBeVisible();
  expect(
    fitBounds.mock.calls.some(
      ([, options]) =>
        options?.padding === 50 && options?.maxZoom === undefined,
    ),
  ).toBe(true);
  expect(screen.getByText("● 几何交汇 / ○ 推测交汇")).toBeVisible();
  expect(sources.mock.calls.some(([id]) => id === "review-faults")).toBe(true);
  expect(sources.mock.calls.some(([id]) => id === "review-intersections")).toBe(
    true,
  );
  const pointLayer = layers.mock.calls
    .map(([layer]) => layer)
    .find((layer) => layer.id === "review-intersections-point");
  expect(JSON.stringify(pointLayer)).toContain("inferred");
  expect(JSON.stringify(pointLayer)).toContain("#ffffff");
  expect(
    request.mock.calls.some(([url]) => String(url).includes("/301/query/")),
  ).toBe(false);
  fireEvent.click(screen.getByLabelText("待核查项"));
  await waitFor(() =>
    expect(
      request.mock.calls.some(([url]) => String(url).includes("/301/query/")),
    ).toBe(true),
  );
  fireEvent.click(screen.getByText("定位检查记录 / 1 条规则命中"));
  fireEvent.click(await screen.findByText("S-02 / 实际疑点"));
  expect(screen.getByText("沿界比例较高，建议核对影像")).toBeVisible();
  fireEvent.click(screen.getByLabelText("矿物与处理状态"));
  await waitFor(() => {
    const mineralSources = sources.mock.calls
      .filter(([id]) => id === "review-alterations")
      .map(([, source]) => JSON.stringify((source as { data: unknown }).data));
    expect(
      mineralSources.some((value) => value.includes('"state":"keep"')),
    ).toBe(true);
    expect(
      mineralSources.some((value) => value.includes('"state":"downweight"')),
    ).toBe(true);
  });
  await page.screenshot({
    path: "../../test-results/multi-element-map-line-point-polygon.png",
    animations: "disabled",
  });
});

it("keeps the base maps usable when an optional dense layer fails and retries on selection", async () => {
  const workflow = reviewWorkflow();
  workflow.workflowType = "geology_multi_element_reasoning";
  workflow.plan.inputs = { lithology: 101, faults: 102 };
  workflow.plan.multiElementMap = {
    before: { lithology: 101, faults: 102 },
    checks: [301],
    alterations: 401,
  };
  let failChecks = true;
  request.mockImplementation(async (url: string) => {
    const id = Number(url.match(/resources\/(\d+)\/query/)?.[1]);
    if (id === 301 && failChecks) throw new Error("当前图层查询暂时失败");
    return reviewQuery(id, id === 102 || id === 301 ? lines : beforeReviewMap);
  });
  render(
    <App>
      <MemoryRouter>
        <MultiElementWorkspace
          workflow={workflow}
          suggestionId={null}
          onReload={() => {}}
        />
      </MemoryRouter>
    </App>,
  );
  await waitFor(() =>
    expect(screen.getByLabelText("待检查地质图地图")).toHaveAttribute(
      "aria-busy",
      "false",
    ),
  );
  expect(
    request.mock.calls.some(([url]) =>
      /\/(301|401)\/query\//.test(String(url)),
    ),
  ).toBe(false);
  fireEvent.click(screen.getByLabelText("待核查项"));
  expect(await screen.findByText("待核查项未能加载")).toBeVisible();
  expect(screen.getByLabelText("待检查地质图地图")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  failChecks = false;
  fireEvent.click(screen.getByLabelText("待核查项"));
  fireEvent.click(screen.getByLabelText("待核查项"));
  await waitFor(() =>
    expect(screen.queryByText("待核查项未能加载")).toBeNull(),
  );
  expect(
    request.mock.calls.filter(([url]) => String(url).includes("/301/query/")),
  ).toHaveLength(2);
});

it("用真实获批变化逐处讲解，并以实际几何和面积展示调查建议变化", async () => {
  await page.viewport(1280, 800);
  const workflow = reviewWorkflow(true);
  workflow.workflowType = "geology_multi_element_reasoning";
  workflow.plan.inputs = { lithology: 101, faults: 102 };
  workflow.plan.algorithms = {
    "actual-edit": { name: "多要素获批修改", manifest: { version: "1.0.1" } },
  };
  const before = structuredClone(beforeReviewMap);
  before.features[0]!.properties.geo_sym = "Q";
  const after = structuredClone(before);
  after.features[0]!.properties.geo_sym = "T₃b";
  const minerals = structuredClone(before);
  minerals.features[0]!.properties = {
    feature_id: "mineral-1",
    weight: 0.8,
    state: "keep",
  };
  const afterMinerals = structuredClone(minerals);
  afterMinerals.features[0]!.properties = {
    feature_id: "mineral-1",
    weight: 0.4,
    state: "downweight",
  };
  const faults = structuredClone(lines);
  faults.features[0]!.properties = {
    line_id: "line-1",
    weight: 1,
    state: "keep",
  };
  const afterFaults = structuredClone(faults);
  afterFaults.features[0]!.properties = {
    line_id: "line-1",
    weight: 0,
    state: "exclude",
  };
  const suggestions = [
    {
      element: "lithology" as const,
      featureId: "unit-a",
      action: "set_code",
      title: "名称与地质代号不一致",
      ruleId: "L-03",
      geometry: before.features[0]!.geometry,
    },
    {
      element: "structure" as const,
      featureId: "line-1",
      action: "exclude",
      title: "构造在覆盖层内缺少支持",
      ruleId: "S-01",
      geometry: faults.features[0]!.geometry,
    },
    {
      element: "alteration" as const,
      featureId: "mineral-1",
      action: "downweight",
      title: "矿物信号可能受到岩石背景影响",
      ruleId: "A-01",
      geometry: minerals.features[0]!.geometry,
    },
  ].map((item, index) => ({
    ...workflow.modificationReview!.suggestions[0]!,
    ...item,
    kind: "multi_element" as const,
    id: `change-${index}`,
    preview: item.geometry,
    ruleRefs: [
      {
        id: item.ruleId,
        version: "1.0.1",
        title: `${item.title}对照规则`,
        knowledgeId: 70 + index,
        revision: 3,
        source: "实际引用的项目整理知识，案例条目",
      },
    ],
  }));
  workflow.modificationReview = {
    proposalHash: "actual",
    approvedSuggestionIds: suggestions.map((item) => item.id),
    suggestions,
  };
  workflow.plan.stages = [
    { name: "check", outputs: [{ key: "alterations", resourceId: 600 }] },
    {
      name: "apply",
      status: "completed",
      identifier: "actual-edit",
      taskId: "actual-task",
      approvedEdits: suggestions.map((item) => ({
        feature_id: item.featureId,
        rule_id: item.ruleId,
        action: item.action,
        target_code: item.action === "set_code" ? "T₃b" : "",
        weight: item.action === "downweight" ? 0.4 : 1,
      })),
      results: [
        {
          key: "changes",
          taskId: "actual-task",
          outputId: 286,
          checksum: "a".repeat(64),
          scope: "all",
          rowCount: suggestions.length,
          rows: suggestions.map((item) => ({
            feature_id: item.featureId,
            rule_id: item.ruleId,
            action: item.action,
            target_code: item.action === "set_code" ? "T₃b" : "",
            weight: item.action === "downweight" ? "0.4" : "1.0",
            actual_changed: "True",
            old_code: "Q",
            new_code: "T₃b",
          })),
        },
      ],
    },
  ];
  workflow.plan.multiElementMap = {
    before: { lithology: 101, faults: 102 },
    after: { lithology: 201, faults: 202 },
    changes: [301],
    beforeProspects: 501,
    afterProspects: 502,
    alterations: 601,
  };
  const changes: GeoJsonFeatureCollection = {
    type: "FeatureCollection",
    features: suggestions.map((item) => ({
      type: "Feature",
      geometry: item.preview,
      properties: {
        feature_id: item.featureId,
        element: item.element,
        rule_id: item.ruleId,
        suggested_action: item.action,
      },
    })),
  };
  const zones = structuredClone(before);
  zones.features.forEach((item, index) => {
    item.properties = {
      grade: "B",
      zone_id: `B${index + 1}`,
      area_km2: index ? 0.65 : 3,
    };
  });
  const afterZones: GeoJsonFeatureCollection = {
    type: "FeatureCollection",
    features: [
      {
        ...zones.features[0]!,
        properties: { ...zones.features[0]!.properties, zone_id: "renumbered" },
      },
    ],
  };
  const collections: Record<number, GeoJsonFeatureCollection> = {
    101: before,
    102: faults,
    201: after,
    202: afterFaults,
    301: changes,
    501: zones,
    502: afterZones,
    600: minerals,
    601: afterMinerals,
  };
  request.mockImplementation(async (url: string) => {
    const id = Number(url.match(/resources\/(\d+)\/query/)?.[1]);
    return reviewQuery(
      id,
      collections[id] ?? { type: "FeatureCollection", features: [] },
    );
  });
  render(
    <App>
      <MemoryRouter>
        <style>
          {workspaceStyles}
          {tourStyles}
        </style>
        <MultiElementWorkspace
          workflow={workflow}
          suggestionId={null}
          onReload={() => {}}
        />
      </MemoryRouter>
    </App>,
  );
  expect(await screen.findByText("第1处，共3处")).toBeVisible();
  await waitFor(
    () =>
      expect(screen.getByLabelText("待检查地质图地图")).toHaveAttribute(
        "aria-busy",
        "false",
      ),
    { timeout: 20000 },
  );
  const labels = screen.getByLabelText("当前对象前后状态");
  const beforeCanvas = screen
    .getByLabelText("待检查地质图地图")
    .querySelector("canvas");
  const afterCanvas = screen
    .getByLabelText("修正后地质图地图")
    .querySelector("canvas");
  expect(beforeCanvas).not.toBeNull();
  expect(afterCanvas).not.toBeNull();
  expect(labels).toHaveTextContent("Q");
  expect(labels).toHaveTextContent("T₃b");
  expect(screen.getByText("发现了什么")).toBeVisible();
  expect(screen.getByText("哪条知识支持")).toBeVisible();
  expect(screen.getByText("算法实际做了什么")).toBeVisible();
  const narrative = screen
    .getByText("发现了什么")
    .closest(".multi-tour-explanation")!;
  expect(narrative.getBoundingClientRect().bottom).toBeLessThanOrEqual(800);
  fireEvent.click(screen.getByLabelText("下一处修改"));
  expect(screen.getByText("第2处，共3处")).toBeVisible();
  expect(screen.getByLabelText("当前对象前后状态")).toHaveTextContent(
    "本轮不参与分析",
  );
  fireEvent.click(screen.getByLabelText("下一处修改"));
  await waitFor(() =>
    expect(screen.getByLabelText("当前对象前后状态")).toHaveTextContent(
      "证据权重 0.8",
    ),
  );
  expect(screen.getByLabelText("当前对象前后状态")).toHaveTextContent(
    "证据权重 0.4",
  );
  expect(
    request.mock.calls.filter(([url]) => String(url).includes("/301/query/")),
  ).toHaveLength(1);
  expect(
    screen.getByLabelText("待检查地质图地图").querySelector("canvas"),
  ).toBe(beforeCanvas);
  expect(
    screen.getByLabelText("修正后地质图地图").querySelector("canvas"),
  ).toBe(afterCanvas);
  expect(document.querySelectorAll(".mapboxgl-canvas")).toHaveLength(2);
  expect(
    request.mock.calls.filter(([url]) => String(url).includes("/101/query/")),
  ).toHaveLength(1);
  expect(
    request.mock.calls.filter(([url]) => String(url).includes("/201/query/")),
  ).toHaveLength(1);
  expect(screen.getByText("面积减少0.65平方公里")).toBeVisible();
  fireEvent.click(screen.getByText("定位变化的核查区"));
  expect(screen.getByLabelText("调查建议前后对比")).toBeVisible();
  fireEvent.click(screen.getByText("查看全区"));
  expect(screen.getByText("对象与依据")).toBeVisible();
  fireEvent.click(screen.getByText("逐处看修改"));
  expect(screen.getByText("第3处，共3处")).toBeVisible();
  await page.screenshot({
    path: "../../test-results/multi-element-change-tour.png",
    animations: "disabled",
    fullPage: true,
  });
  await page.viewport(1600, 900);
});
