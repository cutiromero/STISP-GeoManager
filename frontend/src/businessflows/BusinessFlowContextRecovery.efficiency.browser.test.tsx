import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { businessFlowsApi } from "../api/businessFlows";
import BusinessFlowActivity from "./BusinessFlowActivity";
import BusinessFlowContextRecovery from "./BusinessFlowContextRecovery";
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

it("does not offer evidence reduction that the professional backend refuses", () => {
  render(
    <App>
      <BusinessFlowContextRecovery
        node={waiting().nodes[0]!}
        busy={false}
        legacy
        onRetry={vi.fn()}
        onStop={vi.fn()}
      />
    </App>,
  );
  expect(screen.getByRole("button", { name: "重试当前节点" })).toBeEnabled();
  expect(
    screen.queryByRole("button", { name: "缩小范围并重试" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("textbox", { name: "跳过的非必需证据编号" }),
  ).not.toBeInTheDocument();
});

it("distinguishes request quota from context size without offering ineffective reduction", () => {
  const node = waiting().nodes[0]!;
  node.contextRecovery = {
    ...node.contextRecovery!,
    kind: "model_call_limit",
    budgetScope: "task",
  };
  render(
    <App>
      <BusinessFlowContextRecovery
        node={node}
        busy={false}
        onRetry={vi.fn()}
        onStop={vi.fn()}
      />
    </App>,
  );
  expect(screen.getByText(/模型请求额度不足/)).toBeVisible();
  expect(screen.getByRole("button", { name: "额度更新后继续" })).toBeEnabled();
  expect(
    screen.queryByRole("button", { name: "缩小范围并重试" }),
  ).not.toBeInTheDocument();
});

it("retries a model protocol wait without presenting it as input size or permission to approve", async () => {
  const node = waiting().nodes[0]!;
  node.contextRecovery = {
    ...node.contextRecovery!,
    kind: "model_protocol_error",
  };
  const retry = vi.fn();
  render(
    <App>
      <BusinessFlowContextRecovery
        node={node}
        busy={false}
        onRetry={retry}
        onStop={vi.fn()}
      />
    </App>,
  );
  expect(screen.getByText(/审核响应需要重试/)).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "缩小范围并重试" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "重试本次审核" }));
  expect(retry).toHaveBeenCalledExactlyOnceWith({ feedback: "" });
});

it.each([
  "model_response_error",
  "model_request_error",
  "review_rejected",
  "platform_error",
])(
  "sends bounded human guidance for %s through the original checkpoint",
  async (kind) => {
    const flow = waiting();
    flow.nodes[0]!.contextRecovery = {
      ...flow.nodes[0]!.contextRecovery!,
      kind,
      actor: "executor",
      reason: "需要核对当前节点诊断",
    };
    render(
      <App>
        <MemoryRouter>
          <BusinessFlowActivity flow={flow} onChanged={vi.fn()} />
        </MemoryRouter>
      </App>,
    );
    const input = screen.getByRole("textbox", { name: "补充说明后继续" });
    expect(input).toHaveAttribute("maxlength", "2000");
    expect(
      screen.queryByRole("button", { name: "批准当前节点" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "缩小范围并重试" }),
    ).not.toBeInTheDocument();
    fireEvent.change(input, {
      target: { value: "保留计算，只核对最新统计和引用，再提交审核。" },
    });
    fireEvent.click(screen.getByRole("button", { name: "补充说明并继续" }));
    await waitFor(() => expect(businessFlowsApi.decide).toHaveBeenCalledOnce());
    expect(businessFlowsApi.decide).toHaveBeenCalledWith(
      flow.id,
      expect.objectContaining({
        nodeId: "analyse",
        decision: "retry_context",
        feedback: "保留计算，只核对最新统计和引用，再提交审核。",
        revision: flow.revision,
      }),
    );
  },
);

it.each(["geology_generic", "research_flow"] as const)(
  "only exposes the persisted failed-review retry for %s",
  async (adapter) => {
    const flow = waiting();
    flow.status = "failed";
    flow.definitionSnapshot.adapter = adapter;
    flow.nodes[0]!.contextRecovery!.kind = "model_protocol_error";
    render(
      <App>
        <MemoryRouter>
          <BusinessFlowActivity flow={flow} onChanged={vi.fn()} />
        </MemoryRouter>
      </App>,
    );
    const button = screen.queryByRole("button", { name: "重试本次审核" });
    if (adapter === "research_flow") {
      expect(button).not.toBeInTheDocument();
      return;
    }
    expect(button).toBeEnabled();
    fireEvent.click(button!);
    await waitFor(() => expect(businessFlowsApi.decide).toHaveBeenCalledOnce());
    expect(businessFlowsApi.decide).toHaveBeenCalledWith(
      flow.id,
      expect.objectContaining({ decision: "retry_context", nodeId: "analyse" }),
    );
  },
);

it.each(["task", "node"])(
  "shows operator usage and respects the %s quota boundary",
  (scope) => {
    const node = waiting().nodes[0]!;
    node.contextRecovery = {
      nodeId: node.nodeId,
      level: 0,
      evidence: [],
      kind: "operator_call_limit",
      budgetScope: scope,
      usedOperatorCalls: 16,
      limit: 16,
    };
    const retry = vi.fn();
    render(
      <App>
        <BusinessFlowContextRecovery
          node={node}
          busy={false}
          onRetry={retry}
          onStop={vi.fn()}
        />
      </App>,
    );
    expect(screen.getByText(/算子调用额度不足/)).toBeVisible();
    expect(screen.getByText("已用 16/16 次算子调用。")).toBeVisible();
    const button = screen.getByRole("button", { name: "额度更新后继续" });
    if (scope === "node") expect(button).toBeDisabled();
    else {
      fireEvent.click(button);
      expect(retry).toHaveBeenCalledExactlyOnceWith({ feedback: "" });
    }
    expect(
      screen.queryByRole("button", { name: "缩小范围并重试" }),
    ).not.toBeInTheDocument();
  },
);
