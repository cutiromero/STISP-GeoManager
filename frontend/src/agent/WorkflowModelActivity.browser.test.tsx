import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { agentApi } from "../api/agent";
import type {
  AgentResearchIntent,
  AgentRun,
  AgentWorkflow,
  AgentWorkflowModelActivity,
} from "../api/generated/types.gen";
import { assertAgentRun } from "../api/agentResponse";
import { assertWorkflow } from "../api/workflowResponse";
import { ResponseFormatError } from "../api/responseDiagnostics";
import { reviewWorkflow } from "../map/geologyReview.testFixtures";
import { workflowActivity } from "./agentActivity";
import WorkflowCard from "./WorkflowCard";
import WorkflowModelActivity from "./WorkflowModelActivity";
import ResearchIntentCard from "./ResearchIntentCard";

const modelActivity: AgentWorkflowModelActivity = {
  stage: "检查地质资料",
  status: "thinking",
  thinkingText: "真实思考第一段",
  truncated: false,
  reasoningEffort: "xhigh",
  thinkingEnabled: true,
  attempt: 1,
  outputChars: 0,
  thinkingChars: 7,
  modelName: "test-model",
};
function workflow(overrides: Partial<AgentWorkflow> = {}): AgentWorkflow {
  return {
    ...reviewWorkflow(true),
    view: "card",
    status: "running",
    steps: [],
    evidence: [],
    modificationReview: undefined,
    plan: { phase: "decide" },
    modelActivity: { ...modelActivity },
    ...overrides,
  };
}
beforeEach(() => vi.restoreAllMocks());
afterEach(() => vi.useRealTimers());

it("real model activity updates from lightweight card without fetching detail when reasoning expands", async () => {
  const read = vi.spyOn(agentApi, "workflow");
  const first = workflow();
  const mounted = render(
    <MemoryRouter>
      <WorkflowCard workflow={first} />
    </MemoryRouter>,
  );
  const activity = screen.getByRole("region", { name: "工作流模型活动" });
  expect(activity).toHaveTextContent("模型正在思考");
  expect(activity).toHaveTextContent("检查地质资料");
  expect(activity).toHaveTextContent("已接收响应正文 0 字符");
  fireEvent.click(within(activity).getByText(/查看模型实际思考/));
  expect(
    await within(activity).findByLabelText("模型思考内容"),
  ).toHaveTextContent("真实思考第一段");
  expect(read).not.toHaveBeenCalled();
  mounted.rerender(
    <MemoryRouter>
      <WorkflowCard
        workflow={workflow({
          updatedAt: "new-poll",
          modelActivity: {
            ...modelActivity,
            status: "responding",
            outputChars: 548,
            thinkingText: "真实思考第一段\n真实第二段",
            thinkingChars: 13,
          },
        })}
      />
    </MemoryRouter>,
  );
  expect(activity).toHaveTextContent("已接收响应正文 548 字符");
  expect(within(activity).getByLabelText("模型思考内容")).toHaveTextContent(
    "真实第二段",
  );
  expect(activity.querySelector(".is-streaming")).toBeNull();
  expect(read).not.toHaveBeenCalled();
});

it.each([
  "paused",
  "cancelled",
  "interrupted",
  "failed",
  "succeeded",
  "waiting_approval",
] as const)(
  "real model activity stops reasoning animation in workflow %s",
  async (status) => {
    const mounted = render(<WorkflowModelActivity workflow={workflow()} />);
    fireEvent.click(screen.getByText(/查看模型实际思考/));
    expect(await screen.findByLabelText("模型思考内容")).toHaveClass(
      "is-streaming",
    );
    mounted.rerender(
      <WorkflowModelActivity
        workflow={workflow({ status, pauseRequested: true })}
      />,
    );
    expect(screen.getByLabelText("模型思考内容")).toHaveTextContent(
      "真实思考第一段",
    );
    expect(screen.getByLabelText("模型思考内容")).not.toHaveClass(
      "is-streaming",
    );
    expect(screen.getByRole("status")).not.toHaveAttribute(
      "data-activity-state",
      "working",
    );
    expect(
      workflowActivity(workflow({ status, pauseRequested: true })).state,
    ).not.toBe("working");
  },
);

it("real model activity keeps computation independent from a previous completed model request", () => {
  const computing = workflow({
    status: "waiting_compute",
    modelActivity: { ...modelActivity, status: "complete" },
  });
  render(<WorkflowModelActivity workflow={computing} />);
  expect(screen.getByRole("region")).toHaveTextContent("当前正在进行算子计算");
  expect(screen.getByRole("status")).not.toHaveAttribute(
    "data-activity-state",
    "working",
  );
  expect(workflowActivity(computing)).toMatchObject({
    state: "working",
    label: "算法正在计算",
  });
});

it("real model activity reports missing reasoning and truncation without inventing text", async () => {
  const mounted = render(
    <WorkflowModelActivity
      workflow={workflow({
        modelActivity: {
          ...modelActivity,
          thinkingText: "",
          thinkingChars: 0,
          status: "responding",
          outputChars: 100,
        },
      })}
    />,
  );
  fireEvent.click(screen.getByText(/查看模型实际思考/));
  await screen.findByText("尚未收到可展示的模型思考内容。");
  expect(screen.queryByLabelText("模型思考内容")).not.toBeInTheDocument();
  mounted.rerender(
    <WorkflowModelActivity
      workflow={workflow({
        modelActivity: {
          ...modelActivity,
          thinkingText: "保留的真实思考尾部",
          thinkingChars: 15000,
          truncated: true,
        },
      })}
    />,
  );
  expect(await screen.findByLabelText("模型思考内容")).toHaveTextContent(
    "保留的真实思考尾部",
  );
  expect(
    screen.getByText("仅显示最近 12000 个思考字符，较早部分已省略。"),
  ).toBeInTheDocument();
  mounted.rerender(
    <WorkflowModelActivity
      workflow={workflow({
        id: "another-workflow",
        modelActivity: { ...modelActivity, thinkingText: "新任务实际思考" },
      })}
    />,
  );
  expect(screen.queryByText("保留的真实思考尾部")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText(/查看模型实际思考/));
  expect(await screen.findByLabelText("模型思考内容")).toHaveTextContent(
    "新任务实际思考",
  );
});

it("real model activity refreshes on existing research card polling and stops at terminal", async () => {
  vi.useFakeTimers();
  const initial = workflow();
  const next = workflow({
    modelActivity: { ...modelActivity, status: "responding", outputChars: 777 },
  });
  const done = workflow({
    status: "succeeded",
    modelActivity: { ...modelActivity, status: "complete", outputChars: 900 },
  });
  const read = vi
    .spyOn(agentApi, "workflow")
    .mockResolvedValueOnce(initial)
    .mockResolvedValueOnce(next)
    .mockResolvedValue(done);
  const poll = vi.spyOn(agentApi, "poll");
  const intent: AgentResearchIntent = {
    originRunId: 12,
    revision: "r1",
    scenario: "geology_generic",
    status: "running",
    goal: "核对资料",
    message: "处理中",
    questions: [],
    inputs: {},
    parameters: {},
    inputSummary: [],
    workflowId: initial.id,
  };
  const run: AgentRun & { researchIntent: AgentResearchIntent } = {
    id: 12,
    conversationId: 4,
    model: "test-model",
    status: "succeeded",
    prompt: "核对资料",
    answer: "",
    detail: "",
    evidence: [],
    attachments: [],
    createdAt: "",
    updatedAt: "",
    researchIntent: intent,
  };
  poll.mockResolvedValue({
    run: { ...run, researchIntent: { ...intent, status: "succeeded" } },
    events: [],
    cursor: 0,
  });
  render(
    <MemoryRouter>
      <ResearchIntentCard run={run} onChanged={vi.fn()} />
    </MemoryRouter>,
  );
  await act(() => vi.advanceTimersByTimeAsync(0));
  expect(
    screen.getByRole("region", { name: "工作流模型活动" }),
  ).toHaveTextContent("已接收响应正文 0 字符");
  await act(() => vi.advanceTimersByTimeAsync(1800));
  expect(
    screen.getByRole("region", { name: "工作流模型活动" }),
  ).toHaveTextContent("777 字符");
  await act(() => vi.advanceTimersByTimeAsync(1800));
  expect(
    screen.getByRole("region", { name: "工作流模型活动" }),
  ).toHaveTextContent("900 字符");
  const readCount = read.mock.calls.length;
  await act(() => vi.advanceTimersByTimeAsync(10000));
  expect(read).toHaveBeenCalledTimes(readCount);
  expect(read.mock.calls.every(([, options]) => options?.view === "card")).toBe(
    true,
  );
  expect(poll).toHaveBeenCalledTimes(1);
});

it("real model activity preserves pending approval controls while a preview is present", async () => {
  const detail = workflow({
    status: "waiting_approval",
    plan: { phase: "review_plan" },
    modelActivity: { ...modelActivity, status: "complete" },
  });
  const confirm = vi.fn();
  render(
    <MemoryRouter>
      <WorkflowCard
        workflow={{
          ...detail,
          view: "card",
          steps: [],
          modificationReview: undefined,
        }}
        onConfirm={confirm}
      />
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(
      screen.getByRole("region", { name: "工作流模型活动" }),
    ).toBeInTheDocument(),
  );
  expect(
    screen.getByRole("region", { name: "工作流进度卡片" }),
  ).toBeInTheDocument();
  expect(
    screen
      .getByRole("region", { name: "工作流模型活动" })
      .querySelector(".is-streaming"),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "确认执行" }));
  expect(confirm).toHaveBeenCalledOnce();
});

it("real model activity response guards accept Unicode limits and reject malformed optional snapshots", () => {
  const run = {
    id: 1,
    conversationId: 1,
    model: "m",
    prompt: "",
    answer: "",
    detail: "",
    status: "running",
    evidence: [],
    attachments: [],
    createdAt: "",
    updatedAt: "",
  };
  expect(() =>
    assertAgentRun({ ...run, answerPreview: "🌍".repeat(24000) }),
  ).not.toThrow();
  expect(() =>
    assertAgentRun({ ...run, answerPreview: "🌍".repeat(24001) }),
  ).toThrow(ResponseFormatError);
  expect(() => assertAgentRun({ ...run, answerPreview: {} })).toThrow(
    ResponseFormatError,
  );
  expect(() => assertWorkflow(workflow())).not.toThrow();
  expect(() =>
    assertWorkflow(
      workflow({
        modelActivity: { ...modelActivity, thinkingText: "🌍".repeat(12000) },
      }),
    ),
  ).not.toThrow();
  for (const value of [
    null,
    { ...modelActivity, outputChars: -1 },
    { ...modelActivity, status: "cancelled" },
    { ...modelActivity, attempt: 0 },
  ])
    expect(() =>
      assertWorkflow({ ...workflow(), modelActivity: value }),
    ).toThrow(ResponseFormatError);
});
