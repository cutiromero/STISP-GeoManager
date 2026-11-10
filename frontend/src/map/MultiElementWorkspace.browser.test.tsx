import { App } from "antd";
import { StrictMode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import {
  beforeReviewMap,
  reviewQuery,
  reviewWorkflow,
} from "./geologyReview.testFixtures";
import type {
  ComputeMapPreview,
  GeoJsonFeatureCollection,
} from "../api/generated/types.gen";
import MultiElementWorkspace from "./MultiElementWorkspace";
import { projectReviewPosition } from "./localReviewGeometry";
import { reviewBounds } from "./geologyReviewData";
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
  sessionStorage.removeItem("geology-story:review-workflow");
  vi.restoreAllMocks();
  request.mockReset();
  // Exercise the real API adapter while keeping component tests offline.
  vi.spyOn(window, "fetch").mockImplementation(async (input, init) => {
    const incoming =
      input instanceof Request ? input : new Request(input, init);
    const value = await request(
      new URL(incoming.url, window.location.href).pathname,
    );
    return new Response(JSON.stringify(value), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
});

function rasterWorkflow(mineral = "calcite") {
  const workflow = reviewWorkflow(true);
  workflow.workflowType = "geology_multi_element_reasoning";
  workflow.plan.inputs = { lithology: 101, faults: 102 };
  workflow.plan.algorithms = {
    "geology-multi-check": {
      manifest: { version: "1.1.1", outputs: [{ key: "calcite_before" }] },
    },
    "geology-multi-apply": {
      name: "获批操作执行",
      manifest: { version: "1.1.1", outputs: [{ key: "final_faults" }] },
    },
  };
  const suggestion = {
    ...workflow.modificationReview!.suggestions[0]!,
    id: "raster-change",
    kind: "multi_element" as const,
    element: "alteration" as const,
    featureId: `AG-${mineral}-carbonate`,
    ruleId: "A-01",
    action: "downweight",
    title: "碳酸盐岩背景矿物降权",
    observations: {
      mineral,
      raster_protocol: "alteration-pixels-v1",
      pixel_count: 100,
    },
  };
  workflow.modificationReview = {
    proposalHash: "raster-proposal",
    approvedSuggestionIds: [suggestion.id],
    suggestions: [suggestion],
  };
  workflow.plan.stages = [
    { name: "check", status: "completed", outputs: [], results: [] },
    {
      name: "apply",
      identifier: "geology-multi-apply",
      status: "completed",
      taskId: "raster-task",
      outputs: [],
      approvedEdits: [
        {
          feature_id: suggestion.featureId,
          rule_id: suggestion.ruleId,
          action: suggestion.action,
          weight: 0.4,
        },
      ],
      results: [
        {
          key: "changes",
          taskId: "raster-task",
          outputId: 903,
          checksum: "a".repeat(64),
          scope: "all",
          rowCount: 1,
          rows: [
            {
              feature_id: suggestion.featureId,
              rule_id: suggestion.ruleId,
              action: suggestion.action,
              weight: "0.4",
              actual_changed: "True",
            },
          ],
        },
      ],
    },
  ];
  workflow.plan.multiElementMap = {
    before: { lithology: 101, faults: 102 },
    after: { lithology: 201, faults: 202 },
    checks: [301],
    changes: [],
    alterationRasters: [
      {
        mineral,
        beforeOutputId: 900,
        afterOutputId: 901,
        changesOutputId: 902,
      },
    ],
  };
  workflow.plan.compareFeatures = {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: suggestion.preview,
        properties: {
          feature_id: suggestion.featureId,
          element: suggestion.element,
          rule_id: suggestion.ruleId,
          suggested_action: suggestion.action,
        },
      },
    ],
  };
  return workflow;
}

function rasterPreview(id: number): ComputeMapPreview {
  return {
    name: "方解石",
    kind: "raster",
    metadata: {},
    temporary: true,
    imageUrl: `data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a4m0AAAAASUVORK5CYII=#${id}`,
    imageCoordinates: [
      [98.4, 35.62],
      [98.45, 35.62],
      [98.45, 35.6],
      [98.4, 35.6],
    ],
  };
}

function mockRasterReads(failRaster = false) {
  request.mockImplementation(async (url: string) => {
    const outputId = Number(url.match(/outputs\/(\d+)\/map-preview\//)?.[1]);
    if (outputId) {
      if (failRaster) throw new Error("栅格预览读取失败");
      return rasterPreview(outputId);
    }
    if (url.includes("/api/compute/outputs/"))
      throw new Error("栅格任务不应读取旧蚀变矢量");
    const id = Number(url.match(/resources\/(\d+)\/query/)?.[1]);
    return reviewQuery(id, id === 102 || id === 202 ? lines : beforeReviewMap);
  });
}

it("按实际类别波段展示新增矿物，不限制为五类", async () => {
  const workflow = rasterWorkflow("class_pyrite");
  workflow.plan.inputs = { lithology: 101, faults: 102, alteration_stack: 103 };
  workflow.plan.multiElementMap!.alterationRasters = [
    {
      mineral: "class_pyrite",
      label: "黄铁矿化",
      band: 2,
      beforeOutputId: 900,
      afterOutputId: 901,
      changesOutputId: 902,
    },
  ];
  mockRasterReads();
  const fallback = request.getMockImplementation()!;
  request.mockImplementation(async (url: string) => {
    if (url.includes("map-preview")) {
      const output = Number(url.match(/outputs\/(\d+)/)?.[1]);
      return {
        ...rasterPreview(output),
        metadata: {
          colorTable: [{ value: 1, label: "黄铁矿化", color: "#f5a623ff" }],
        },
      };
    }
    return fallback(url);
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
    expect(
      screen
        .getByLabelText("修正后地质图地图")
        .querySelector('image[data-layer="alteration:class_pyrite"]'),
    ).toBeInTheDocument(),
  );
  const previews = request.mock.calls.filter(([url]) =>
    String(url).includes("map-preview"),
  );
  expect(previews.map(([url]) => url).sort()).toEqual(
    [900, 901, 902]
      .map((id) => `/api/compute/outputs/${id}/map-preview/?band=2`)
      .sort(),
  );
  expect(screen.getByText("黄铁矿化")).toBeVisible();
});

it("栅格矿物章节与保存位置直接显示实际PNG，不再读取旧蚀变矢量", async () => {
  const workflow = rasterWorkflow();
  mockRasterReads();
  const show = () =>
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
  const expectRasters = async () => {
    for (const [label, outputId] of [
      ["待检查地质图地图", 900],
      ["修正后地质图地图", 901],
    ] as const) {
      await waitFor(() =>
        expect(
          screen
            .getByLabelText(label)
            .querySelector('image[data-layer="alteration:calcite"]'),
        ).toHaveAttribute("href", rasterPreview(outputId).imageUrl),
      );
    }
    expect(screen.queryByText("矿物与处理状态未能加载")).toBeNull();
  };
  const view = show();
  expect(await screen.findByText("本页第1处，共1处")).toBeVisible();
  // The default tour can reach a mineral while the overview layer is unchecked.
  await expectRasters();
  fireEvent.click(screen.getByRole("button", { name: "查看矿物章节" }));
  await expectRasters();
  fireEvent.click(screen.getByRole("button", { name: "查看全区" }));
  fireEvent.click(screen.getByLabelText("修正记录"));
  fireEvent.click(screen.getByLabelText("待核查项"));
  await waitFor(() =>
    expect(
      screen
        .getByLabelText("修正后地质图地图")
        .querySelector('image[data-layer="alteration-changes:calcite"]'),
    ).toHaveAttribute("href", rasterPreview(902).imageUrl),
  );
  await waitFor(() =>
    expect(
      request.mock.calls.some(([url]) => String(url).includes("/301/query/")),
    ).toBe(true),
  );
  fireEvent.click(screen.getByRole("button", { name: "逐处看修改" }));
  await waitFor(() =>
    expect(sessionStorage.getItem("geology-story:review-workflow")).toContain(
      '"chapter":"alteration"',
    ),
  );
  view.unmount();
  show();
  expect(await screen.findByText("本页第1处，共1组")).toBeVisible();
  await expectRasters();
  expect(
    request.mock.calls.filter(([url]) =>
      /\/outputs\/\d+\/preview\//.test(String(url)),
    ),
  ).toHaveLength(0);
});

it("真实栅格预览失败时保留错误和基础双图，不回退旧矢量", async () => {
  mockRasterReads(true);
  render(
    <App>
      <MemoryRouter>
        <MultiElementWorkspace
          workflow={rasterWorkflow()}
          suggestionId={null}
          onReload={() => {}}
        />
      </MemoryRouter>
    </App>,
  );
  expect(await screen.findByText("蚀变栅格：栅格预览读取失败")).toBeVisible();
  fireEvent.click(await screen.findByRole("button", { name: "查看矿物章节" }));
  expect(screen.queryByText("矿物与处理状态未能加载")).toBeNull();
  await waitFor(() =>
    expect(screen.getByLabelText("待检查地质图地图")).toHaveAttribute(
      "aria-busy",
      "false",
    ),
  );
  expect(
    request.mock.calls.filter(([url]) =>
      /\/outputs\/\d+\/preview\//.test(String(url)),
    ),
  ).toHaveLength(0);
});

it("当前矿物分析缺少栅格引用时明确报错，不尝试蚀变矢量", async () => {
  const workflow = rasterWorkflow();
  delete workflow.plan.multiElementMap!.alterationRasters;
  mockRasterReads();
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
  expect(
    await screen.findByText("蚀变栅格：当前蚀变栅格协议缺少地图输出引用"),
  ).toBeVisible();
  expect(
    request.mock.calls.some(([url]) =>
      String(url).includes("/api/compute/outputs/"),
    ),
  ).toBe(false);
});

it.each(["lithology", "structure"])(
  "合法%s分段没有矿物成果时不误报栅格缺失",
  async (segment) => {
    const workflow = reviewWorkflow();
    workflow.workflowType = "geology_multi_element_reasoning";
    workflow.parameters = { segment };
    workflow.plan.inputs = { lithology: 101, faults: 102 };
    workflow.plan.algorithms = {
      "geology-multi-check": {
        manifest: { version: "1.1.1", outputs: [{ key: "calcite_before" }] },
      },
    };
    workflow.plan.stages = [
      { name: "check", status: "completed", results: [] },
    ];
    workflow.plan.multiElementMap = { before: { lithology: 101, faults: 102 } };
    mockRasterReads();
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
    fireEvent.click(
      await screen.findByRole("button", { name: "查看岩性章节" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "查看矿物章节" }));
    expect(screen.queryByText(/当前蚀变栅格协议缺少地图输出引用/)).toBeNull();
    expect(
      request.mock.calls.some(([url]) =>
        String(url).includes("/api/compute/outputs/"),
      ),
    ).toBe(false);
  },
);

it("非空栅格引用缺少当前故事矿物时仍明确报错", async () => {
  const workflow = rasterWorkflow();
  workflow.plan.multiElementMap!.alterationRasters![0]!.mineral = "chlorite";
  mockRasterReads();
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
  expect(
    await screen.findByText("蚀变栅格：当前蚀变栅格协议缺少地图输出引用"),
  ).toBeVisible();
});

it.each(["afterOutputId", "changesOutputId"] as const)(
  "已完成执行缺少%s时不使用改前图替代",
  async (key) => {
    const workflow = rasterWorkflow();
    delete workflow.plan.multiElementMap!.alterationRasters![0]![key];
    mockRasterReads();
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
    expect(
      await screen.findByText(
        "蚀变栅格：当前蚀变栅格协议缺少完整的前后地图输出引用",
      ),
    ).toBeVisible();
    const map = await screen.findByLabelText("修正后地质图地图");
    expect(
      map.querySelector('image[data-layer="alteration:calcite"]'),
    ).toBeNull();
    expect(
      request.mock.calls.some(([url]) =>
        String(url).includes("/api/compute/outputs/"),
      ),
    ).toBe(false);
  },
);

it.each(["hidden", "running"])("矿物%s时不提前报栅格引用缺失", async (mode) => {
  const workflow = rasterWorkflow();
  delete workflow.plan.multiElementMap!.alterationRasters;
  if (mode === "running") workflow.plan.stages![0]!.status = "running";
  else
    sessionStorage.setItem(
      "geology-story:review-workflow",
      JSON.stringify({ chapter: "all", viewMode: "overview", visible: [] }),
    );
  mockRasterReads();
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
  await screen.findByRole("button", { name: "查看矿物章节" });
  expect(screen.queryByText(/当前蚀变栅格协议缺少地图输出引用/)).toBeNull();
  if (mode === "hidden") {
    fireEvent.click(screen.getByRole("button", { name: "查看矿物章节" }));
    expect(
      await screen.findByText("蚀变栅格：当前蚀变栅格协议缺少地图输出引用"),
    ).toBeVisible();
  }
});

it("页签使用全局计数并按要素分页，成果更新可一键刷新", async () => {
  const workflow = reviewWorkflow();
  workflow.workflowType = "geology_multi_element_reasoning";
  workflow.plan.inputs = { lithology: 101, faults: 102 };
  workflow.plan.pagination = {
    part: "changes",
    total: 5572,
    offset: 0,
    limit: 25,
    groups: [],
    counts: { all: 5572, lithology: 76, structure: 38, alteration: 5458 },
    revision: "frozen",
  };
  request.mockImplementation(async (url: string) =>
    reviewQuery(
      Number(url.match(/resources\/(\d+)\/query/)?.[1]),
      beforeReviewMap,
    ),
  );
  const onPage = vi.fn().mockResolvedValue(undefined);
  const onReload = vi.fn();
  render(
    <App>
      <MemoryRouter>
        <MultiElementWorkspace
          workflow={workflow}
          suggestionId={null}
          onPage={onPage}
          onReload={onReload}
        />
      </MemoryRouter>
    </App>,
  );
  expect(
    await screen.findByRole("button", { name: "查看构造章节" }),
  ).toHaveTextContent("38");
  expect(
    screen.getByRole("button", { name: "查看矿物章节" }),
  ).toHaveTextContent("5458");
  fireEvent.click(screen.getByRole("button", { name: "查看构造章节" }));
  await waitFor(() => expect(onPage).toHaveBeenCalledWith(0, "structure"));
  onPage.mockRejectedValueOnce(new Error("成果已更新，请刷新后继续浏览"));
  fireEvent.click(screen.getByRole("button", { name: "查看矿物章节" }));
  await waitFor(() => expect(onPage).toHaveBeenCalledWith(0, "alteration"));
  fireEvent.click(
    await screen.findByRole("button", { name: "刷新并保留当前位置" }),
  );
  expect(onReload).toHaveBeenCalledOnce();
});

it("讲解页双图同类采用成果原色并支持线点面、Unicode代号与空心交汇点", async () => {
  const worker = vi.spyOn(window, "Worker");
  const started = performance.now();
  const workflow = reviewWorkflow();
  workflow.workflowType = "geology_multi_element_reasoning";
  workflow.plan.inputs = { lithology: 101, faults: 102 };
  workflow.plan.stages = [{ name: "check", status: "completed", outputs: [] }];
  workflow.plan.multiElementMap = {
    before: { lithology: 101, faults: 102 },
    after: { lithology: 201, faults: 202 },
    checks: [301],
    changes: [],
    intersections: 401,
    beforeProspects: 501,
    afterProspects: 502,
    alterationRasters: [
      {
        mineral: "calcite",
        beforeOutputId: 900,
        afterOutputId: 901,
        changesOutputId: 902,
      },
    ],
  };
  const base = structuredClone(beforeReviewMap);
  base.features[0]!.properties.fill_color = "#4abb83";
  base.features[0]!.properties.geo_sym = "T₃b²";
  const styledAfter = structuredClone(base);
  styledAfter.features[0]!.properties.fill_color = "#ffdfa4";
  const zones = structuredClone(base);
  zones.features[0]!.properties = {
    zone_id: "A01",
    grade: "A",
    explanation: "本次算法确认构造、矿物组合与有利岩性条件同时满足",
    evidence_json: "构造条件：满足；蚀变类型：绿泥石、水云母",
  };
  request.mockImplementation(async (url: string) => {
    const outputId = Number(url.match(/outputs\/(\d+)\/map-preview\//)?.[1]);
    if (outputId) return rasterPreview(outputId);
    const id = Number(url.match(/resources\/(\d+)\/query/)?.[1]);
    return reviewQuery(
      id,
      [102, 202, 301].includes(id)
        ? lines
        : id === 401
          ? points
          : [501, 502].includes(id)
            ? zones
            : id === 201
              ? styledAfter
              : base,
    );
  });
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
  expect(
    screen.queryByRole("button", { name: "在地理工作台对比" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("查看岩性配色"));
  expect(screen.getByText("八宝山组 / T₃b²")).toBeVisible();
  expect(screen.getAllByRole("group", { name: "本地矢量图层" })).toHaveLength(
    2,
  );
  for (const unit of document.querySelectorAll(
    '[data-layer="geological-units"]',
  ))
    expect(unit.querySelector("path")).toHaveAttribute("fill", "#ffdfa4");
  expect(base.features[0]!.properties.fill_color).toBe("#4abb83");
  expect(document.querySelector('[class*="mapbox"], canvas')).toBeNull();
  expect(worker).not.toHaveBeenCalled();
  expect(
    performance
      .getEntriesByType("resource")
      .filter(
        (entry) =>
          entry.startTime >= started &&
          /mapbox|tianditu|\/tiles\b|\/styles\b|\.pbf\b/.test(entry.name),
      ),
  ).toHaveLength(0);
  expect(screen.getByText("● 几何交汇 / ○ 推测交汇")).toBeVisible();
  expect(
    document.querySelector('[data-layer="review-faults"] path'),
  ).not.toBeNull();
  expect(
    document.querySelector(
      '[data-layer="review-intersections"] circle[fill="#fff"]',
    ),
  ).not.toBeNull();
  expect(
    request.mock.calls.some(([url]) => String(url).includes("/301/query/")),
  ).toBe(false);
  fireEvent.click(screen.getByLabelText("待核查项"));
  await waitFor(() =>
    expect(
      request.mock.calls.some(([url]) => String(url).includes("/301/query/")),
    ).toBe(true),
  );
  fireEvent.click(await screen.findByText("定位检查记录 / 1 条规则命中"));
  fireEvent.click(await screen.findByText("S-02 / 实际疑点"));
  expect(screen.getByText("沿界比例较高，建议核对影像")).toBeVisible();
  fireEvent.click(screen.getByLabelText("有效蚀变"));
  for (const [label, outputId] of [
    ["待检查地质图地图", 900],
    ["修正后地质图地图", 901],
  ] as const)
    await waitFor(() =>
      expect(
        screen
          .getByLabelText(label)
          .querySelector('image[data-layer="alteration:calcite"]'),
      ).toHaveAttribute("href", rasterPreview(outputId).imageUrl),
    );
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
    "actual-edit": { name: "多要素获批修改", manifest: { version: "1.1.1" } },
  };
  const before = structuredClone(beforeReviewMap);
  before.features[0]!.properties.geo_sym = "Q";
  const after = structuredClone(before);
  after.features[0]!.properties.geo_sym = "T₃b";
  const minerals = structuredClone(before);
  minerals.features[0]!.geometry = {
    type: "Polygon",
    coordinates: [
      [
        [98.6, 35.7],
        [98.63, 35.7],
        [98.63, 35.72],
        [98.6, 35.72],
        [98.6, 35.7],
      ],
    ],
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
      featureId: "AG-mineral-1",
      action: "downweight",
      title: "矿物信号可能受到岩石背景影响",
      ruleId: "A-01",
      geometry: minerals.features[0]!.geometry,
      observations: {
        mineral: "calcite",
        raster_protocol: "alteration-pixels-v1",
      },
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
    { name: "check", status: "completed", outputs: [] },
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
    alterationRasters: [
      {
        mineral: "calcite",
        beforeOutputId: 900,
        afterOutputId: 901,
        changesOutputId: 902,
      },
    ],
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
  workflow.plan.compareFeatures = changes;
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
  };
  let completeMineralRead = () => {};
  const mineralRead = new Promise<void>((resolve) => {
    completeMineralRead = resolve;
  });
  request.mockImplementation(async (url: string) => {
    const outputId = Number(url.match(/outputs\/(\d+)\/map-preview\//)?.[1]);
    if (outputId) {
      await mineralRead;
      return rasterPreview(outputId);
    }
    const id = Number(url.match(/resources\/(\d+)\/query/)?.[1]);
    return reviewQuery(
      id,
      collections[id] ?? { type: "FeatureCollection", features: [] },
    );
  });
  const view = render(
    <App>
      <MemoryRouter>
        <style>
          {workspaceStyles}
          {tourStyles}
        </style>
        <MultiElementWorkspace
          workflow={workflow}
          suggestionId="change-1"
          onReload={() => {}}
        />
      </MemoryRouter>
    </App>,
  );
  expect(await screen.findByText("本页第2处，共3处")).toBeVisible();
  expect(document.querySelector(".multi-tour-map-stage")).toHaveAttribute(
    "data-current-change",
    "change-1",
  );
  fireEvent.click(screen.getByLabelText("上一处修改"));
  expect(await screen.findByText("本页第1处，共3处")).toBeVisible();
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
    .querySelector("svg");
  const afterCanvas = screen
    .getByLabelText("修正后地质图地图")
    .querySelector("svg");
  expect(beforeCanvas).not.toBeNull();
  expect(afterCanvas).not.toBeNull();
  const expectFocusInBothMaps = async () => {
    await waitFor(
      () => {
        const currentKey = document
          .querySelector(".multi-tour-map-stage")
          ?.getAttribute("data-current-change");
        const selected = suggestions.findIndex(
          (item) => item.id === currentKey,
        );
        expect(selected).toBeGreaterThanOrEqual(0);
        const target = reviewBounds({
          type: "FeatureCollection",
          features: [changes.features[selected]!],
        })!;
        const expected = [
          projectReviewPosition([target[0], target[1]]),
          projectReviewPosition([target[2], target[3]]),
        ];
        const vectors = screen.getAllByRole("group", { name: "本地矢量图层" });
        expect(vectors).toHaveLength(2);
        expect(vectors[0]).toHaveAttribute(
          "viewBox",
          vectors[1]!.getAttribute("viewBox"),
        );
        for (const vector of vectors) {
          expect(
            vector.querySelector('[data-layer="story-focus"] path'),
          ).not.toBeNull();
          const [left, top, width, height] = vector
            .getAttribute("viewBox")!
            .split(" ")
            .map(Number);
          for (const point of expected) {
            expect(point[0]).toBeGreaterThanOrEqual(left!);
            expect(point[0]).toBeLessThanOrEqual(left! + width!);
            expect(point[1]).toBeGreaterThanOrEqual(top!);
            expect(point[1]).toBeLessThanOrEqual(top! + height!);
          }
        }
        const maps = document.querySelectorAll(".geology-review-map-canvas");
        expect(maps).toHaveLength(2);
        for (const map of maps) {
          const canvas = map.querySelector("svg")!.getBoundingClientRect();
          const marker = map.querySelector("text")!.getBoundingClientRect();
          expect(marker.left).toBeGreaterThanOrEqual(canvas.left);
          expect(marker.right).toBeLessThanOrEqual(canvas.right);
          expect(marker.top).toBeGreaterThanOrEqual(canvas.top);
          expect(marker.bottom).toBeLessThanOrEqual(canvas.bottom);
          expect(
            Math.abs(
              (marker.left + marker.right - canvas.left - canvas.right) / 2,
            ),
          ).toBeLessThan(canvas.width * 0.15);
          expect(
            Math.abs(
              (marker.top + marker.bottom - canvas.top - canvas.bottom) / 2,
            ),
          ).toBeLessThan(canvas.height * 0.25);
        }
      },
      { timeout: 5000 },
    );
  };
  await expectFocusInBothMaps();
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
  expect(screen.getByText("本页第2处，共3处")).toBeVisible();
  await waitFor(() =>
    expect(screen.getByLabelText("当前对象前后状态")).toHaveTextContent(
      "已从最终成果删除",
    ),
  );
  await expectFocusInBothMaps();
  fireEvent.click(screen.getByLabelText("下一处修改"));
  await waitFor(() =>
    expect(
      request.mock.calls.filter(([url]) =>
        /\/outputs\/(900|901)\/map-preview\//.test(String(url)),
      ),
    ).not.toHaveLength(0),
  );
  fireEvent.click(screen.getByLabelText("上一处修改"));
  expect(screen.getByText("本页第2处，共3处")).toBeVisible();
  completeMineralRead();
  await expectFocusInBothMaps();
  expect(screen.getByLabelText("当前对象前后状态")).toHaveTextContent(
    "已从最终成果删除",
  );
  fireEvent.click(screen.getByLabelText("下一处修改"));
  await waitFor(() =>
    expect(screen.getByLabelText("当前对象前后状态")).toHaveTextContent(
      "证据权重 原记录未提供",
    ),
  );
  await waitFor(() =>
    expect(screen.getByLabelText("当前对象前后状态")).toHaveTextContent(
      "证据权重 0.4",
    ),
  );
  await expectFocusInBothMaps();
  fireEvent.click(screen.getByLabelText("上一处修改"));
  fireEvent.click(screen.getByLabelText("上一处修改"));
  fireEvent.click(screen.getByLabelText("下一处修改"));
  fireEvent.click(screen.getByLabelText("下一处修改"));
  expect(screen.getByText("本页第3处，共3处")).toBeVisible();
  await expectFocusInBothMaps();
  expect(
    request.mock.calls.filter(([url]) => String(url).includes("/301/query/")),
  ).toHaveLength(0);
  expect(screen.getByLabelText("待检查地质图地图").querySelector("svg")).toBe(
    beforeCanvas,
  );
  expect(screen.getByLabelText("修正后地质图地图").querySelector("svg")).toBe(
    afterCanvas,
  );
  expect(document.querySelectorAll(".mapboxgl-canvas")).toHaveLength(0);
  expect(
    request.mock.calls.filter(([url]) => String(url).includes("/101/query/")),
  ).toHaveLength(1);
  expect(
    request.mock.calls.filter(([url]) => String(url).includes("/201/query/")),
  ).toHaveLength(1);
  expect(screen.getByText("面积减少0.65平方公里")).toBeVisible();
  fireEvent.click(screen.getByText("定位变化的核查区"));
  expect(screen.getByLabelText("调查建议前后对比")).toBeVisible();
  fireEvent.click(screen.getByText("逐处看修改"));
  await expectFocusInBothMaps();
  await page.getByRole("button", { name: "查看全区", exact: true }).click();
  expect(screen.getByText("对象与依据")).toBeVisible();
  await waitFor(() => expect(beforeCanvas!.clientHeight).toBeGreaterThan(400));
  await page.getByRole("button", { name: "逐处看修改", exact: true }).click();
  expect(screen.getByText("本页第3处，共3处")).toBeVisible();
  await expectFocusInBothMaps();
  for (const [width, height] of [
    [820, 620],
    [1600, 1000],
  ]) {
    await page.viewport(width!, height!);
    await page.getByRole("button", { name: "查看全区", exact: true }).click();
    await waitFor(() =>
      expect(beforeCanvas!.clientHeight).toBeGreaterThanOrEqual(400),
    );
    await page.getByRole("button", { name: "逐处看修改", exact: true }).click();
    await expectFocusInBothMaps();
  }
  fireEvent.keyDown(beforeCanvas!, { key: "ArrowRight" });
  const pannedView = beforeCanvas!.getAttribute("viewBox");
  expect(pannedView).toBe(afterCanvas!.getAttribute("viewBox"));
  await page.viewport(1600, 900);
  await waitFor(() => {
    expect(beforeCanvas!.clientHeight).toBeGreaterThanOrEqual(220);
    expect(beforeCanvas!.clientHeight).toBeLessThanOrEqual(300);
  });
  expect(beforeCanvas).toHaveAttribute("viewBox", pannedView);
  fireEvent.click(screen.getByLabelText("上一处修改"));
  fireEvent.click(screen.getByLabelText("下一处修改"));
  await expectFocusInBothMaps();
  expect(screen.getAllByRole("group", { name: "本地矢量图层" })).toHaveLength(
    2,
  );
  expect(screen.getByLabelText("待检查地质图地图").querySelector("svg")).toBe(
    beforeCanvas,
  );
  expect(screen.getByLabelText("修正后地质图地图").querySelector("svg")).toBe(
    afterCanvas,
  );
  for (const id of [101, 201, 301])
    expect(
      request.mock.calls.filter(([url]) =>
        String(url).includes(`/${id}/query/`),
      ),
    ).toHaveLength(id === 301 ? 0 : 1);
  await page.screenshot({
    path: "../../test-results/multi-element-change-tour.png",
    animations: "disabled",
    fullPage: true,
  });
  const reads = request.mock.calls.length;
  fireEvent.click(screen.getByRole("button", { name: "查看构造章节" }));
  expect(screen.getByText("本页第1处，共1处")).toBeVisible();
  await waitFor(() =>
    expect(screen.getByLabelText("当前对象前后状态")).toHaveTextContent(
      "已从最终成果删除",
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "查看矿物章节" }));
  expect(screen.getByText("本页第1处，共1组")).toBeVisible();
  await waitFor(() =>
    expect(screen.getByLabelText("当前对象前后状态")).toHaveTextContent(
      "证据权重 0.4",
    ),
  );
  expect(request).toHaveBeenCalledTimes(reads);
  await waitFor(() =>
    expect(sessionStorage.getItem("geology-story:review-workflow")).toContain(
      '"chapter":"alteration"',
    ),
  );
  view.unmount();
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
  expect(await screen.findByText("本页第1处，共1组")).toBeVisible();
  await waitFor(() =>
    expect(screen.getByLabelText("当前对象前后状态")).toHaveTextContent(
      "证据权重 0.4",
    ),
  );
  await page.viewport(1600, 900);
});

it("2.0仅显示修正后远景目标单图、连续色带与实际依据", async () => {
  const workflow = reviewWorkflow();
  workflow.workflowType = "geology_multi_element_reasoning";
  workflow.plan.inputs = { lithology: 101, faults: 102 };
  workflow.plan.multiElementMap = {
    before: { lithology: 101, faults: 102 },
    after: { lithology: 201, faults: 202 },
    prospectProtocol: "after_only_v2",
    afterProspects: 502,
    prospectHeatmapOutputId: 803,
  };
  const targets = structuredClone(beforeReviewMap);
  targets.features = [targets.features[0]!];
  targets.features[0]!.properties = {
    zone_id: "P001",
    priority_rank: 1,
    area_km2: 0.45,
    explanation:
      "构造支持覆盖100%，250米邻域内组合满足2类加权矿物，基岩条件满足。",
  };
  request.mockImplementation(async (url: string) => {
    if (url.includes("outputs/803/map-preview"))
      return {
        ...rasterPreview(803),
        metadata: {
          colorRamp: [
            { value: 0, label: "低", color: "#2166acff" },
            { value: 0.5, label: "中", color: "#ffff80ff" },
            { value: 1, label: "高", color: "#d73027ff" },
          ],
        },
      };
    const id = Number(url.match(/resources\/(\d+)\/query/)?.[1]);
    return reviewQuery(
      id,
      id === 502 ? targets : [102, 202].includes(id) ? lines : beforeReviewMap,
    );
  });
  const view = render(
    <App>
      <MemoryRouter>
        <MultiElementWorkspace
          workflow={workflow}
          suggestionId={null}
          onReload={vi.fn()}
        />
      </MemoryRouter>
    </App>,
  );
  await screen.findByText("优先核查的找矿目标");
  await screen.findByLabelText("远景相对置信度色带");
  fireEvent.click(screen.getByRole("button", { name: "查看调查建议章节" }));
  expect(
    view.container.querySelectorAll(".geology-review-map-pair section"),
  ).toHaveLength(1);
  expect(view.container.querySelector('image[href*="803"]')).not.toBeNull();
  expect(screen.queryByText("这些处理怎样改变调查建议")).toBeNull();
  expect(
    request.mock.calls.some(([url]) =>
      String(url).includes("resources/501/query"),
    ),
  ).toBe(false);
  fireEvent.click(screen.getByText(/P001 ·/));
  expect(screen.getByText(/构造支持覆盖100%/)).toBeVisible();
});
