import { beforeEach, expect, it, vi } from "vitest";
import type { ResourceProfileResponse } from "../api/generated/types.gen";
import { createEmptyLayerGroup } from "../utils/layerFactory";
import { resetProjectSession, setActiveProject } from "../projects/session";
import {
  afterReviewMap,
  beforeReviewMap,
  reviewDifferences,
  reviewQuery,
  reviewWorkflow,
  comparisonProjection,
} from "./geologyReview.testFixtures";
import { loadWorkbenchReviewComparison } from "./geologyWorkbenchCompareData";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../api/client", () => ({
  requestJson: request,
  requestForm: vi.fn(),
}));

export function comparisonProfile(id: number): ResourceProfileResponse {
  return {
    resource: {
      ...createEmptyLayerGroup("测试").sourceResource,
      id,
      name:
        id === 101 ? "待检查地质图" : id === 201 ? "修正后地质图" : "修改范围",
      isQueryable: true,
    },
    fields: [],
    featureCount: 2,
    geometryType: "Polygon",
    bounds: [98.4, 35.6, 98.45, 35.62],
  };
}

function respond(actual = true) {
  request.mockImplementation(async (url: string) => {
    if (url.includes("/workflows/")) return reviewWorkflow(actual);
    const id = Number(url.match(/resources\/(\d+)\//)?.[1]);
    if (url.endsWith("/profile/")) return comparisonProfile(id);
    return reviewQuery(
      id,
      id === 101
        ? beforeReviewMap
        : id === 201
          ? afterReviewMap
          : reviewDifferences,
    );
  });
}
const registerLayer = vi.fn().mockResolvedValue(undefined);
const load = (options = {}) =>
  loadWorkbenchReviewComparison({
    workflowId: "review-workflow",
    projectId: "3",
    projectTagId: "3",
    registerLayer,
    ...options,
  });

it("先显示两张岩性图，不等待后续构造和蚀变请求完成", async () => {
  const workflow = reviewWorkflow(true);
  workflow.workflowType = "geology_generic";
  workflow.plan.multiElementMap = {
    before: { lithology: 101, faults: 102 },
    after: { lithology: 201, faults: 202 },
    checks: [],
    changes: [],
  };
  workflow.plan.algorithms = {
    "geology-multi-apply": { manifest: { outputs: [{ key: "final_faults" }] } },
  };
  let finish: (() => void) | undefined;
  const blocked = new Promise<void>((resolve) => {
    finish = resolve;
  });
  request.mockImplementation(async (url: string) => {
    if (url.includes("/workflows/")) return workflow;
    const id = Number(url.match(/resources\/(\d+)\//)?.[1]);
    if (id === 102 || id === 202) await blocked;
    return url.endsWith("/profile/")
      ? comparisonProfile(id)
      : reviewQuery(
          id,
          id === 101
            ? beforeReviewMap
            : id === 201
              ? afterReviewMap
              : { type: "FeatureCollection", features: [] },
        );
  });
  const onPrimary = vi.fn();
  const pending = load({ onPrimary });
  await vi.waitFor(() => expect(onPrimary).toHaveBeenCalledOnce());
  expect(onPrimary.mock.calls[0]![0].before).toEqual(beforeReviewMap);
  expect(onPrimary.mock.calls[0]![0].after).toEqual(afterReviewMap);
  finish!();
  await pending;
});

it("按需加载模式不读取辅助图层与修改记录；展开时复用主图并去重辅助请求", async () => {
  const workflow = reviewWorkflow(true);
  workflow.workflowType = "geology_generic";
  workflow.plan.multiElementMap = {
    before: { lithology: 101, faults: 102 },
    after: { lithology: 201, faults: 302 },
    beforeAlterations: 600,
    alterations: 601,
    changes: [202],
    checks: [],
  };
  request.mockImplementation(async (url: string) => {
    if (url.includes("/workflows/")) return workflow;
    const id = Number(url.match(/resources\/(\d+)\//)?.[1]);
    return url.endsWith("/profile/")
      ? comparisonProfile(id)
      : reviewQuery(
          id,
          id === 101
            ? beforeReviewMap
            : id === 201
              ? afterReviewMap
              : id === 202
                ? reviewDifferences
                : { type: "FeatureCollection", features: [] },
        );
  });
  const result = await load({ deferOverlays: true });
  expect(
    request.mock.calls.filter(([url]) => String(url).includes("/workflows/")),
  ).toHaveLength(1);
  expect(String(request.mock.calls[0]![0])).toContain("view=compare");
  expect(result.differences.features).toHaveLength(0);
  expect(result.overlays).toBeUndefined();
  const queryIds = () =>
    request.mock.calls
      .filter(([url]) => String(url).endsWith("/query/"))
      .map(([url]) => Number(String(url).match(/resources\/(\d+)\//)?.[1]));
  expect(queryIds()).toEqual([101, 201]);
  expect(
    registerLayer.mock.calls.map(([profile]) => profile.resource.id),
  ).toEqual([101, 201]);
  await result.loadOverlays!("faults");
  expect(queryIds().sort()).toEqual([101, 102, 201, 302]);
  const [first, second] = await Promise.all([
    result.loadOverlays!(),
    result.loadOverlays!(),
  ]);
  expect(first).toBe(second);
  expect(queryIds().sort()).toEqual([101, 102, 201, 302, 600, 601]);
});

it.each(["geology_generic", "geology_multi_element_reasoning"])(
  "%s在仅保留正式成果时仍从任务文件生成真实讲解与前后对比",
  async (workflowType) => {
    const workflow = reviewWorkflow(true);
    workflow.workflowType = workflowType;
    const suggestion = {
      ...workflow.modificationReview!.suggestions[0]!,
      kind: "multi_element" as const,
      featureId: "unit-a",
      ruleId: "L-01",
      action: "set_code",
      element: "lithology" as const,
    };
    workflow.modificationReview = {
      proposalHash: "frozen",
      suggestions: [suggestion],
      approvedSuggestionIds: [suggestion.id],
    };
    workflow.plan.multiElementMap = {
      before: { lithology: 101, faults: 102 },
      after: { lithology: 201, faults: 202 },
      checks: [],
      changes: [],
      alterations: 601,
      intersections: 401,
      beforeProspects: 501,
      afterProspects: 502,
    };
    workflow.plan.stages = [
      {
        name: "check",
        status: "completed",
        results: [{ key: "alterations", kind: "vector", outputId: 700 }],
      },
      {
        name: "apply",
        status: "completed",
        taskId: "actual-task",
        approvedEdits: [
          {
            feature_id: "unit-a",
            rule_id: "L-01",
            action: "set_code",
            target_code: "T3b",
            weight: 1,
          },
        ],
        results: [
          {
            key: "changes",
            taskId: "actual-task",
            outputId: 709,
            checksum: "a".repeat(64),
            scope: "all",
            rowCount: 1,
            rows: [
              {
                feature_id: "unit-a",
                rule_id: "L-01",
                action: "set_code",
                target_code: "T3b",
                weight: "1",
                actual_changed: "True",
                new_code: "T3b",
              },
            ],
          },
          ...[
            "changes_lithology_issues",
            "changes_fault_issues",
            "changes_alteration_issues",
          ].map((key, index) => ({
            key,
            kind: "vector",
            outputId: 710 + index,
          })),
        ],
      },
      {
        name: "relations",
        status: "completed",
        results: [
          { key: "before_intersections", kind: "vector", outputId: 720 },
        ],
      },
    ];
    request.mockImplementation(async (url: string) => {
      if (url.includes("/workflows/"))
        return comparisonProjection(workflow, url);
      if (url.includes("/compute/outputs/")) {
        const outputId = Number(url.match(/outputs\/(\d+)\//)?.[1]);
        const feature = structuredClone(beforeReviewMap.features[0]!);
        feature.properties = {
          feature_id: "unit-a",
          rule_id: "L-01",
          suggested_action: "set_code",
          state: "keep",
        };
        return {
          kind: "vector",
          columns: [],
          rows: [],
          metadata: {},
          geojson: {
            type: "FeatureCollection",
            features: [700, 710, 720].includes(outputId) ? [feature] : [],
          },
        };
      }
      const id = Number(url.match(/resources\/(\d+)\//)?.[1]);
      if (url.endsWith("/profile/")) return comparisonProfile(id);
      return reviewQuery(id, beforeReviewMap);
    });
    const result = await load();
    expect(result.tour).toBeUndefined();
    const page = await result.loadChanges!(0);
    expect(page.tour).toHaveLength(1);
    expect(page.tour![0]!.action).toBe("set_code");
    expect(
      result.overlays.find((item) => item.key === "alterations")!.before
        .features,
    ).toHaveLength(1);
    expect(
      result.overlays.find((item) => item.key === "intersections")!.before
        .features,
    ).toHaveLength(1);
    expect(
      request.mock.calls.filter(([url]) =>
        String(url).includes("/compute/outputs/"),
      ),
    ).toHaveLength(2);
    expect(
      request.mock.calls.some(([url]) => String(url).includes("/import/")),
    ).toBe(false);
    expect(
      registerLayer.mock.calls.some(([profile]) =>
        [700, 710, 711, 712, 720].includes(profile.resource.id),
      ),
    ).toBe(false);
  },
);

beforeEach(() => {
  request.mockReset();
  registerLayer.mockClear();
  resetProjectSession();
  setActiveProject("3");
  respond();
});

it("uses complete real responses once and registers all three normal layers with their catalog names", async () => {
  const result = await load();
  expect(result.before).toEqual(beforeReviewMap);
  expect(result.after).toEqual(afterReviewMap);
  expect(result.differences).toEqual(reviewDifferences);
  expect(result.beforeName).toBe("待检查地质图");
  expect(result.afterName).toBe("修正后地质图");
  expect(
    registerLayer.mock.calls.map(([profile]) => profile.resource.id),
  ).toEqual([101, 201, 202]);
  for (const [profile, query] of registerLayer.mock.calls) {
    expect(query.resourceId).toBe(profile.resource.id);
    expect(query.returnedCount).toBe(query.geojson.features.length);
    expect(query.limitExceeded).toBe(false);
  }
  expect(
    request.mock.calls.filter(([url]) => String(url).endsWith("/query/")),
  ).toHaveLength(3);
  expect(
    request.mock.calls.every(
      ([url, options]) =>
        !options ||
        String(url).endsWith("/query/") ||
        Object.keys(options).every((key) =>
          ["validate", "view", "signal", "suggestionId"].includes(key),
        ),
    ),
  ).toBe(true);
});

it("registers only the input before approval and preserves saved suggestion previews", async () => {
  respond(false);
  const result = await load();
  expect(result.after).toBeNull();
  expect(result.differences.features).toHaveLength(2);
  expect(registerLayer).toHaveBeenCalledOnce();
  expect(registerLayer.mock.calls[0]![0].resource.id).toBe(101);
});

it("refuses another project without reading a workflow or registering any layer", async () => {
  await expect(load({ projectTagId: "4" })).rejects.toThrow(
    "切换到检查任务所属项目",
  );
  expect(request).not.toHaveBeenCalled();
  expect(registerLayer).not.toHaveBeenCalled();
});

it.each(["approval", "partial", "wrong-project", "wrong-workflow"])(
  "rejects %s before any result queries",
  async (kind) => {
    const workflow = reviewWorkflow(true);
    if (kind === "approval")
      workflow.modificationReview!.approvedSuggestionIds = [];
    if (kind === "partial")
      workflow.plan.stages = [
        {
          identifier: "geology-map-correct",
          outputs: [{ key: "corrected", resourceId: 201 }],
        },
      ];
    if (kind === "wrong-project") workflow.projectId = 4;
    if (kind === "wrong-workflow")
      workflow.workflowType = "ecology_investigation";
    request.mockResolvedValueOnce(workflow);
    await expect(load()).rejects.toThrow();
    expect(request).toHaveBeenCalledOnce();
    expect(registerLayer).not.toHaveBeenCalled();
  },
);

it("does not add a layer after the project or mounted task changes during a read", async () => {
  let current = true;
  request.mockImplementation(async (url: string) => {
    if (url.includes("/workflows/")) return reviewWorkflow(true);
    if (url.endsWith("/profile/")) return comparisonProfile(101);
    current = false;
    return reviewQuery(101, beforeReviewMap);
  });
  await expect(load({ isCurrent: () => current })).rejects.toMatchObject({
    name: "AbortError",
  });
  expect(registerLayer).not.toHaveBeenCalled();
});

it("rejects truncated data rather than registering a partial comparison", async () => {
  request.mockImplementation(async (url: string) => {
    if (url.includes("/workflows/")) return reviewWorkflow(true);
    if (url.endsWith("/profile/")) return comparisonProfile(101);
    return { ...reviewQuery(101, beforeReviewMap), limitExceeded: true };
  });
  await expect(load()).rejects.toThrow("超过双图预览范围");
  expect(registerLayer).not.toHaveBeenCalled();
});
