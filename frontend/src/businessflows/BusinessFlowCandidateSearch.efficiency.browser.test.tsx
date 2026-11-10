import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type {
  AgentResource,
  AgentResourceList,
} from "../api/generated/types.gen";
import { businessFlowsApi } from "../api/businessFlows";
import { agentApi } from "../api/agent";
import {
  getActiveProject,
  resetProjectSession,
  setActiveProject,
} from "../projects/session";
import { invalidateBrowserRequests } from "../auth/browserSession";
import BusinessFlowLaunch from "./BusinessFlowLaunch";
import {
  researchDetail,
  researchVersion,
  directInputPlan,
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
      ],
    },
    status: "ready",
  }),
}));
const intent = {
  definitionId: 2,
  versionId: 21,
  title: "项目资料摘要",
  goal: "比较两份项目资料。",
};
const resource = (id: number, name = `项目资料${id}`): AgentResource => ({
  id,
  name,
  dataType: "table",
  description: "本项目已登记资料",
});
const firstPage = Array.from({ length: 50 }, (_, index) => resource(index + 1));
function deferred() {
  let resolve!: (value: AgentResourceList) => void;
  const promise = new Promise<AgentResourceList>((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}
function show() {
  return render(
    <App>
      <MemoryRouter>
        <BusinessFlowLaunch
          launch={intent}
          model="executor"
          onStarted={vi.fn()}
          onCancel={vi.fn()}
        />
      </MemoryRouter>
    </App>,
  );
}
const input = (role = "主资料") =>
  screen.getByRole("combobox", { name: `${role}：选择资料` });
async function choose(name: string) {
  const option = () =>
    screen.getByText(
      (_text, element) =>
        element?.classList.contains("ant-select-item-option-content") ===
          true && element.textContent === name,
    );
  await waitFor(() => expect(option()).toBeVisible());
  fireEvent.click(option());
}
beforeEach(() => {
  vi.spyOn(businessFlowsApi, "prepareInputs").mockImplementation(
    async (_id, request) => directInputPlan(request),
  );
  setActiveProject("3");
  const definition = {
    ...researchVersion.definition,
    inputRequirements: [
      {
        key: "source",
        label: "主资料",
        description: "选择主要资料。",
        dataTypes: ["table" as const],
        required: true,
        requiredFields: [],
      },
      {
        key: "comparison",
        label: "对比资料",
        description: "选择对比资料。",
        dataTypes: ["table" as const],
        required: false,
        requiredFields: [],
      },
    ],
  };
  const version = { ...researchVersion, definition };
  vi.spyOn(businessFlowsApi, "detail").mockResolvedValue({
    ...researchDetail,
    version,
    versions: [version],
  });
  vi.spyOn(agentApi, "resources").mockResolvedValue({ items: firstPage });
});
afterEach(() => {
  vi.restoreAllMocks();
  resetProjectSession();
});

it("waits for IME completion and explains description-only matches", async () => {
  vi.mocked(agentApi.resources).mockImplementation(async (query = "") => ({
    items: query
      ? [{ ...resource(99, "区域观测"), description: "该资料记录地质构造" }]
      : firstPage,
  }));
  show();
  await screen.findByRole("textbox", { name: "本次任务目标" });
  fireEvent.mouseDown(input());
  await waitFor(() => expect(agentApi.resources).toHaveBeenCalledOnce());
  fireEvent.compositionStart(input());
  fireEvent.change(input(), { target: { value: "di" } });
  await act(async () => new Promise((resolve) => setTimeout(resolve, 400)));
  expect(agentApi.resources).toHaveBeenCalledOnce();
  fireEvent.change(input(), { target: { value: "地质" } });
  fireEvent.compositionEnd(input(), { data: "地质" });
  await waitFor(() => expect(agentApi.resources).toHaveBeenCalledTimes(2));
  expect(vi.mocked(agentApi.resources).mock.calls[1]?.[0]).toBe("地质");
  expect(await screen.findByText("地质", { selector: "mark" })).toBeVisible();
  expect(screen.getByText(/说明：/)).toHaveTextContent("该资料记录地质构造");
});

it("does not load an empty catalog when composition opens a closed selector", async () => {
  show();
  await screen.findByRole("textbox", { name: "本次任务目标" });
  fireEvent.compositionStart(input());
  fireEvent.change(input(), { target: { value: "di" } });
  fireEvent.mouseDown(input());
  await act(async () => new Promise((resolve) => setTimeout(resolve, 400)));
  expect(agentApi.resources).not.toHaveBeenCalled();
  fireEvent.change(input(), { target: { value: "地质" } });
  fireEvent.compositionEnd(input(), { data: "地质" });
  await waitFor(() => expect(agentApi.resources).toHaveBeenCalledOnce());
  expect(vi.mocked(agentApi.resources).mock.calls[0]?.[0]).toBe("地质");
});

it("finds the 51st registered item through debounced remote search and keeps the other selected label", async () => {
  const beyond = resource(51, "第51条已登记资料");
  vi.mocked(agentApi.resources).mockImplementation(async (query = "") => ({
    items: query ? [beyond] : firstPage,
  }));
  show();
  await screen.findByRole("textbox", { name: "本次任务目标" });
  expect(agentApi.resources).not.toHaveBeenCalled();
  fireEvent.mouseDown(input());
  await choose("项目资料1");
  fireEvent.mouseDown(input("对比资料"));
  expect(agentApi.resources).toHaveBeenCalledOnce();
  fireEvent.change(input("对比资料"), { target: { value: "第" } });
  fireEvent.change(input("对比资料"), { target: { value: "第51" } });
  fireEvent.change(input("对比资料"), { target: { value: "第51条" } });
  await waitFor(() => expect(agentApi.resources).toHaveBeenCalledTimes(2));
  expect(vi.mocked(agentApi.resources).mock.calls[1]?.[0]).toBe("第51条");
  await choose(beyond.name);
  expect(input().closest(".business-flow-launch-field")).toHaveTextContent(
    "项目资料1",
  );
  expect(
    input("对比资料").closest(".business-flow-launch-field"),
  ).toHaveTextContent(beyond.name);
  expect(screen.queryByText("资料已不可用")).not.toBeInTheDocument();
});

it("shares one in-flight empty query across roles rather than reading once per field", async () => {
  const gate = deferred();
  vi.mocked(agentApi.resources).mockReturnValue(gate.promise);
  show();
  await screen.findByRole("textbox", { name: "本次任务目标" });
  fireEvent.mouseDown(input());
  await waitFor(() => expect(agentApi.resources).toHaveBeenCalledOnce());
  fireEvent.mouseDown(input("对比资料"));
  expect(agentApi.resources).toHaveBeenCalledOnce();
  await act(async () => gate.resolve({ items: firstPage }));
  await choose("项目资料2");
  fireEvent.mouseDown(input());
  expect(agentApi.resources).toHaveBeenCalledOnce();
});

it("aborts superseded searches, ignores late bodies and cancels pending work on unmount", async () => {
  const old = deferred(),
    late = deferred();
  vi.mocked(agentApi.resources).mockImplementation(async (query = "") =>
    query === "旧查询"
      ? old.promise
      : query === "卸载中"
        ? late.promise
        : {
            items: [
              resource(query ? 99 : 1, query ? "当前查询结果" : "初始资料"),
            ],
          },
  );
  const view = show();
  await screen.findByRole("textbox", { name: "本次任务目标" });
  fireEvent.mouseDown(input());
  await waitFor(() => expect(agentApi.resources).toHaveBeenCalledOnce());
  fireEvent.change(input(), { target: { value: "旧查询" } });
  await waitFor(() => expect(agentApi.resources).toHaveBeenCalledTimes(2));
  const staleSignal = vi.mocked(agentApi.resources).mock.calls[1]?.[1]?.signal;
  expect(staleSignal?.aborted).toBe(false);
  fireEvent.change(input(), { target: { value: "新查询" } });
  expect(staleSignal?.aborted).toBe(true);
  await waitFor(() => expect(agentApi.resources).toHaveBeenCalledTimes(3));
  const latestOption = await screen.findByRole("group", {
    name: "当前查询结果",
  });
  await waitFor(() => expect(latestOption).toBeVisible());
  await act(async () =>
    old.resolve({ items: [resource(88, "不应回写的旧结果")] }),
  );
  expect(screen.queryByText("不应回写的旧结果")).not.toBeInTheDocument();
  expect(screen.getByRole("group", { name: "当前查询结果" })).toBeVisible();
  fireEvent.change(input(), { target: { value: "卸载中" } });
  await waitFor(() => expect(agentApi.resources).toHaveBeenCalledTimes(4));
  const pending = vi.mocked(agentApi.resources).mock.calls[3]?.[1]?.signal;
  view.unmount();
  expect(pending?.aborted).toBe(true);
  await act(async () =>
    late.resolve({ items: [resource(77, "卸载后不回写")] }),
  );
  expect(screen.queryByText("卸载后不回写")).not.toBeInTheDocument();
});

it("does not launch a delayed search after closing the dropdown and retries an actual failure", async () => {
  vi.mocked(agentApi.resources).mockImplementation(async (query = "") => {
    if (
      query === "会失败" &&
      vi
        .mocked(agentApi.resources)
        .mock.calls.filter((call) => call[0] === "会失败").length === 1
    )
      throw new Error("搜索暂时失败");
    return { items: [resource(1, query ? "重试成功资料" : "初始资料")] };
  });
  show();
  await screen.findByRole("textbox", { name: "本次任务目标" });
  fireEvent.mouseDown(input());
  await waitFor(() => expect(agentApi.resources).toHaveBeenCalledOnce());
  fireEvent.change(input(), { target: { value: "会失败" } });
  expect(
    await screen.findByText("搜索暂时失败", { selector: ".ant-alert-title" }),
  ).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "重试读取资料" }));
  await waitFor(() => expect(agentApi.resources).toHaveBeenCalledTimes(3));
  await choose("重试成功资料");
  fireEvent.mouseDown(input("对比资料"));
  await waitFor(() => expect(agentApi.resources).toHaveBeenCalledTimes(4));
  fireEvent.change(input("对比资料"), { target: { value: "不应发送" } });
  fireEvent.blur(input("对比资料"));
  fireEvent.mouseDown(screen.getByRole("textbox", { name: "本次任务目标" }));
  await new Promise((resolve) => setTimeout(resolve, 350));
  expect(agentApi.resources).toHaveBeenCalledTimes(4);
});

it.each(["project", "account"])(
  "clears candidates and selected labels at the %s authorization boundary",
  async (boundary) => {
    vi.mocked(agentApi.resources).mockImplementation(async () => ({
      items: [
        resource(1, getActiveProject() === "3" ? "此前已选资料" : "新项目资料"),
      ],
    }));
    show();
    await screen.findByRole("textbox", { name: "本次任务目标" });
    fireEvent.mouseDown(input());
    await choose("此前已选资料");
    expect(input().closest(".business-flow-launch-field")).toHaveTextContent(
      "此前已选资料",
    );
    await act(async () => {
      if (boundary === "project") setActiveProject("4");
      else invalidateBrowserRequests();
    });
    expect(
      input().closest(".business-flow-launch-field"),
    ).not.toHaveTextContent("此前已选资料");
    fireEvent.mouseDown(input());
    await waitFor(() => expect(agentApi.resources).toHaveBeenCalledTimes(2));
    expect(vi.mocked(agentApi.resources).mock.calls[1]?.[1]?.signal).not.toBe(
      vi.mocked(agentApi.resources).mock.calls[0]?.[1]?.signal,
    );
  },
);
