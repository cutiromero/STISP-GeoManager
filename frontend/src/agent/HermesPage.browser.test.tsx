import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { requestEventStream, requestJson } from "../api/client";
import HermesPage from "./HermesPage";

vi.mock("../components/WorkspaceHeader", () => ({ default: () => null }));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: { id: 17, permissions: {} } }),
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => ({
    current: "1",
    projects: [{ id: 1, name: "公开" }],
  }),
}));
vi.mock("./AgentPage", () => ({
  default: ({ runtimeSwitch }: { runtimeSwitch?: React.ReactNode }) => (
    <div>原有记录页面{runtimeSwitch}</div>
  ),
}));
vi.mock("../api/client", async (load) => ({
  ...(await load<typeof import("../api/client")>()),
  requestJson: vi.fn(),
  requestEventStream: vi.fn(),
}));

it("uses the platform workspace and composer with native Hermes sessions and an on-demand tools panel", async () => {
  const prefix = "/api/agent/hermes";
  const session = {
    id: "stisp_test",
    title: "新会话",
    last_run_id: null,
    internet_enabled: true,
  };
  const output =
    "已读取业务流目录\n[公开来源](https://science.nasa.gov/mission/landsat-9/)";
  const runId = "run_test";
  let completed = false;
  const request = vi.mocked(requestJson);
  request.mockImplementation(async (address, options) => {
    switch (address.slice(prefix.length)) {
      case "/v1/capabilities":
        return { session_modes: ["agent"], public_web_enabled: true };
      case "/api/sessions?mode=agent":
        return { data: [], has_more: false };
      case "/api/sessions":
        expect(options?.method).toBe("POST");
        expect(options?.body).toEqual({
          mode: "agent",
          internet_enabled: true,
        });
        return { session };
      case `/api/sessions/${session.id}`:
        expect(options).toMatchObject({
          method: "PATCH",
          body: { internet_enabled: false },
        });
        return { session: { ...session, internet_enabled: false } };
      case "/v1/skills":
        return {
          data: [{ name: "research-workflow", description: "科研业务流指南" }],
        };
      case "/v1/toolsets":
        return {
          data: [
            {
              name: "web",
              label: "Web",
              enabled: true,
              configured: true,
              tools: ["web_search", "web_extract"],
            },
            {
              name: "skills",
              label: "Skills",
              enabled: true,
              tools: ["skill_view"],
            },
            {
              name: "unavailable",
              label: "不可用工具",
              enabled: false,
              tools: [],
            },
          ],
        };
      case "/v1/runs":
        expect(options?.body).toEqual({
          input: "查看发布流程",
          session_id: session.id,
        });
        expect(options?.idempotencyKey).toBeTruthy();
        return { run_id: runId, status: "started" };
      case `/v1/runs/${runId}`:
        return {
          status: completed ? "completed" : "running",
          output,
        };
      case `/api/sessions/${session.id}/messages`:
        return {
          data: [
            { id: 1, role: "user", content: "查看发布流程" },
            { id: 2, role: "assistant", content: output },
          ],
        };
      default:
        throw new Error(`Unexpected request ${address}`);
    }
  });
  let finish = () => {};
  vi.mocked(requestEventStream).mockImplementation(async (url, onEvent) => {
    expect(url).toBe(`${prefix}/v1/runs/${runId}/events?last_seq=-1`);
    onEvent("message", {
      seq: 1,
      event: "message.delta",
      delta: "正在读取目录",
    });
    await new Promise<void>((resolve) => {
      finish = resolve;
    });
    completed = true;
  });

  const { container } = render(
    <App>
      <MemoryRouter initialEntries={["/agent/workbench?runtime=hermes"]}>
        <HermesPage />
      </MemoryRouter>
    </App>,
  );
  const message = await screen.findByRole("textbox", { name: "输入消息" });
  expect(
    container.querySelector(".agent-main .agent-composer")?.contains(message),
  ).toBe(true);
  expect(
    container.querySelector("#agent-conversation-sidebar .agent-history"),
  ).toBeTruthy();
  expect(request.mock.calls.some(([path]) => path.endsWith("/v1/skills"))).toBe(
    false,
  );

  const tools = screen.getByRole("button", { name: "技能与工具" });
  expect(tools.closest(".agent-composer-tools")).toBeTruthy();
  fireEvent.click(tools);
  const skill = await screen.findByText("research-workflow");
  await waitFor(() => expect(skill).toBeVisible());
  expect(screen.getByText("科研业务流指南")).toBeVisible();
  expect(screen.getByText("skill_view")).toBeVisible();
  expect(screen.getByText("web_search")).toBeVisible();
  expect(screen.queryByText("不可用工具")).toBeNull();
  fireEvent.click(tools);
  const internet = screen.getByRole("button", { name: "联网检索" });
  expect(internet).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(internet);
  expect(internet).toHaveAttribute("aria-pressed", "true");

  fireEvent.change(message, { target: { value: "查看发布流程" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(await screen.findByText("正在读取目录")).toBeVisible();
  expect(screen.getByRole("button", { name: "停止回答" })).toBeVisible();
  finish();
  await waitFor(() => expect(screen.queryByText("正在读取目录")).toBeNull());
  const transcript = container.querySelector<HTMLElement>(".agent-messages")!;
  expect(await within(transcript).findByText("已读取业务流目录")).toBeVisible();
  expect(within(transcript).getByText("查看发布流程")).toHaveClass(
    "agent-user-message",
  );
  expect(within(transcript).getByText("MH-Agent")).toBeVisible();
  expect(
    within(transcript).getByRole("link", { name: "公开来源" }),
  ).toHaveAttribute("target", "_blank");
  fireEvent.click(internet);
  await waitFor(() =>
    expect(internet).toHaveAttribute("aria-pressed", "false"),
  );
});

it("keeps the classic runtime as the default and allows explicit switching", async () => {
  const request = vi.mocked(requestJson);
  request.mockClear();
  request.mockImplementation(async (address) => {
    if (address.endsWith("/v1/capabilities"))
      return { session_modes: ["agent"] };
    if (address.includes("/api/sessions")) return { data: [], has_more: false };
    throw new Error(`Unexpected request ${address}`);
  });
  render(
    <App>
      <MemoryRouter initialEntries={["/agent/workbench?projectTagId=1"]}>
        <HermesPage />
      </MemoryRouter>
    </App>,
  );
  expect(screen.getByText("原有记录页面")).toBeVisible();
  expect(request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("新版"));
  expect(
    await screen.findByRole("textbox", { name: "输入消息" }),
  ).toBeVisible();
  fireEvent.click(screen.getByText("经典版"));
  expect(await screen.findByText("原有记录页面")).toBeVisible();
});

it("opens a versioned research task with the shared data picker and native task list", async () => {
  const session = { id: "stisp_research", title: "新会话", last_run_id: null };
  const taskId = "f8c01bb8-b122-4e13-b480-aee6f4862d98";
  const plan = {
    revision: 1,
    todos: [{ id: "inspect", content: "检查样点字段", status: "in_progress" }],
  };
  let finished = false;
  vi.mocked(requestJson).mockImplementation(async (address, options) => {
    if (address.endsWith("/v1/capabilities"))
      return { session_modes: ["agent"] };
    if (address.endsWith("/api/sessions?mode=agent")) return { data: [] };
    if (address.endsWith("/api/sessions")) return { session };
    if (address.includes("/workflow-uploads/references/")) {
      return {
        total: 1,
        directories: [{ id: 5, name: "样地" }],
        items: [
          {
            id: 42,
            name: "调查样点",
            dataType: "table",
            description: "野外样点",
          },
        ],
      };
    }
    if (address.endsWith("/v1/runs")) {
      expect(options?.body).toMatchObject({
        input: expect.stringMatching(/版本编号 17[\s\S]*核对调查资料[\s\S]*42/),
        session_id: session.id,
      });
      return { run_id: "run_research", status: "started" };
    }
    if (address.endsWith("/v1/runs/run_research"))
      return {
        status: finished ? "completed" : "running",
        output: "已完成资料检查",
      };
    if (address.endsWith(`/api/sessions/${session.id}/messages`)) {
      return {
        data: [
          {
            id: 1,
            role: "tool",
            tool_name: "todo_list",
            content: JSON.stringify(plan),
          },
          {
            id: 2,
            role: "tool",
            tool_name: "submit_research_compute",
            content: JSON.stringify({ taskId }),
          },
          { id: 3, role: "assistant", content: "已完成资料检查" },
        ],
      };
    }
    throw new Error(`Unexpected request ${address}`);
  });

  let complete = () => {};
  vi.mocked(requestEventStream).mockImplementation(async (_, onEvent) => {
    onEvent("message", {
      seq: 1,
      event: "tool.completed",
      tool: "todo_list",
      preview: JSON.stringify(plan),
      error: false,
    });
    await new Promise<void>((resolve) => {
      complete = resolve;
    });
    finished = true;
  });

  render(
    <App>
      <MemoryRouter
        initialEntries={[
          {
            pathname: "/agent/workbench",
            search: "?runtime=hermes",
            state: {
              hermesWorkflow: {
                title: "科研资料摘要",
                goal: "核对调查资料",
                versionId: 17,
                projectId: "1",
              },
            },
          },
        ]}
      >
        <HermesPage />
      </MemoryRouter>
    </App>,
  );
  expect(await screen.findByRole("textbox", { name: "输入消息" })).toHaveValue(
    "核对调查资料",
  );
  fireEvent.click(screen.getByRole("button", { name: "选择系统数据" }));
  fireEvent.click(
    await screen.findByRole("checkbox", { name: "选择调查样点" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "加入本次任务" }));
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  const tasks = await screen.findByRole("region", { name: "任务清单" });
  expect(within(tasks).getByText("检查样点字段")).toBeVisible();
  complete();
  expect(
    await screen.findByRole("link", { name: "查看计算任务" }),
  ).toHaveAttribute("href", `/compute?task=${taskId}&projectTagId=1`);
});
