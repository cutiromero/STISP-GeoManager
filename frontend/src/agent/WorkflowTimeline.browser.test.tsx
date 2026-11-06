import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { expect, it } from "vitest";
import type { AgentWorkflowStep } from "../api/generated/types.gen";
import WorkflowDecisionTimeline from "./WorkflowDecisionTimeline";
import { mainWorkflowSteps, workflowStepTitle } from "./workflowTimeline";

function step(
  id: number,
  values: Partial<AgentWorkflowStep>,
): AgentWorkflowStep {
  return {
    id,
    sequence: id,
    kind: "model_activity",
    status: "succeeded",
    message: "",
    action: {},
    inputRefs: {},
    outputRefs: {},
    metrics: {},
    computeTaskId: "",
    errorCode: "",
    startedAt: "",
    finishedAt: "",
    ...values,
  };
}

it("shows meaningful process steps and preserves all otherwise empty records in audit", async () => {
  const steps = [
    step(1, {
      status: "failed",
      action: { stage: "字段识别" },
      outputRefs: {
        modelActivity: {
          stage: "字段识别",
          status: "failed",
          thinkingChars: 12,
          outputChars: 0,
        },
      },
    }),
    step(2, {
      action: { stage: "字段识别" },
      outputRefs: {
        modelActivity: {
          stage: "字段识别",
          status: "complete",
          thinkingChars: 30,
          outputChars: 45,
          thinkingText: "实际返回的思考片段",
        },
      },
    }),
    step(3, { kind: "field_mapping_confirmed", message: "资料与字段已确认" }),
    step(4, { kind: "review_feedback", message: "用户审核通过，继续处理" }),
    step(5, { kind: "working_copies", message: "分析资料已准备" }),
    step(6, {
      kind: "collect_results",
      message: "本步真实结果已入库",
      computeTaskId: "task-1",
    }),
  ];
  expect(mainWorkflowSteps(steps).map((value) => value.id)).toEqual([3, 5, 6]);
  render(
    <WorkflowDecisionTimeline
      concise
      steps={steps}
      taskNames={{ "task-1": "三要素检查" }}
    />,
  );
  expect(screen.getByText("1. 资料与字段已确认")).toBeInTheDocument();
  expect(screen.getByText("3. 三要素检查：成果已就绪")).toBeInTheDocument();
  expect(screen.queryByText(/模型分析：字段识别/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("详细运行记录 / 6 条"));
  await waitFor(() =>
    expect(screen.getAllByText(/模型分析：字段识别/)).toHaveLength(2),
  );
  const audit = screen
    .getByText("详细运行记录 / 6 条")
    .closest(".ant-collapse-item")!;
  expect(
    within(audit as HTMLElement).getByText("已重新分析"),
  ).toBeInTheDocument();
  const titles = [
    ...audit.querySelectorAll(".agent-decision-step-heading strong"),
  ];
  expect(titles).toHaveLength(6);
  expect(
    titles.every((title) => /^\d+\.\s+\S/.test(title.textContent ?? "")),
  ).toBe(true);
});

it("always provides a title for a status-only technical step", () => {
  expect(workflowStepTitle(step(1, { kind: "analysis_model_attempt" }))).toBe(
    "模型响应校验",
  );
  expect(workflowStepTitle(step(2, { kind: "unknown_internal" }))).toBe(
    "运行记录",
  );
  expect(mainWorkflowSteps([step(1, {})])).toEqual([]);
});
