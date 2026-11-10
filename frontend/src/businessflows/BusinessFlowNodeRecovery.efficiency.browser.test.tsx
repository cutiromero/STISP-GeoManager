import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { businessFlowsApi } from "../api/businessFlows";
import BusinessFlowActivity, {
  readableBusinessFlowEvents,
} from "./BusinessFlowActivity";
import { businessFlowRun } from "./businessFlow.testFixtures";

function show(allowSkip = false) {
  const flow = businessFlowRun();
  flow.nodes[0]!.status = "waiting_recovery";
  flow.nodes[0]!.recovery = {
    reason: "目标字段不存在",
    question: "请确认资料对应关系",
    attempts: ["补充映射：字段不存在"],
    allowSkip,
    options: ["retry_recovery", "cancel"],
    failure: { code: "MISSING_FIELD", remedy: "complete_mapping" },
  };
  render(
    <App>
      <MemoryRouter>
        <BusinessFlowActivity flow={flow} onChanged={vi.fn()} />
      </MemoryRouter>
    </App>,
  );
  return flow;
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(businessFlowsApi, "run");
  vi.spyOn(businessFlowsApi, "decide").mockResolvedValue(
    businessFlowRun({ status: "queued" }),
  );
  vi.spyOn(businessFlowsApi, "cancel").mockResolvedValue(
    businessFlowRun({ status: "cancelled" }),
  );
});

it("sends replacement data and parameters without approval or history refresh", async () => {
  const flow = show();
  expect(
    screen.getByRole("region", { name: "节点失败恢复" }),
  ).toBeInTheDocument();
  expect(screen.getByText("补充映射：字段不存在")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("恢复输入数据"), {
    target: { value: '{"source":99}' },
  });
  fireEvent.change(screen.getByLabelText("恢复算子参数"), {
    target: { value: '{"threshold":0.5}' },
  });
  fireEvent.change(screen.getByLabelText("恢复说明或回答"), {
    target: { value: "换用已核实数据" },
  });
  fireEvent.click(screen.getByRole("button", { name: "从本节点继续" }));
  await waitFor(() => expect(businessFlowsApi.decide).toHaveBeenCalledOnce());
  expect(businessFlowsApi.decide).toHaveBeenCalledWith(
    flow.id,
    expect.objectContaining({
      nodeId: "analyse",
      revision: flow.revision,
      decision: "retry_recovery",
      recoveryInputs: { source: 99 },
      recoveryParameters: { threshold: 0.5 },
      feedback: "换用已核实数据",
      idempotencyKey: expect.any(String),
    }),
  );
  expect(businessFlowsApi.run).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: "跳过本节点" }),
  ).not.toBeInTheDocument();
});

it("rejects invalid JSON locally and permits only explicit configured skip", async () => {
  show(true);
  fireEvent.change(screen.getByLabelText("恢复输入数据"), {
    target: { value: "[]" },
  });
  fireEvent.click(screen.getByRole("button", { name: "从本节点继续" }));
  expect(screen.getByText("资料与参数必须是 JSON 对象。")).toBeInTheDocument();
  expect(businessFlowsApi.decide).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "跳过本节点" }));
  await waitFor(() => expect(businessFlowsApi.decide).toHaveBeenCalledOnce());
  expect(businessFlowsApi.decide).toHaveBeenCalledWith(
    expect.any(String),
    expect.objectContaining({ decision: "skip_node" }),
  );
});

it("stops through cancel instead of an artificial approval", async () => {
  show();
  fireEvent.click(screen.getByRole("button", { name: "停止任务" }));
  await waitFor(() => expect(businessFlowsApi.cancel).toHaveBeenCalledOnce());
  expect(businessFlowsApi.decide).not.toHaveBeenCalled();
});

it("keeps consecutive tool steps instead of collapsing their activity", () => {
  const event = {
    id: 1,
    nodeId: "analyse",
    actor: "executor" as const,
    kind: "node_tool_step",
    status: "running",
    message: "查询可用算子",
    createdAt: "2026-11-11T00:00:00Z",
  };
  const events = readableBusinessFlowEvents([
    event,
    { ...event, id: 2, message: "检查输入差距" },
  ]);
  expect(events).toHaveLength(2);
});
