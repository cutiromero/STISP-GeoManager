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
      ([url, options]) => !options || String(url).endsWith("/query/"),
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
