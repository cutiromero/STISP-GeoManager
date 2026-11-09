import { act, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { agentApi } from "../api/agent";
import { consumeServerEvents } from "../api/eventStream";
import type { AgentBootstrap, AgentRun } from "../api/generated/types.gen";
import AgentPage from "./AgentPage";

vi.mock("../components/WorkspaceHeader", () => ({
  default: () => <header>STISP</header>,
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: { id: 99, permissions: {} } }),
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => ({
    current: "1",
    projects: [{ id: 1, name: "公开", code: "default" }],
  }),
}));
vi.mock("./useAgentBootstrap", () => ({
  useAgentBootstrapState: () => ({
    bootstrap,
    status: "ready",
    error: "",
    retry: vi.fn(),
  }),
}));
const bootstrap: AgentBootstrap = {
  canAgent: true,
  canChat: true,
  canManage: false,
  runStreamingEnabled: true,
  thinkingEnabled: true,
  internetEnabled: false,
  allowAttachments: false,
  workerOnline: true,
  defaultAgentModel: "mock",
  defaultChatModel: "mock",
  capabilities: [],
  models: [
    {
      alias: "mock",
      name: "Mock",
      status: "online",
      supportsThinking: true,
      supportsVision: false,
      allowAgent: true,
      contextWindowTokens: 32768,
      checkedAt: "",
    },
  ],
};
const run: AgentRun = {
  id: 5,
  conversationId: 1,
  model: "mock",
  status: "running",
  prompt: "请根据资料说明",
  answer: "",
  answerPreview: "",
  thinkingMode: "deep",
  detail: "",
  evidence: [],
  attachments: [],
  contextTruncated: false,
  createdAt: "",
  updatedAt: "",
};
const conversation = {
  id: 1,
  projectId: 1,
  mode: "agent" as const,
  title: "研究资料",
  archived: false,
  createdAt: "",
  updatedAt: "",
};
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
  vi.spyOn(agentApi, "conversations").mockResolvedValue({
    items: [conversation],
  });
  vi.spyOn(agentApi, "detail").mockResolvedValue({ conversation, runs: [run] });
  vi.spyOn(agentApi, "resources").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "workflows").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "researchDemoSummaries").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "computeTasks").mockResolvedValue({ items: [] });
});

function show() {
  return render(
    <App>
      <MemoryRouter initialEntries={["/agent/workbench"]}>
        <AgentPage />
      </MemoryRouter>
    </App>,
  );
}

it("renders real stream chunks and safe Markdown before completion without concurrent polling", async () => {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(value) {
      controller = value;
    },
  });
  const response = new Response(body, {
    headers: { "Content-Type": "text/event-stream" },
  });
  const stream = vi
    .spyOn(agentApi, "stream")
    .mockImplementation((_id, onEvent, signal) =>
      consumeServerEvents(response, onEvent, signal),
    );
  const poll = vi.spyOn(agentApi, "poll");
  const send = (kind: string, data: unknown) =>
    controller.enqueue(
      new TextEncoder().encode(
        `event: ${kind}\ndata: ${JSON.stringify(data)}\n\n`,
      ),
    );
  show();
  await waitFor(() => expect(stream).toHaveBeenCalledOnce());
  await act(async () => send("snapshot", { run, cursor: 0, events: [] }));
  await act(async () =>
    send("progress", {
      runId: 5,
      conversationId: 1,
      fromCursor: 0,
      cursor: 1,
      events: [
        { id: 1, kind: "thinking", text: "先核对实际资料", createdAt: "" },
      ],
    }),
  );
  await screen.findByText("先核对实际资料");
  await act(async () =>
    send("progress", {
      runId: 5,
      conversationId: 1,
      fromCursor: 1,
      cursor: 2,
      events: [
        {
          id: 2,
          kind: "answer_preview",
          text: "**真实第一段** <img src=x>",
          createdAt: "",
        },
      ],
    }),
  );
  const preview = await screen.findByRole("region", { name: "答复增量预览" });
  expect(preview.querySelector("strong")).toHaveTextContent("真实第一段");
  expect(preview.querySelector("img")).toBeNull();
  expect(screen.getByRole("button", { name: "停止回答" })).toBeVisible();
  expect(poll).not.toHaveBeenCalled();
  await act(async () =>
    send("progress", {
      runId: 5,
      conversationId: 1,
      fromCursor: 2,
      cursor: 3,
      events: [
        {
          id: 3,
          kind: "answer_delta",
          text: "\n\n" + "遥".repeat(25000) + "长段结尾",
          createdAt: "",
        },
      ],
    }),
  );
  await waitFor(() => expect(preview).toHaveTextContent("长段结尾"));
  await act(async () => {
    send("snapshot", {
      run: {
        ...run,
        status: "succeeded",
        answer: "核验后的最终答复",
        answerPreview: "",
      },
      cursor: 4,
      events: [],
    });
    send("end", { reason: "settled" });
    controller.close();
  });
  await screen.findByText("核验后的最终答复");
  expect(
    screen.queryByRole("region", { name: "答复增量预览" }),
  ).not.toBeInTheDocument();
  expect(poll).not.toHaveBeenCalled();
});

it("unmounting closes the byte stream and does not cancel the underlying task", async () => {
  const cancelled = vi.fn();
  const response = new Response(
    new ReadableStream<Uint8Array>({ cancel: cancelled }),
    { headers: { "Content-Type": "text/event-stream" } },
  );
  const stream = vi
    .spyOn(agentApi, "stream")
    .mockImplementation((_id, onEvent, signal) =>
      consumeServerEvents(response, onEvent, signal),
    );
  const cancelTask = vi.spyOn(agentApi, "cancel");
  const view = show();
  await waitFor(() => expect(stream).toHaveBeenCalledOnce());
  view.unmount();
  await waitFor(() => expect(cancelled).toHaveBeenCalledOnce());
  expect(cancelTask).not.toHaveBeenCalled();
});
