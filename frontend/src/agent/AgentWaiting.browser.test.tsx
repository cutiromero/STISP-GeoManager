import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App, ConfigProvider } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type {
  AgentBootstrap,
  AgentConversation,
  AgentRun,
} from "../api/generated/types.gen";
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
    projects: [{ id: 1, name: "公开" }],
  }),
}));
vi.mock("./useAgentBootstrap", () => ({ useAgentBootstrap: () => bootstrap }));

const bootstrap: AgentBootstrap = {
  canChat: true,
  canAgent: true,
  canManage: false,
  thinkingEnabled: true,
  defaultReasoningEffort: "medium",
  internetEnabled: false,
  allowAttachments: false,
  workerOnline: true,
  defaultChatModel: "qwen",
  defaultAgentModel: "qwen",
  capabilities: [],
  models: [
    {
      alias: "qwen",
      name: "Qwen",
      allowAgent: true,
      contextWindowTokens: 32768,
      supportsThinking: true,
      supportsVision: false,
      status: "online",
      checkedAt: "",
    },
  ],
};
const conversation: AgentConversation = {
  id: 39,
  projectId: 1,
  mode: "chat",
  title: "植被分析",
  archived: false,
  createdAt: "2026-10-16",
  updatedAt: "2026-10-16",
};
const waitingRun: AgentRun = {
  id: 139,
  conversationId: 39,
  model: "qwen",
  status: "waiting_input",
  prompt:
    "我想分析植被变化，但还没想清楚怎么做。你先问我一个最关键的问题，等我回答后再继续。",
  answer: "",
  detail: "等待您回答",
  evidence: [],
  attachments: [],
  thinkingMode: "deep",
  thinkingText: "先确认用户想分析哪类植被变化，再确定所需数据与分析方向。",
  contextTruncated: false,
  createdAt: "2026-10-16",
  updatedAt: "2026-10-16",
  interaction: {
    questionId: "vegetation-target",
    revision: 1,
    kind: "input",
    status: "pending",
    title: "你想分析的植被变化具体指什么？",
    reason: "变化目标决定需要的数据和下一步分析方法。",
    questions: [
      {
        key: "change",
        label: "希望了解的变化",
        type: "multiple",
        required: true,
        options: [
          { value: "cover", label: "植被覆盖范围" },
          { value: "health", label: "植被健康状况" },
          { value: "season", label: "季节变化" },
          { value: "species", label: "物种组成" },
          { value: "unsure", label: "还不确定" },
        ],
      },
    ],
    createdAt: "2026-10-16",
  },
  interactionHistory: [],
};

function show(mode: "chat" | "workbench", demo = false) {
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <MemoryRouter
          initialEntries={[
            {
              pathname: `/agent/${mode}`,
              ...(demo
                ? {
                    state: {
                      researchDemo: {
                        scenario: "ecology_investigation",
                        projectId: 1,
                        prompt: waitingRun.prompt,
                        token: "waiting-demo-token",
                      },
                    },
                  }
                : {}),
            },
          ]}
        >
          <AgentPage />
        </MemoryRouter>
      </App>
    </ConfigProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
  vi.spyOn(agentApi, "conversations").mockResolvedValue({
    items: [conversation],
  });
  vi.spyOn(agentApi, "detail").mockResolvedValue({
    conversation,
    runs: [waitingRun],
  });
  vi.spyOn(agentApi, "resources").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "workflows").mockResolvedValue({ items: [] });
  vi.spyOn(computeApi, "algorithms").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(computeApi, "inputs").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(agentApi, "submit").mockResolvedValue(waitingRun);
});

it.each(["chat", "workbench"] as const)(
  "%s restores an answerable question with an explicit composer target",
  async (mode) => {
    const view = show(mode);
    const card = await screen.findByRole("region", {
      name: "等待您回答的问题",
    });
    expect(within(card).getByText("植被健康状况")).toBeVisible();
    expect(screen.getByText("在下方回答当前问题")).toBeVisible();
    expect(screen.getByRole("button", { name: "提交回答" })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "重试" }),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByLabelText("当前任务")).getByText("等待您回答"),
    ).toBeVisible();
    const input = screen.getByRole("textbox", { name: "输入消息" });
    expect(input).toHaveAttribute("aria-describedby", "agent-answer-target");
    expect(input).toHaveAttribute(
      "placeholder",
      "可直接补充回答，或在上方问题卡中选择并继续",
    );
    if (mode === "chat") {
      expect(
        screen.queryByRole("button", { name: "调用算法" }),
      ).not.toBeInTheDocument();
      expect(agentApi.resources).not.toHaveBeenCalled();
    }
    fireEvent.click(screen.getByRole("button", { name: "查看问题" }));
    expect(
      within(card).getByRole("checkbox", { name: "植被覆盖范围" }),
    ).toHaveFocus();
    await page.screenshot({
      path: `../../test-results/agent-waiting-answer-${mode}.png`,
    });
    view.unmount();
    show(mode);
    await screen.findByRole("region", { name: "等待您回答的问题" });
    expect(agentApi.submit).not.toHaveBeenCalled();
  },
);

it.each(["chat", "workbench"] as const)(
  "%s reveals a live question and sends a typed answer to the same run",
  async (mode) => {
    const processing: AgentRun = {
      ...waitingRun,
      status: "running",
      detail: "正在思考",
      interaction: null,
    };
    vi.mocked(agentApi.detail).mockResolvedValue({
      conversation,
      runs: [processing],
    });
    vi.spyOn(agentApi, "poll").mockResolvedValue({
      run: waitingRun,
      events: [],
      cursor: 0,
    });
    const continued: AgentRun = {
      ...waitingRun,
      status: "queued",
      detail: "正在继续处理",
      interaction: null,
    };
    const answer = vi
      .spyOn(agentApi, "answerInteraction")
      .mockImplementation(async () => {
        vi.mocked(agentApi.poll).mockResolvedValue({
          run: continued,
          events: [],
          cursor: 0,
        });
        return continued;
      });
    show(mode);
    await screen.findByRole("region", { name: "等待您回答的问题" });
    fireEvent.change(screen.getByRole("textbox", { name: "输入消息" }), {
      target: { value: "我关注植被健康状况，目前只有两期NDVI" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交回答" }));
    await waitFor(() =>
      expect(answer).toHaveBeenCalledExactlyOnceWith(
        139,
        expect.objectContaining({
          action: "answer",
          questionId: "vegetation-target",
          revision: 1,
          answers: {},
          text: "我关注植被健康状况，目前只有两期NDVI",
        }),
      ),
    );
    await screen.findByRole("button", { name: "停止回答" });
    expect(
      screen.queryByRole("region", { name: "等待您回答的问题" }),
    ).not.toBeInTheDocument();
    expect(agentApi.submit).not.toHaveBeenCalled();
  },
);

it("keeps a question from the showcase demo in the same run when answered", async () => {
  const processing: AgentRun = {
    ...waitingRun,
    status: "queued",
    detail: "正在分析任务",
    interaction: null,
  };
  vi.spyOn(agentApi, "create").mockResolvedValue({
    ...conversation,
    mode: "agent",
  });
  vi.mocked(agentApi.submit).mockResolvedValue(processing);
  vi.spyOn(agentApi, "poll").mockResolvedValue({
    run: waitingRun,
    events: [],
    cursor: 0,
  });
  const answer = vi
    .spyOn(agentApi, "answerInteraction")
    .mockImplementation(async () => {
      vi.mocked(agentApi.poll).mockResolvedValue({
        run: processing,
        events: [],
        cursor: 0,
      });
      return processing;
    });
  show("workbench", true);
  const card = await screen.findByRole("region", { name: "等待您回答的问题" });
  fireEvent.click(within(card).getByRole("checkbox", { name: "植被健康状况" }));
  fireEvent.click(within(card).getByRole("button", { name: "确认并继续" }));
  await waitFor(() =>
    expect(answer).toHaveBeenCalledExactlyOnceWith(
      139,
      expect.objectContaining({
        action: "answer",
        questionId: "vegetation-target",
        answers: { change: ["health"] },
      }),
    ),
  );
  expect(agentApi.submit).toHaveBeenCalledExactlyOnceWith(
    39,
    expect.objectContaining({
      demoScenario: "ecology_investigation",
      idempotencyKey: "waiting-demo-token",
    }),
  );
  expect(agentApi.create).toHaveBeenCalledOnce();
  await screen.findByRole("button", { name: "停止回答" });
});
