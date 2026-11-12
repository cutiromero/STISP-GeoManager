import { expect, it, vi } from "vitest";
import { ApiError } from "./client";
import type { AgentEvent, AgentRun } from "./generated/types.gen";
import { applyAgentEvents, watchAgentRun } from "./watchAgentRun";
import { consumeServerEvents, STREAM_IDLE_MILLISECONDS } from "./eventStream";

const initial: AgentRun = {
  id: 1,
  conversationId: 2,
  model: "mock",
  status: "running",
  prompt: "问题",
  answer: "",
  detail: "",
  evidence: [],
  attachments: [],
  contextTruncated: false,
  createdAt: "",
  updatedAt: "",
};
const event = (
  id: number,
  kind: AgentEvent["kind"],
  text: string,
): AgentEvent => ({ id, kind, text, createdAt: "" });
const snapshot = (run = initial, cursor = 0) => ({ run, events: [], cursor });

it("recovers a network interruption while the caller remains active", async () => {
  const api = {
    stream: vi.fn().mockRejectedValue(new TypeError("connection interrupted")),
    poll: vi
      .fn()
      .mockResolvedValue(snapshot({ ...initial, status: "succeeded" })),
  };
  const update = vi.fn();
  await watchAgentRun(
    initial,
    api,
    new AbortController().signal,
    update,
    vi.fn(),
  );
  expect(api.poll).toHaveBeenCalledOnce();
  expect(update.mock.calls.at(-1)?.[0].run.status).toBe("succeeded");
});

it("releases a stalled SSE reader before recovering the completed snapshot", async () => {
  vi.useFakeTimers();
  try {
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({ cancel });
    const response = new Response(body, {
      headers: { "Content-Type": "text/event-stream" },
    });
    const api = {
      stream: vi.fn(
        (
          _id: number,
          callback: (kind: string, value: unknown) => void,
          signal?: AbortSignal,
        ) => consumeServerEvents(response, callback, signal),
      ),
      poll: vi
        .fn()
        .mockResolvedValue(snapshot({ ...initial, status: "succeeded" })),
    };
    const update = vi.fn();
    const pending = watchAgentRun(
      initial,
      api,
      new AbortController().signal,
      update,
      vi.fn(),
    );
    expect(api.poll).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(STREAM_IDLE_MILLISECONDS);
    await pending;
    expect(cancel).toHaveBeenCalledOnce();
    expect(api.poll).toHaveBeenCalledOnce();
    expect(update.mock.calls.at(-1)?.[0].run.status).toBe("succeeded");
  } finally {
    vi.useRealTimers();
  }
});

it("streams the initial body before completion without polling in parallel", async () => {
  let finish!: () => void;
  const gate = new Promise<void>((resolve) => {
    finish = resolve;
  });
  const updates: AgentRun[] = [];
  const api = {
    poll: vi.fn(),
    stream: vi.fn(
      async (_id: number, callback: (kind: string, value: unknown) => void) => {
        callback("snapshot", snapshot());
        callback("progress", {
          runId: 1,
          conversationId: 2,
          fromCursor: 0,
          cursor: 1,
          events: [event(1, "answer_preview", "第一段")],
        });
        await gate;
        callback("progress", {
          runId: 1,
          conversationId: 2,
          fromCursor: 1,
          cursor: 2,
          events: [event(2, "answer_delta", "第二段")],
        });
        callback(
          "snapshot",
          snapshot(
            {
              ...initial,
              status: "succeeded",
              answer: "第一段第二段",
              answerPreview: "",
            },
            3,
          ),
        );
      },
    ),
  };
  const pending = watchAgentRun(
    initial,
    api,
    new AbortController().signal,
    (value) => updates.push(value.run),
    vi.fn(),
  );
  await vi.waitFor(() => expect(updates.at(-1)?.answerPreview).toBe("第一段"));
  expect(api.poll).not.toHaveBeenCalled();
  finish();
  await pending;
  expect(updates.some((run) => run.answerPreview === "第一段第二段")).toBe(
    true,
  );
  expect(updates.at(-1)?.answer).toBe("第一段第二段");
  expect(api.stream).toHaveBeenCalledOnce();
});

it("slot saturation uses a read fallback and never resubmits work", async () => {
  const api = {
    stream: vi.fn().mockRejectedValue(new ApiError("busy", 503)),
    poll: vi
      .fn()
      .mockResolvedValue(
        snapshot({ ...initial, status: "succeeded", answer: "已完成" }),
      ),
  };
  const failure = vi.fn();
  const update = vi.fn();
  await watchAgentRun(
    initial,
    api,
    new AbortController().signal,
    update,
    failure,
  );
  expect(api.poll).toHaveBeenCalledOnce();
  expect(failure).not.toHaveBeenCalled();
  expect(update.mock.calls[0]?.[0].run.answer).toBe("已完成");
});

it("a cursor gap recovers through a complete snapshot without rendering missing text", async () => {
  const updates: AgentRun[] = [];
  const api = {
    stream: vi.fn(
      async (_id: number, callback: (kind: string, value: unknown) => void) => {
        callback("snapshot", snapshot());
        callback("progress", {
          runId: 1,
          conversationId: 2,
          fromCursor: 2,
          cursor: 3,
          events: [event(3, "answer_delta", "不应显示")],
        });
      },
    ),
    poll: vi
      .fn()
      .mockResolvedValue(
        snapshot(
          { ...initial, status: "succeeded", answer: "恢复后的完整答复" },
          3,
        ),
      ),
  };
  const failure = vi.fn();
  await watchAgentRun(
    initial,
    api,
    new AbortController().signal,
    (value) => updates.push(value.run),
    failure,
  );
  expect(failure).toHaveBeenCalledOnce();
  expect(updates.some((run) => run.answerPreview?.includes("不应显示"))).toBe(
    false,
  );
  expect(updates.at(-1)?.answer).toBe("恢复后的完整答复");
});

it("a project/auth abort stops instead of retrying the old run in a new scope", async () => {
  const api = {
    stream: vi
      .fn()
      .mockRejectedValue(new DOMException("project switched", "AbortError")),
    poll: vi.fn(),
  };
  await expect(
    watchAgentRun(initial, api, new AbortController().signal, vi.fn(), vi.fn()),
  ).rejects.toMatchObject({ name: "AbortError" });
  expect(api.poll).not.toHaveBeenCalled();
});

it("revocation does not fall back to another read route", async () => {
  const api = {
    stream: vi.fn().mockRejectedValue(new ApiError("权限失效", 403)),
    poll: vi.fn(),
  };
  await expect(
    watchAgentRun(initial, api, new AbortController().signal, vi.fn(), vi.fn()),
  ).rejects.toMatchObject({ status: 403 });
  expect(api.poll).not.toHaveBeenCalled();
});

it("supports long real text beyond the old preview limit and resets checkpoints", () => {
  let run = applyAgentEvents(initial, [
    event(1, "answer_preview", "遥".repeat(24000)),
    event(2, "answer_delta", "感".repeat(3000)),
    event(3, "tool_started", 'execute_operator：{"arguments":{"private":1}}'),
  ]);
  expect(run.answerPreview).toHaveLength(27000);
  expect(run.answerPreview).not.toContain("arguments");
  run = applyAgentEvents(run, [
    event(4, "answer_preview", ""),
    event(5, "answer_delta", "新答复"),
  ]);
  expect(run.answerPreview).toBe("新答复");
});
