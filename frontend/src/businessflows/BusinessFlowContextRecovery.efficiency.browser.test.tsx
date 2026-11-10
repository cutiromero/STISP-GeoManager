import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { businessFlowsApi } from "../api/businessFlows";
import BusinessFlowActivity from "./BusinessFlowActivity";
import { businessFlowRun } from "./businessFlow.testFixtures";

function waiting() {
  const flow = businessFlowRun();
  flow.nodes[0]!.status = "waiting_context";
  flow.nodes[0]!.contextManagement = {
    nodeId: "analyse",
    level: 2,
    noticeSummary: ["optional：仅保留索引摘要；原始18000字节，保留120字节。"],
  };
  flow.nodes[0]!.contextRecovery = {
    nodeId: "analyse",
    level: 3,
    beforeTokens: 40000,
    afterTokens: 33000,
    evidence: [
      { id: "required", title: "必需资料", bytes: 12000, required: true },
      { id: "optional", title: "补充资料", bytes: 18000, required: false },
    ],
  };
  return flow;
}

function show() {
  const flow = waiting();
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

it("shows compaction and retries the current node without human approval or reads", async () => {
  const flow = show();
  expect(screen.getByText("本节点输入已整理 · 第2档")).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "节点上下文等待" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "批准当前节点" }),
  ).not.toBeInTheDocument();
  fireEvent.change(
    screen.getByRole("textbox", { name: "跳过的非必需证据编号" }),
    { target: { value: "optional" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "跳过所填证据并重试" }));
  await waitFor(() => expect(businessFlowsApi.decide).toHaveBeenCalledOnce());
  expect(businessFlowsApi.decide).toHaveBeenCalledWith(
    flow.id,
    expect.objectContaining({
      nodeId: "analyse",
      revision: flow.revision,
      decision: "retry_context",
      skipEvidenceIds: ["optional"],
      idempotencyKey: expect.any(String),
    }),
  );
  expect(businessFlowsApi.run).not.toHaveBeenCalled();
});

it("sends an explicit smaller sample scope through the original decision API", async () => {
  show();
  fireEvent.click(screen.getByRole("button", { name: "缩小范围并重试" }));
  await waitFor(() => expect(businessFlowsApi.decide).toHaveBeenCalledOnce());
  expect(businessFlowsApi.decide).toHaveBeenCalledWith(
    expect.any(String),
    expect.objectContaining({
      decision: "retry_context",
      contextScope: { maxItems: 1, maxTextCharacters: 250 },
    }),
  );
});

it("stops through cancel instead of a fabricated approval", async () => {
  show();
  fireEvent.click(screen.getByRole("button", { name: "停止任务" }));
  await waitFor(() => expect(businessFlowsApi.cancel).toHaveBeenCalledOnce());
  expect(businessFlowsApi.decide).not.toHaveBeenCalled();
});
