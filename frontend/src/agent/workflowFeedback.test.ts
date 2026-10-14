import { expect, it } from "vitest";
import { reviewWorkflow } from "../map/geologyReview.testFixtures";
import { workflowStageLabel } from "./workflowFeedback";

it.each([
  {
    taskId: null,
    stageStatus: "pending",
    workflowStatus: "failed",
    label: "形成修正建议",
  },
  {
    taskId: "compute-edit",
    stageStatus: "running",
    workflowStatus: "waiting_compute",
    label: "正在修正地图",
  },
  {
    taskId: "compute-edit",
    stageStatus: "completed",
    workflowStatus: "running",
    label: "已修正地图",
  },
  {
    taskId: "compute-edit",
    stageStatus: "failed",
    workflowStatus: "failed",
    label: "地图修正",
  },
] as const)(
  "地质检查edit阶段按真实提交状态显示：$label",
  ({ taskId, stageStatus, workflowStatus, label }) => {
    const workflow = reviewWorkflow();
    workflow.status = workflowStatus;
    workflow.plan = {
      phase: "decide",
      stageIndex: 0,
      stages: [{ name: "edit", taskId, status: stageStatus }],
    };
    expect(workflowStageLabel(workflow)).toBe(label);
  },
);
