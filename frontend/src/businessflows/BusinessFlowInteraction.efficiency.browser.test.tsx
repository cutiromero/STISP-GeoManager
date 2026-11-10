import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { useState, type ComponentProps } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { businessFlowsApi } from "../api/businessFlows";
import { computeApi } from "../api/compute";
import { liveComputeTask } from "../agent/computeFlow.testFixtures";
import { agentApi } from "../api/agent";
import { ApiError } from "../api/client";
import type { BusinessFlowRun } from "../api/generated/types.gen";
import platformStyles from "../styles.css?inline";
import { reviewWorkflow } from "../map/geologyReview.testFixtures";
import BusinessFlowActivity, {
  readableBusinessFlowEvents,
  businessFlowProgress,
} from "./BusinessFlowActivity";
import BusinessFlowLaunch from "./BusinessFlowLaunch";
import {
  businessFlowRun,
  directInputPlan,
  geologyDetail,
  geologySpec,
  researchDetail,
  researchVersion,
} from "./businessFlow.testFixtures";

vi.mock("../agent/useAgentBootstrap", () => ({
  useAgentBootstrapState: () => ({
    bootstrap: {
      canAgent: true,
      workerOnline: true,
      models: [
        {
          alias: "executor",
          name: "执行模型",
          allowAgent: true,
          status: "online",
        },
        {
          alias: "reviewer",
          name: "审核模型",
          allowAgent: true,
          status: "online",
        },
      ],
    },
    status: "ready",
  }),
}));
vi.mock("../agent/WorkflowCard", () => ({
  default: ({
    workflow,
    onConfirm,
    onReview,
  }: ComponentProps<typeof import("../agent/WorkflowCard").default>) => (
    <section aria-label="原专业审核卡">
      <p>专业方案 {workflow.planHash}</p>
      <output aria-label="专业卡实时模型思考">
        {workflow.modelActivity?.thinkingText}
      </output>
      <button onClick={onConfirm}>按专业方案确认</button>
      <button
        onClick={() => onReview?.("approve", "仅批准选中对象", ["candidate-1"])}
      >
        批准已选处置
      </button>
    </section>
  ),
}));
vi.mock("../agent/WorkflowReportFile", () => ({
  default: () => (
    <section aria-label="原科研报告文件">科研报告文件已打开</section>
  ),
}));
vi.mock("../agent/GenericWorkflowUploads", () => ({
  default: ({
    batchId,
    onInputsChange,
  }: ComponentProps<
    typeof import("../agent/GenericWorkflowUploads").default
  >) => (
    <section aria-label="原地质资料准备">
      <output aria-label="本次资料批次">{batchId}</output>
      <button onClick={() => onInputsChange({ lithology: 7 })}>
        选择已有地质图
      </button>
    </section>
  ),
}));
const intent = {
  definitionId: 2,
  versionId: 21,
  title: "项目资料摘要",
  goal: "梳理本次项目资料。",
};
function showActivity(
  initial: BusinessFlowRun = businessFlowRun(),
  listener = vi.fn(),
) {
  function Harness() {
    const [flow, setFlow] = useState(initial);
    return (
      <>
        <style>{platformStyles}</style>
        <App>
          <MemoryRouter>
            <BusinessFlowActivity
              flow={flow}
              onChanged={(next) => {
                setFlow(next);
                listener(next);
              }}
            />
          </MemoryRouter>
        </App>
      </>
    );
  }
  return { view: render(<Harness />), listener };
}
function showLaunch(launch = intent, callback = vi.fn()) {
  return {
    view: render(
      <>
        <style>{platformStyles}</style>
        <App>
          <MemoryRouter>
            <BusinessFlowLaunch
              launch={launch}
              model="executor"
              onStarted={callback}
              onCancel={vi.fn()}
            />
          </MemoryRouter>
        </App>
      </>,
    ),
    callback,
  };
}
beforeEach(() => {
  vi.spyOn(businessFlowsApi, "prepareInputs").mockImplementation(
    async (_id, request) => directInputPlan(request),
  );
  vi.spyOn(businessFlowsApi, "run").mockResolvedValue(businessFlowRun());
  vi.spyOn(businessFlowsApi, "detail").mockResolvedValue(researchDetail);
  vi.spyOn(agentApi, "resources").mockResolvedValue({
    items: [
      {
        id: 7,
        name: "授权样地数据",
        dataType: "table",
        description: "当前项目资料",
      },
    ],
  });
  vi.spyOn(agentApi, "workflow").mockResolvedValue({
    ...reviewWorkflow(true),
    id: businessFlowRun().id,
    workflowType: "geology_generic",
    status: "waiting_approval",
    planHash: "approved-plan",
    plan: { phase: "confirm_plan" },
  });
});
afterEach(() => vi.restoreAllMocks());

it("keeps AI acceptance separate from a real human approval and never polls while parked", async () => {
  const decide = vi
    .spyOn(businessFlowsApi, "decide")
    .mockResolvedValue(businessFlowRun({ status: "queued", revision: 5 }));
  const { listener } = showActivity();
  expect(screen.getByRole("button", { name: "批准当前节点" })).toBeEnabled();
  expect(
    within(screen.getByRole("region", { name: "审核智能体" })).getByText(
      "审核通过",
    ),
  ).toBeVisible();
  expect(screen.getByText("此处需要用户明确批准。")).toBeVisible();
  expect(decide).not.toHaveBeenCalled();
  expect(businessFlowsApi.run).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "批准当前节点" }));
  await waitFor(() => expect(listener).toHaveBeenCalledOnce());
  expect(decide).toHaveBeenCalledExactlyOnceWith(
    businessFlowRun().id,
    expect.objectContaining({
      nodeId: "analyse",
      revision: 4,
      decision: "approve",
      feedback: "",
      idempotencyKey: expect.any(String),
    }),
  );
});
it("sends a precise revision request and reuses its idempotency key on a transport retry", async () => {
  const decide = vi
    .spyOn(businessFlowsApi, "decide")
    .mockRejectedValueOnce(new Error("连接中断"))
    .mockResolvedValueOnce(businessFlowRun({ status: "queued", revision: 5 }));
  showActivity();
  fireEvent.click(screen.getByRole("button", { name: "要求返修" }));
  expect(
    await screen.findByText(
      "请说明需要返修的原因，执行智能体才能有针对性地修改。",
    ),
  ).toBeVisible();
  expect(decide).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole("textbox", { name: "审核反馈" }), {
    target: { value: "请补充这个结论的真实资料依据。" },
  });
  fireEvent.click(screen.getByRole("button", { name: "要求返修" }));
  expect(await screen.findByText("连接中断")).toBeVisible();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "要求返修" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "要求返修" }));
  await waitFor(() => expect(decide).toHaveBeenCalledTimes(2));
  expect(decide.mock.calls[1]?.[1]).toEqual(decide.mock.calls[0]?.[1]);
  expect(decide.mock.calls[1]?.[1].feedback).toContain("真实资料依据");
});
it("hides old processing content immediately after a control-only cancellation", async () => {
  const stopped = businessFlowRun({ status: "cancelled", revision: 5 });
  stopped.nodes = stopped.nodes.map((node) => ({
    ...node,
    executor: { status: "unavailable" },
    reviewer: { status: "unavailable" },
    outputs: {},
  }));
  stopped.events = [];
  const cancel = vi
    .spyOn(businessFlowsApi, "cancel")
    .mockResolvedValue(stopped);
  showActivity();
  expect(screen.getByText("执行结果已核对真实资料。")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "停止业务流" }));
  await waitFor(() => expect(cancel).toHaveBeenCalledOnce());
  await waitFor(() =>
    expect(
      screen.queryByText("执行结果已核对真实资料。"),
    ).not.toBeInTheDocument(),
  );
  expect(screen.queryByText("引用与结果相符。")).not.toBeInTheDocument();
  expect(
    screen.getByText("任务已停止。此前的处理正文不再在此处展示。"),
  ).toBeVisible();
  expect(businessFlowsApi.run).not.toHaveBeenCalled();
});
it("hides protected actor content after an explicit permission rejection", async () => {
  vi.spyOn(businessFlowsApi, "decide").mockRejectedValueOnce(
    new ApiError("资料已撤权", 403),
  );
  showActivity();
  fireEvent.click(screen.getByRole("button", { name: "批准当前节点" }));
  expect(await screen.findByText("资料已撤权")).toBeVisible();
  expect(
    screen.queryByText("执行结果已核对真实资料。"),
  ).not.toBeInTheDocument();
  expect(screen.getByText("访问权限已变化，处理内容已隐藏。")).toBeVisible();
});
it("opens professional review lazily and never substitutes a generic approval", async () => {
  const flow = businessFlowRun({
    flowId: 1,
    versionId: 11,
    definitionSnapshot: geologySpec,
    currentNode: "apply",
  });
  flow.nodes = geologySpec.nodes.map((node) => ({
    nodeId: node.id,
    status: node.id === "apply" ? "waiting_human" : "succeeded",
    attempt: 1,
    executor: { status: "succeeded" },
    reviewer: { status: node.review.ai ? "passed" : "not_required" },
    human: {
      required: node.review.human,
      status:
        node.id === "apply"
          ? "pending"
          : node.review.human
            ? "approved"
            : "not_required",
      reason: "核对专业处置范围。",
    },
    outputs: {},
  }));
  const decide = vi.spyOn(businessFlowsApi, "decide");
  const confirm = vi.spyOn(agentApi, "confirmWorkflow").mockResolvedValue({
    ...reviewWorkflow(true),
    id: flow.id,
    workflowType: "geology_generic",
    planHash: "next-plan",
  });
  showActivity(flow);
  expect(agentApi.workflow).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: "批准当前节点" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "打开专业审核" }));
  expect(
    await screen.findByRole("region", { name: "原专业审核卡" }),
  ).toBeVisible();
  expect(agentApi.workflow).toHaveBeenCalledExactlyOnceWith(flow.id, {
    view: "card",
    signal: expect.any(AbortSignal),
  });
  fireEvent.click(screen.getByRole("button", { name: "批准已选处置" }));
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  expect(confirm).toHaveBeenCalledWith(
    flow.id,
    "approved-plan",
    expect.objectContaining({
      decision: "approve",
      selectedSuggestionIds: ["candidate-1"],
    }),
  );
  expect(decide).not.toHaveBeenCalled();
});
it("does not prepare reports or read flow details until the user asks", async () => {
  showActivity(businessFlowRun({ status: "succeeded", currentNode: "finish" }));
  expect(screen.queryByText("科研报告文件已打开")).not.toBeInTheDocument();
  expect(businessFlowsApi.run).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "报告与成果" }));
  expect(await screen.findByText("科研报告文件已打开")).toBeVisible();
  const events = businessFlowRun().events;
  expect(
    readableBusinessFlowEvents([
      ...events,
      { ...events[1]!, id: 3, message: "审核通过，仍需用户批准。" },
    ]),
  ).toHaveLength(2);
});
it("loads generic input choices only when needed and starts the exact selected version once", async () => {
  const detail = {
    ...researchDetail,
    version: {
      ...researchVersion,
      definition: {
        ...researchVersion.definition,
        inputRequirements: [
          {
            key: "source",
            label: "待分析资料",
            description: "选择授权资料。",
            dataTypes: ["table" as const],
            required: true,
            requiredFields: [],
          },
        ],
      },
    },
  };
  detail.versions = [detail.version];
  vi.mocked(businessFlowsApi.detail).mockResolvedValue(detail);
  const start = vi
    .spyOn(businessFlowsApi, "start")
    .mockResolvedValue(businessFlowRun({ status: "queued" }));
  const { callback } = showLaunch();
  await screen.findByRole("textbox", { name: "本次任务目标" });
  expect(agentApi.resources).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "开始业务流" })).toBeDisabled();
  fireEvent.mouseDown(
    screen.getByRole("combobox", { name: "待分析资料：选择资料" }),
  );
  await waitFor(() =>
    expect(
      screen.getByText("授权样地数据", {
        selector: '.ant-select-item-option-content [role="group"]',
      }),
    ).toBeVisible(),
  );
  fireEvent.click(
    screen.getByText("授权样地数据", {
      selector: '.ant-select-item-option-content [role="group"]',
    }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "开始业务流" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "开始业务流" }));
  fireEvent.click(screen.getByRole("button", { name: "开始业务流" }));
  await waitFor(() => expect(callback).toHaveBeenCalledOnce());
  expect(start).toHaveBeenCalledExactlyOnceWith(
    2,
    expect.objectContaining({
      versionId: 21,
      model: "executor",
      reviewerModel: "executor",
      inputs: { source: 7 },
      goal: intent.goal,
      idempotencyKey: expect.any(String),
    }),
  );
  expect(start.mock.calls[0]?.[1]).not.toHaveProperty("conversationId");
  expect(agentApi.resources).toHaveBeenCalledOnce();
});
it("binds professional launch uploads to one batch and does not load ordinary candidates", async () => {
  const detail = {
    ...geologyDetail,
    version: {
      ...geologyDetail.version!,
      definition: {
        ...geologySpec,
        inputRequirements: geologySpec.inputRequirements.map((input) => ({
          ...input,
          required: input.key === "lithology",
        })),
      },
    },
  };
  detail.versions = [detail.version];
  vi.mocked(businessFlowsApi.detail).mockResolvedValue(detail);
  const start = vi
    .spyOn(businessFlowsApi, "start")
    .mockResolvedValue(businessFlowRun({ status: "queued" }));
  showLaunch({
    ...intent,
    definitionId: 1,
    versionId: 11,
    title: "地质逻辑推理",
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "选择已有地质图" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "开始业务流" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "开始业务流" }));
  await waitFor(() => expect(start).toHaveBeenCalledOnce());
  expect(start.mock.calls[0]?.[1].parameters.uploadBatchId).toMatch(
    /^[a-f0-9]{32}$/,
  );
  expect(start.mock.calls[0]?.[1].inputs).toEqual({ lithology: 7 });
  expect(agentApi.resources).not.toHaveBeenCalled();
});
it("keeps start retries idempotent", async () => {
  const start = vi
    .spyOn(businessFlowsApi, "start")
    .mockRejectedValueOnce(new Error("启动回执暂未收到"))
    .mockResolvedValueOnce(businessFlowRun({ status: "queued" }));
  showLaunch();
  await screen.findByRole("textbox", { name: "本次任务目标" });
  fireEvent.click(screen.getByRole("button", { name: "开始业务流" }));
  expect(await screen.findByText("启动回执暂未收到")).toBeVisible();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "开始业务流" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "开始业务流" }));
  await waitFor(() => expect(start).toHaveBeenCalledTimes(2));
  expect(start.mock.calls[1]?.[1]).toEqual(start.mock.calls[0]?.[1]);
});
it.each([
  [1366, 768],
  [390, 844],
])(
  "keeps actor status and human controls readable at %sx%s",
  async (width, height) => {
    await page.viewport(width, height);
    try {
      showActivity();
      const panel = screen.getByRole("region", { name: "业务流工作状态" });
      expect(panel.scrollWidth).toBeLessThanOrEqual(width);
      expect(
        screen.getByRole("button", { name: "批准当前节点" }),
      ).toBeVisible();
      await page.screenshot({
        path: `../../test-results/business-flow-activity-${width}.png`,
      });
    } finally {
      await page.viewport(1600, 900);
    }
  },
);

it("opens real node results once and does not refetch them for unrelated stream revisions", async () => {
  const task = { ...liveComputeTask("succeeded"), projectTagId: 3 };
  const lookup = vi.spyOn(computeApi, "task").mockResolvedValue(task);
  const importResult = vi.spyOn(computeApi, "importOutput");
  vi.spyOn(window, "open").mockReturnValue(null);
  const flow = businessFlowRun();
  flow.nodes[0]!.outputs = { taskId: task.id };
  const listener = vi.fn();
  const view = render(
    <>
      <style>{platformStyles}</style>
      <App>
        <MemoryRouter>
          <BusinessFlowActivity flow={flow} onChanged={listener} />
        </MemoryRouter>
      </App>
    </>,
  );
  expect(lookup).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "分析项目资料：查看节点计算结果" }),
  );
  expect(
    await screen.findByText("259 × 260 / 1 波段 / EPSG:3857"),
  ).toBeVisible();
  expect(lookup).toHaveBeenCalledExactlyOnceWith(task.id);
  expect(importResult).not.toHaveBeenCalled();
  const next = {
    ...flow,
    revision: 20,
    updatedAt: "2026-11-10T00:02:00Z",
    events: [
      ...flow.events,
      {
        id: 3,
        nodeId: "analyse",
        actor: "reviewer" as const,
        kind: "review_progress",
        status: "waiting_approval",
        message: "补充了审核说明。",
        createdAt: "2026-11-10T00:02:00Z",
      },
    ],
  };
  await act(async () =>
    view.rerender(
      <>
        <style>{platformStyles}</style>
        <App>
          <MemoryRouter>
            <BusinessFlowActivity flow={next} onChanged={listener} />
          </MemoryRouter>
        </App>
      </>,
    ),
  );
  expect(lookup).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "在地理工作台查看" }));
  expect(window.open).toHaveBeenCalledWith(
    "/map?computeOutputId=30&projectTagId=3",
    "_blank",
    "noopener",
  );
});

it("does not silently substitute the latest version for an unavailable frozen version", async () => {
  const start = vi.spyOn(businessFlowsApi, "start");
  showLaunch({ ...intent, versionId: 999 });
  expect(
    await screen.findByText("该发布版本已无法读取，请返回业务流目录重新选择。"),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "开始业务流" }),
  ).not.toBeInTheDocument();
  expect(start).not.toHaveBeenCalled();
});

it("sends a separately selected reviewer model without changing the executor", async () => {
  const version = {
    ...researchVersion,
    definition: {
      ...researchVersion.definition,
      nodes: researchVersion.definition.nodes.map((node) => ({
        ...node,
        review: { ai: true, human: false, maxRevisions: 1 },
      })),
    },
  };
  vi.mocked(businessFlowsApi.detail).mockResolvedValue({
    ...researchDetail,
    version,
    versions: [version],
  });
  const start = vi
    .spyOn(businessFlowsApi, "start")
    .mockResolvedValue(businessFlowRun({ status: "queued" }));
  showLaunch();
  const reviewer = await screen.findByRole("combobox", { name: "审核模型" });
  fireEvent.mouseDown(reviewer);
  const option = await screen.findByText("审核模型", {
    selector: ".ant-select-item-option-content",
  });
  fireEvent.click(option);
  fireEvent.click(screen.getByRole("button", { name: "开始业务流" }));
  await waitFor(() => expect(start).toHaveBeenCalledOnce());
  expect(start.mock.calls[0]?.[1]).toMatchObject({
    model: "executor",
    reviewerModel: "reviewer",
  });
});

it("counts completed execution and independent review before the required human decision", () => {
  const waiting = businessFlowRun();
  waiting.nodes[0]!.executor.audit = { modelName: "科研执行模型" };
  waiting.nodes[0]!.reviewer.audit = { modelName: "独立审核模型" };
  const progress = businessFlowProgress(waiting);
  expect(progress.completedNodes).toBe(0);
  expect(progress.percent).toBeGreaterThan(0);
  expect(progress.percent).toBeLessThan(100);
  showActivity(waiting);
  expect(screen.getByText("已完成执行与独立审核")).toBeVisible();
  expect(screen.getByText("科研执行模型")).toBeVisible();
  expect(screen.getByText("独立审核模型")).toBeVisible();
  expect(
    screen.getByRole("progressbar", { name: "业务流阶段进度" }),
  ).toHaveAttribute("aria-valuenow", String(progress.percent));
  const initial = businessFlowRun({ status: "queued" });
  initial.nodes = initial.nodes.map((node) => ({
    ...node,
    status: "pending",
    attempt: 0,
    executor: { status: "pending" },
    reviewer: {
      status: node.nodeId === "analyse" ? "pending" : "not_required",
    },
    human: {
      ...node.human,
      status: node.human.required ? "pending" : "not_required",
    },
  }));
  expect(businessFlowProgress(initial).percent).toBe(0);
  const finished = businessFlowRun({ status: "running" });
  finished.nodes = finished.nodes.map((node) => ({
    ...node,
    status: "succeeded",
  }));
  expect(businessFlowProgress(finished).percent).toBe(99);
  expect(
    businessFlowProgress({ ...finished, status: "succeeded" }).percent,
  ).toBe(100);
});

it("keeps an open professional thinking view live from parent stream props without detail rereads", async () => {
  const flow = businessFlowRun({
    definitionSnapshot: geologySpec,
    currentNode: "apply",
    status: "running",
  });
  const response = {
    ...reviewWorkflow(true),
    id: flow.id,
    workflowType: "geology_generic" as const,
  };
  vi.mocked(agentApi.workflow).mockResolvedValue(response);
  const props = { flow, onChanged: vi.fn() };
  const activity = {
    stage: "分析",
    status: "thinking" as const,
    thinkingText: "先到的一段",
    thinkingChars: 5,
    outputChars: 0,
    attempt: 1,
    reasoningEffort: "medium" as const,
    thinkingEnabled: true,
    truncated: false,
  };
  const view = render(
    <App>
      <MemoryRouter>
        <BusinessFlowActivity {...props} modelActivity={activity} />
      </MemoryRouter>
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: "打开专业审核" }));
  expect(await screen.findByLabelText("专业卡实时模型思考")).toHaveTextContent(
    "先到的一段",
  );
  view.rerender(
    <App>
      <MemoryRouter>
        <BusinessFlowActivity
          {...props}
          modelActivity={{
            ...activity,
            thinkingText: "先到的一段，接着到达",
            thinkingChars: 10,
          }}
        />
      </MemoryRouter>
    </App>,
  );
  expect(screen.getByLabelText("专业卡实时模型思考")).toHaveTextContent(
    "先到的一段，接着到达",
  );
  expect(agentApi.workflow).toHaveBeenCalledOnce();
});
