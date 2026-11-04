import { beforeEach, expect, it, vi } from "vitest";
import { computeApi } from "../api/compute";
import { reviewWorkflow } from "./geologyReview.testFixtures";
import { queryWorkflowVectors } from "./workflowOutputMaps";

vi.mock("../api/compute", () => ({ computeApi: { vectorPreview: vi.fn() } }));
beforeEach(() => vi.clearAllMocks());

it("直接读取任务中间输出，不请求导入或资源详情", async () => {
  const workflow = reviewWorkflow(true);
  workflow.plan.stages = [
    {
      name: "relations",
      status: "completed",
      results: [{ key: "before_intersections", kind: "vector", outputId: 900 }],
    },
  ];
  const geojson = { type: "FeatureCollection" as const, features: [] };
  vi.mocked(computeApi.vectorPreview).mockResolvedValue({
    kind: "vector",
    metadata: {},
    columns: [],
    rows: [],
    geojson,
  });
  expect(
    await queryWorkflowVectors(workflow, "relations", ["before_intersections"]),
  ).toEqual(geojson);
  expect(computeApi.vectorPreview).toHaveBeenCalledExactlyOnceWith(900);
});

it("未运行阶段不读取，已完成但缺文件不伪装为空图", async () => {
  const workflow = reviewWorkflow();
  expect(
    (
      await queryWorkflowVectors(workflow, "relations", [
        "before_intersections",
      ])
    ).features,
  ).toEqual([]);
  expect(computeApi.vectorPreview).not.toHaveBeenCalled();
  workflow.plan.stages = [
    { name: "relations", status: "completed", results: [] },
  ];
  await expect(
    queryWorkflowVectors(workflow, "relations", ["before_intersections"]),
  ).rejects.toThrow("缺少完整空间输出");
});

it("保留权限错误，不退回导入或未校验几何", async () => {
  const workflow = reviewWorkflow();
  workflow.plan.stages = [
    {
      name: "check",
      status: "completed",
      results: [{ key: "alterations", kind: "vector", outputId: 901 }],
    },
  ];
  const denied = new Error("无权访问");
  vi.mocked(computeApi.vectorPreview).mockRejectedValue(denied);
  await expect(
    queryWorkflowVectors(workflow, "check", ["alterations"]),
  ).rejects.toBe(denied);
});
