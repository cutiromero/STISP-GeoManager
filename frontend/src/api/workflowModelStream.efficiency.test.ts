import { expect, it, vi } from "vitest";
import { applyAgentEvents, watchAgentRun } from "./watchAgentRun";
import { workflowModelActivity } from "./workflowModelStream";
import { businessFlowRun } from "../businessflows/businessFlow.testFixtures";
import type {
  AgentRun,
  AgentWorkflowModelActivity,
} from "./generated/types.gen";

const activity: AgentWorkflowModelActivity = {
  stage: "规划执行",
  status: "thinking",
  thinkingText: "",
  thinkingChars: 0,
  outputChars: 0,
  attempt: 1,
  reasoningEffort: "medium",
  thinkingEnabled: true,
  truncated: false,
};
const initial: AgentRun = {
  id: 41,
  conversationId: 31,
  model: "model",
  status: "waiting_compute",
  prompt: "分析",
  answer: "",
  detail: "",
  evidence: [],
  attachments: [],
  contextTruncated: false,
  createdAt: "",
  updatedAt: "",
  businessFlow: businessFlowRun({ status: "running" }),
};
const event = (id: number, text: string, sequence = 1, reset = false) => ({
  id,
  kind: "workflow_model_activity" as const,
  createdAt: "",
  text: JSON.stringify({
    workflowId: initial.businessFlow!.id,
    sequence,
    reset,
    thinkingDelta: text,
    activity: {
      ...activity,
      thinkingText: undefined,
      thinkingChars: text.length,
    },
  }),
});

it("renders partial thinking before the transport completes without polling or submitting work", async () => {
  let finish!: () => void;
  const gate = new Promise<void>((resolve) => {
    finish = resolve;
  });
  const received: AgentRun[] = [];
  const api = {
    poll: vi.fn(),
    stream: vi.fn(async (_id, callback) => {
      callback("snapshot", { run: initial, cursor: 0, events: [] });
      callback("progress", {
        runId: 41,
        conversationId: 31,
        fromCursor: 0,
        cursor: 1,
        events: [event(1, "第一段", 1, true)],
      });
      await gate;
      callback("progress", {
        runId: 41,
        conversationId: 31,
        fromCursor: 1,
        cursor: 2,
        events: [event(2, "第二段")],
      });
      callback("snapshot", {
        run: { ...received.at(-1)!, status: "waiting_review" },
        cursor: 2,
        events: [],
      });
    }),
  };
  const pending = watchAgentRun(
    initial,
    api,
    new AbortController().signal,
    (value) => received.push(value.run),
    vi.fn(),
  );
  await vi.waitFor(() =>
    expect(workflowModelActivity(received.at(-1)!)?.thinkingText).toBe(
      "第一段",
    ),
  );
  expect(api.poll).not.toHaveBeenCalled();
  finish();
  await pending;
  expect(workflowModelActivity(received.at(-1)!)?.thinkingText).toBe(
    "第一段第二段",
  );
  expect(api.stream).toHaveBeenCalledOnce();
});

it("isolates attempts, bounds real Unicode thinking and refuses another workflow's event", () => {
  let run = applyAgentEvents(initial, [event(1, "旧阶段", 1, true)]);
  run = applyAgentEvents(run, [event(2, "新阶段", 2, true)]);
  expect(workflowModelActivity(run)?.thinkingText).toBe("新阶段");
  run = applyAgentEvents(run, [event(3, "矿".repeat(12000), 2)]);
  expect(Array.from(workflowModelActivity(run)!.thinkingText)).toHaveLength(
    12000,
  );
  const wrong = event(4, "外部正文");
  const value = JSON.parse(wrong.text);
  value.workflowId = "other";
  wrong.text = JSON.stringify(value);
  expect(() => applyAgentEvents(run, [wrong])).toThrow(
    "工作流模型活动返回内容不完整",
  );
});
