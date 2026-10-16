import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App, ConfigProvider } from "antd";
import { beforeEach, expect, it, vi } from "vitest";
import type { AgentInteraction, AgentRun } from "../api/generated/types.gen";
import { agentApi } from "../api/agent";
import InteractionCard from "./InteractionCard";
import "./agent.css";

function card(overrides: Partial<AgentInteraction> = {}): AgentInteraction {
  return {
    questionId: "spectral-bands",
    revision: 1,
    kind: "input",
    status: "pending",
    title: "确认影像波段",
    reason: "影像有8个波段，但没有光谱名称。",
    plan: "使用确认的红光和近红外波段计算植被指数。",
    createdAt: "2026-10-16",
    questions: [
      {
        key: "red",
        label: "红光波段",
        type: "single",
        required: true,
        defaultValue: "3",
        options: [
          { value: "3", label: "第3波段" },
          { value: "4", label: "第4波段" },
        ],
      },
      {
        key: "evidence",
        label: "辅助依据",
        type: "multiple",
        required: false,
        options: [
          { value: "rain", label: "降水资料" },
          { value: "field", label: "调查记录" },
        ],
      },
      { key: "scope", label: "分析范围", type: "text", required: false },
    ],
    ...overrides,
  };
}

function run(question = card()): AgentRun {
  return {
    id: 12,
    conversationId: 4,
    model: "qwen",
    status: "waiting_input",
    prompt: "分析植被变化",
    answer: "",
    detail: "等待您回答",
    evidence: [],
    attachments: [],
    contextTruncated: false,
    createdAt: "2026-10-16",
    updatedAt: "2026-10-16",
    interaction: question,
    interactionHistory: [],
  };
}

function show(value: AgentRun = run(), onChanged = vi.fn()) {
  const element = (next: AgentRun) => (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <InteractionCard run={next} onChanged={onChanged} />
      </App>
    </ConfigProvider>
  );
  return {
    onChanged,
    element,
    ...render(element(value)),
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(agentApi, "answerInteraction").mockResolvedValue({
    ...run(),
    status: "queued",
    interaction: null,
  });
  vi.spyOn(agentApi, "poll").mockResolvedValue({
    run: run(),
    events: [],
    cursor: 0,
  });
});

it("shows a default for review without sending it automatically", () => {
  show();
  expect(
    screen.getByRole("region", { name: "等待您回答的问题" }),
  ).toBeVisible();
  expect(screen.getByRole("radio", { name: "第3波段" })).toBeChecked();
  expect(screen.getByText("默认值需要您确认后才会发送。")).toBeVisible();
  expect(agentApi.answerInteraction).not.toHaveBeenCalled();
});

it("submits single, multiple, text and supplementary answers to the same task", async () => {
  const changed = show().onChanged;
  fireEvent.click(screen.getByRole("radio", { name: "第4波段" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "降水资料" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "调查记录" }));
  fireEvent.change(screen.getByLabelText("分析范围"), {
    target: { value: "绿洲边缘" },
  });
  fireEvent.change(screen.getByPlaceholderText(/可以补充条件/), {
    target: { value: "只评估有效观测区域" },
  });
  fireEvent.click(screen.getByRole("button", { name: "确认并继续" }));
  await waitFor(() =>
    expect(agentApi.answerInteraction).toHaveBeenCalledOnce(),
  );
  expect(agentApi.answerInteraction).toHaveBeenCalledWith(
    12,
    expect.objectContaining({
      action: "answer",
      questionId: "spectral-bands",
      revision: 1,
      answers: { red: "4", evidence: ["rain", "field"], scope: "绿洲边缘" },
      text: "只评估有效观测区域",
    }),
  );
  await waitFor(() =>
    expect(changed).toHaveBeenCalledWith(
      expect.objectContaining({ id: 12, status: "queued" }),
    ),
  );
});

it("prevents repeated clicks while the submission is in flight", async () => {
  let finish: ((value: AgentRun) => void) | undefined;
  vi.mocked(agentApi.answerInteraction).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  show();
  const button = screen.getByRole("button", { name: "确认并继续" });
  fireEvent.click(button);
  fireEvent.click(button);
  await waitFor(() =>
    expect(agentApi.answerInteraction).toHaveBeenCalledOnce(),
  );
  finish?.({ ...run(), status: "queued", interaction: null });
});

it("reuses the submission key after a lost response and polls the original task", async () => {
  vi.mocked(agentApi.answerInteraction).mockRejectedValueOnce(
    new Error("连接中断，回答尚未确认"),
  );
  show();
  fireEvent.click(screen.getByRole("button", { name: "确认并继续" }));
  await screen.findByText("连接中断，回答尚未确认");
  await waitFor(() => expect(agentApi.poll).toHaveBeenCalledWith(12));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "确认并继续" }),
    ).not.toBeDisabled(),
  );
  const first = vi.mocked(agentApi.answerInteraction).mock.calls[0]![1];
  fireEvent.click(screen.getByRole("button", { name: "确认并继续" }));
  await waitFor(() =>
    expect(agentApi.answerInteraction).toHaveBeenCalledTimes(2),
  );
  expect(
    vi.mocked(agentApi.answerInteraction).mock.calls[1]![1].submissionKey,
  ).toBe(first.submissionKey);
});

it("uses a new submission key when the answer is revised after a failed delivery", async () => {
  vi.mocked(agentApi.answerInteraction).mockRejectedValueOnce(
    new Error("回答未送达"),
  );
  show();
  fireEvent.click(screen.getByRole("button", { name: "确认并继续" }));
  await screen.findByText("回答未送达");
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "确认并继续" }),
    ).not.toBeDisabled(),
  );
  const first = vi.mocked(agentApi.answerInteraction).mock.calls[0]![1];
  fireEvent.click(screen.getByRole("radio", { name: "第4波段" }));
  fireEvent.click(screen.getByRole("button", { name: "确认并继续" }));
  await waitFor(() =>
    expect(agentApi.answerInteraction).toHaveBeenCalledTimes(2),
  );
  expect(
    vi.mocked(agentApi.answerInteraction).mock.calls[1]![1].submissionKey,
  ).not.toBe(first.submissionKey);
});

it("cancels the pending card and sends no answer", async () => {
  show();
  fireEvent.click(screen.getByRole("button", { name: "取消等待" }));
  await waitFor(() =>
    expect(agentApi.answerInteraction).toHaveBeenCalledWith(
      12,
      expect.objectContaining({ action: "cancel", answers: {}, text: "" }),
    ),
  );
});

it("restores saved answers as readable collapsed history without reopening the old form", async () => {
  const answered = card({
    status: "answered",
    answer: {
      submittedAt: "2026-10-16",
      submissionKey: "saved",
      answers: { red: "3", evidence: ["rain"] },
      text: "近红外为第8波段",
    },
  });
  show({
    ...run(),
    status: "queued",
    interaction: null,
    interactionHistory: [answered],
  });
  expect(
    screen.queryByRole("button", { name: "确认并继续" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /确认影像波段/ }));
  expect(await screen.findByText("第3波段")).toBeVisible();
  expect(screen.getByText("降水资料")).toBeVisible();
  expect(screen.getByText(/近红外为第8波段/)).toBeVisible();
  expect(agentApi.answerInteraction).not.toHaveBeenCalled();
});

it("requires an explicit review answer, with supplementary text unable to bypass approval", async () => {
  const review = card({
    kind: "review",
    questions: [
      {
        key: "approve",
        label: "是否继续",
        type: "single",
        required: true,
        options: [
          { value: "approve", label: "批准" },
          { value: "reject", label: "拒绝" },
        ],
      },
    ],
  });
  show({ ...run(review), status: "waiting_review" });
  fireEvent.change(screen.getByPlaceholderText(/可以补充条件/), {
    target: { value: "请核对范围" },
  });
  fireEvent.click(screen.getByRole("button", { name: "确认并继续" }));
  await screen.findByText(/请作答/);
  expect(agentApi.answerInteraction).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("radio", { name: "拒绝" }));
  fireEvent.click(screen.getByRole("button", { name: "确认并继续" }));
  await waitFor(() =>
    expect(agentApi.answerInteraction).toHaveBeenCalledWith(
      12,
      expect.objectContaining({ answers: { approve: "reject" } }),
    ),
  );
});

it("accepts a free-text clarification for a required information question", async () => {
  const question = card({
    questions: [
      {
        key: "red",
        label: "红光波段",
        type: "single",
        required: true,
        options: [{ value: "3", label: "第3波段" }],
      },
    ],
  });
  show(run(question));
  fireEvent.change(screen.getByPlaceholderText(/可以补充条件/), {
    target: { value: "用红光第3波段、近红外第8波段" },
  });
  fireEvent.click(screen.getByRole("button", { name: "确认并继续" }));
  await waitFor(() =>
    expect(agentApi.answerInteraction).toHaveBeenCalledWith(
      12,
      expect.objectContaining({
        answers: {},
        text: "用红光第3波段、近红外第8波段",
      }),
    ),
  );
});

it("resets unsent answers when a newer question revision replaces the old card", async () => {
  const view = show();
  fireEvent.click(screen.getByRole("radio", { name: "第4波段" }));
  const replacement = run(
    card({
      questionId: "new-evidence",
      revision: 2,
      title: "按新证据重新确认",
    }),
  );
  view.rerender(view.element(replacement));
  expect(screen.getByRole("radio", { name: "第3波段" })).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "确认并继续" }));
  await waitFor(() =>
    expect(agentApi.answerInteraction).toHaveBeenCalledWith(
      12,
      expect.objectContaining({
        questionId: "new-evidence",
        revision: 2,
        answers: { red: "3" },
      }),
    ),
  );
});
