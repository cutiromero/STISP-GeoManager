import { render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { computeApi } from "../api/compute";
import type { ComputeTask } from "../api/generated/types.gen";
import ComputeQualitySummary from "./ComputeQualitySummary";
import RunComputeTasks from "./RunComputeTasks";
import { liveComputeTask } from "./computeFlow.testFixtures";
import "./agent.css";

function reviewTask(): ComputeTask {
  const task = liveComputeTask("succeeded");
  const output = task.outputs[0];
  const qualityCheck = {
    version: 1,
    status: "needs_review",
    summary: "实际任务检查 24 个要素，其中 2 个需要审核。",
    metrics: {
      totalFeatures: 24,
      validAfter: 24,
      needsReview: 2,
      failed: 0,
      maxAreaChangePct: 8,
    },
  };
  return {
    ...task,
    id: "actual-repair-task",
    algorithmName: "面几何修复",
    outputs: [
      {
        ...output,
        id: 50,
        key: "repaired",
        label: "修复候选",
        kind: "vector",
        metadata: { qualityCheck },
      },
      {
        ...output,
        id: 51,
        key: "repair_log",
        label: "修复记录",
        kind: "table",
        metadata: { qualityCheck },
        downloadUrl: "/api/compute/outputs/51/download/",
      },
      {
        ...output,
        id: 52,
        key: "repair_audit",
        label: "完整审核包",
        kind: "archive",
        fileName: "repair_audit.zip",
        metadata: { qualityCheck },
        downloadUrl: "/api/compute/outputs/52/download/",
      },
    ],
  };
}
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(computeApi, "preview").mockResolvedValue({
    kind: "table",
    metadata: { rows: 150 },
    columns: [
      "repair_row",
      "needs_review",
      "review_reasons",
      "non_polygon_parts",
      "candidate_type",
    ],
    rows: [
      [
        21,
        "True",
        "包含降维片段，完整候选已保留在审核包",
        4,
        "GeometryCollection",
      ],
      [22, "False", "", 0, "Polygon"],
    ],
  });
  vi.spyOn(computeApi, "task").mockResolvedValue(reviewTask());
});
function show(content: React.ReactNode) {
  return render(
    <AntApp>
      <MemoryRouter>{content}</MemoryRouter>
    </AntApp>,
  );
}
it("shows the actual quality summary once and reads dimensional fragments from the actual log", async () => {
  show(<ComputeQualitySummary task={reviewTask()} />);
  expect(
    screen.getAllByText("实际任务检查 24 个要素，其中 2 个需要审核。"),
  ).toHaveLength(1);
  expect(screen.getAllByText("24", { selector: "dd" })).toHaveLength(2);
  await screen.findByText("记录第 21 项");
  expect(screen.getByText("非面／降维片段：4")).toBeInTheDocument();
  expect(
    screen.getByText("包含降维片段，完整候选已保留在审核包"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("已显示前 2 条记录，完整记录请下载审核包。"),
  ).toBeInTheDocument();
  expect(computeApi.preview).toHaveBeenCalledWith(51);
  expect(
    screen.getByRole("button", { name: "下载完整候选与审核包" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("50")).not.toBeInTheDocument();
  expect(screen.queryByText("51")).not.toBeInTheDocument();
});
it("keeps ordinary imports hidden during review, while retaining the explicit review evidence", async () => {
  show(
    <RunComputeTasks
      taskIds={["actual-repair-task"]}
      refreshKey="review"
      reviewing
      autoImport
    />,
  );
  await screen.findByText("候选结果需要审核");
  await screen.findByText("记录第 21 项");
  expect(
    screen.queryByRole("button", { name: "将结果入库" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getAllByText("等待审核确认后继续保存成果").length,
  ).toBeGreaterThan(0);
});
it("shows passed checks without inventing repair details or fetching a log", () => {
  const task = reviewTask();
  task.outputs = [
    {
      ...task.outputs[0],
      metadata: {
        qualityCheck: {
          version: 1,
          status: "passed",
          summary: "当前任务质量检查通过。",
          metrics: {},
        },
      },
    },
  ];
  show(<ComputeQualitySummary task={task} />);
  expect(screen.getByText("当前任务质量检查通过。")).toBeInTheDocument();
  expect(screen.queryByText("核对修复原因与降维片段")).not.toBeInTheDocument();
  expect(computeApi.preview).not.toHaveBeenCalled();
});
