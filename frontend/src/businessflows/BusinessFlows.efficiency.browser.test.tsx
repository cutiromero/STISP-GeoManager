import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { computeApi } from "../api/compute";
import { computeVersion } from "../agent/computeFlow.testFixtures";
import { businessFlowsApi } from "../api/businessFlows";
import { ApiError } from "../api/client";
import type { BusinessFlowNodeState } from "../api/generated/types.gen";
import platformStyles from "../styles.css?inline";
import BusinessFlowsPage from "./BusinessFlowsPage";
import BusinessFlowGraph, { businessFlowLevels } from "./BusinessFlowGraph";
import BusinessFlowEditor from "./BusinessFlowEditor";
import {
  geologyDetail,
  geologyFlow,
  geologyVersion,
  researchDetail,
  researchFlow,
  researchSpec,
  researchVersion,
  summary,
} from "./businessFlow.testFixtures";

const session = vi.hoisted(() => ({ project: "3", canAgent: true }));
vi.mock("../components/WorkspaceHeader", () => ({
  default: ({ activeTab }: { activeTab: string }) => (
    <header
      style={{ position: "absolute", top: 8, left: 8, right: 8, height: 50 }}
      data-testid="module-header"
    >
      STISP · {activeTab}
    </header>
  ),
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({
    user: {
      id: 99,
      username: "researcher",
      permissions: { canBrowseData: true },
    },
  }),
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => ({
    current: session.project,
    projects: [{ id: Number(session.project), name: "逻辑推理" }],
  }),
}));
vi.mock("../agent/useAgentBootstrap", () => ({
  useAgentBootstrapState: () => ({
    bootstrap: { canAgent: session.canAgent },
    status: "ready",
    error: "",
    retry: vi.fn(),
  }),
}));
function Location() {
  const location = useLocation();
  return (
    <output aria-label="当前导航">
      {JSON.stringify({ path: location.pathname, state: location.state })}
    </output>
  );
}
function show() {
  return render(
    <>
      <style>{platformStyles}</style>
      <App>
        <MemoryRouter>
          <BusinessFlowsPage />
          <Location />
        </MemoryRouter>
      </App>
    </>,
  );
}

it("keeps the diagram and goal after a transient refresh, and clears them after revoked access", async () => {
  show();
  await screen.findByRole("heading", { name: geologyFlow.name });
  const goal = screen.getByRole("textbox", { name: "这次希望完成什么任务" });
  fireEvent.change(goal, { target: { value: "本次分析要求" } });
  vi.mocked(businessFlowsApi.detail).mockRejectedValueOnce(
    new TypeError("temporary network error"),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "刷新业务流", exact: true }),
  );
  await screen.findByText("暂时无法更新，已保留当前流程");
  expect(screen.getByRole("heading", { name: geologyFlow.name })).toBeVisible();
  expect(goal).toHaveValue("本次分析要求");
  vi.mocked(businessFlowsApi.detail).mockRejectedValueOnce(
    new ApiError("项目访问已撤销", 403),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "重新加载", exact: true }),
  );
  await screen.findByText("项目访问已撤销");
  expect(
    screen.queryByRole("heading", { name: geologyFlow.name }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "开始业务流", exact: true }),
  ).not.toBeInTheDocument();
});
beforeEach(() => {
  session.project = "3";
  session.canAgent = true;
  vi.spyOn(businessFlowsApi, "list").mockResolvedValue({
    items: [
      summary(geologyFlow, geologyVersion),
      summary(researchFlow, researchVersion),
    ],
    canManage: false,
  });
  vi.spyOn(businessFlowsApi, "detail").mockImplementation(async (id) =>
    id === 1 ? geologyDetail : researchDetail,
  );
});
afterEach(() => vi.restoreAllMocks());

it("queries each normalized search once and does not reread selected detail on search or node selection", async () => {
  show();
  await screen.findByRole("heading", { name: geologyFlow.name });
  expect(businessFlowsApi.list).toHaveBeenCalledOnce();
  expect(businessFlowsApi.detail).toHaveBeenCalledOnce();
  fireEvent.change(screen.getByRole("textbox", { name: "搜索业务流" }), {
    target: { value: "项目资料" },
  });
  expect(screen.getByRole("button", { name: /项目资料摘要/ })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /审核与处置建议，/ }));
  expect(
    within(
      screen.getByRole("complementary", { name: "节点职责与审核边界" }),
    ).getByText("审核与处置建议"),
  ).toBeVisible();
  expect(
    screen.getByText(
      "此处必须由您作决定。执行与审核智能体都不能代替您的批准。",
    ),
  ).toBeVisible();
  expect(businessFlowsApi.detail).toHaveBeenCalledOnce();
  await waitFor(() => expect(businessFlowsApi.list).toHaveBeenCalledTimes(2));
  fireEvent.change(screen.getByRole("textbox", { name: "搜索业务流" }), {
    target: { value: " 项目资料 " },
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 360));
  });
  expect(businessFlowsApi.list).toHaveBeenCalledTimes(2);
  expect(businessFlowsApi.detail).toHaveBeenCalledOnce();
});

it("launches the selected published version with a task goal and no premature execution", async () => {
  const start = vi.spyOn(businessFlowsApi, "start");
  show();
  await screen.findByRole("heading", { name: geologyFlow.name });
  fireEvent.change(
    screen.getByRole("textbox", { name: "这次希望完成什么任务" }),
    { target: { value: "分析本次研究区的地质资料" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "交给智能体执行" }));
  const navigation = JSON.parse(screen.getByLabelText("当前导航").textContent!);
  expect(navigation.path).toBe("/agent/workbench");
  expect(navigation.state.businessFlowLaunch).toEqual({
    definitionId: 1,
    versionId: 11,
    title: geologyFlow.name,
    goal: "分析本次研究区的地质资料",
  });
  expect(start).not.toHaveBeenCalled();
});

it("shows a simple flow without inventing AI or human checkpoints", async () => {
  show();
  await screen.findByRole("heading", { name: geologyFlow.name });
  fireEvent.click(screen.getByRole("button", { name: /项目资料摘要/ }));
  await screen.findByRole("heading", { name: researchFlow.name });
  expect(screen.getByText("无需 AI 审核")).toBeVisible();
  expect(screen.getByText("无需人工确认")).toBeVisible();
  expect(document.querySelectorAll(".business-flow-node-guards")).toHaveLength(
    0,
  );
  expect(
    screen.getByText("完成本节点要求后自动进入下一步，无需额外确认。"),
  ).toBeVisible();
});

it("has a retryable list failure and does not invent an empty successful catalog", async () => {
  vi.mocked(businessFlowsApi.list).mockRejectedValueOnce(
    new Error("目录暂时不可用"),
  );
  show();
  expect(await screen.findByText("目录暂时不可用")).toBeVisible();
  expect(businessFlowsApi.detail).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  await screen.findByRole("heading", { name: geologyFlow.name });
  expect(businessFlowsApi.list).toHaveBeenCalledTimes(2);
});

it("preserves dependency branches and renders execution/review/human states from the run", async () => {
  const branch = {
    ...researchSpec.nodes[0]!,
    id: "parallel",
    title: "并行分析",
  };
  const nodes = [
    researchSpec.nodes[0]!,
    branch,
    {
      ...researchSpec.nodes[1]!,
      dependsOn: ["analyse", "parallel"],
      review: { ai: true, human: true, maxRevisions: 1 },
    },
  ];
  expect(
    businessFlowLevels(nodes).map((level) => level.map((node) => node.id)),
  ).toEqual([["analyse", "parallel"], ["finish"]]);
  const states: BusinessFlowNodeState[] = [
    {
      nodeId: "finish",
      status: "waiting_human",
      attempt: 2,
      executor: { status: "succeeded" },
      reviewer: { status: "passed", reason: "依据完整" },
      human: { required: true, status: "pending", reason: "等待人类决定" },
      outputs: {},
    },
  ];
  render(
    <App>
      <BusinessFlowGraph nodes={nodes} states={states} />
    </App>,
  );
  expect(
    screen.getByRole("button", { name: /交付摘要，等待您决定/ }),
  ).toBeVisible();
  expect(screen.getByText("等待您决定 · 第 2 次处理")).toBeVisible();
  await waitFor(() =>
    expect(
      document.querySelectorAll(".business-flow-graph-links > path"),
    ).toHaveLength(5),
  );
  expect(() =>
    businessFlowLevels([{ ...nodes[0]!, dependsOn: ["finish"] }, nodes[2]!]),
  ).toThrow();
});

it("locks the professional skeleton and important human gates while publishing a review-policy version", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(
    <App>
      <BusinessFlowEditor
        open
        flow={geologyFlow}
        version={geologyVersion}
        onClose={() => {}}
        onSave={save}
      />
    </App>,
  );
  const approval = screen.getByRole("switch", {
    name: "审核与处置建议：必须由人决定",
  });
  expect(approval).toBeChecked();
  expect(approval).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "添加节点" }),
  ).not.toBeInTheDocument();
  expect(
    screen
      .getAllByRole("textbox", { name: "节点编码" })
      .every((element) => (element as HTMLInputElement).disabled),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "保存并发布" }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(
    save.mock.calls[0]?.[1].nodes.find(
      (node: { id: string }) => node.id === "apply",
    ).review.human,
  ).toBe(true);
});

it("keeps edited node identity stable and prevents duplicate publish requests", async () => {
  let complete!: () => void;
  const save = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        complete = resolve;
      }),
  );
  render(
    <App>
      <BusinessFlowEditor open onClose={() => {}} onSave={save} />
    </App>,
  );
  fireEvent.change(screen.getByRole("textbox", { name: "流程名称" }), {
    target: { value: "科研资料归纳" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "流程编码" }), {
    target: { value: "research_summary" },
  });
  const node = screen.getAllByRole("textbox", { name: "节点编码" })[0]!;
  node.focus();
  fireEvent.change(node, { target: { value: "research_changed" } });
  expect(screen.getAllByRole("textbox", { name: "节点编码" })[0]).toBe(node);
  expect(node).toHaveFocus();
  const publish = screen.getByRole("button", { name: "保存并发布" });
  fireEvent.click(publish);
  fireEvent.click(publish);
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(save.mock.calls[0]?.[1].nodes[1].dependsOn).toEqual([
    "research_changed",
  ]);
  await act(async () => complete());
});

it.each([
  [1440, 1000],
  [390, 844],
])(
  "keeps flow navigation and primary launch available at %sx%s",
  async (width, height) => {
    await page.viewport(width, height);
    try {
      show();
      await screen.findByRole("heading", { name: geologyFlow.name });
      const shell = document.querySelector<HTMLElement>(
        ".business-flows-shell",
      )!;
      expect(shell.scrollWidth).toBeLessThanOrEqual(width);
      if (width < 760) {
        fireEvent.click(screen.getByRole("button", { name: "流程目录" }));
        const dialog = await screen.findByRole("dialog");
        await waitFor(() => expect(dialog).toBeVisible());
        expect(
          within(dialog).getByRole("button", { name: /项目资料摘要/ }),
        ).toBeVisible();
        fireEvent.click(
          within(dialog).getByRole("button", { name: /项目资料摘要/ }),
        );
        await screen.findByRole("heading", { name: researchFlow.name });
        await waitFor(() => expect(dialog).not.toBeVisible());
      }
      const action = screen.getByRole("button", { name: "交给智能体执行" });
      action.scrollIntoView({ block: "center" });
      await waitFor(() =>
        expect(action.getBoundingClientRect().right).toBeLessThanOrEqual(width),
      );
      await page.screenshot({
        path: `../../test-results/business-flow-catalog-${width}.png`,
      });
      if (width >= 760) {
        document.querySelector<HTMLElement>(".business-flow-main")!.scrollTop =
          0;
        await page.screenshot({
          path: `../../test-results/business-flow-diagram-${width}.png`,
        });
      }
    } finally {
      await page.viewport(1600, 900);
    }
  },
);

it("leaves an empty project ready when the previous detail was still loading", async () => {
  let finish!: (value: typeof geologyDetail) => void;
  vi.mocked(businessFlowsApi.detail).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const view = show();
  await waitFor(() => expect(businessFlowsApi.detail).toHaveBeenCalledOnce());
  vi.mocked(businessFlowsApi.list).mockResolvedValue({
    items: [],
    canManage: false,
  });
  session.project = "4";
  view.rerender(
    <>
      <style>{platformStyles}</style>
      <App>
        <MemoryRouter>
          <BusinessFlowsPage />
          <Location />
        </MemoryRouter>
      </App>
    </>,
  );
  expect(await screen.findByText("当前项目尚未登记业务流")).toBeVisible();
  await act(async () => finish(geologyDetail));
  expect(
    screen.queryByRole("heading", { name: geologyFlow.name }),
  ).not.toBeInTheDocument();
  expect(
    document.querySelector(".business-flow-main .ant-spin-spinning"),
  ).toBeNull();
});

it("keeps all legacy human gates fixed and only exposes supported independent review points", () => {
  render(
    <App>
      <BusinessFlowEditor
        open
        flow={geologyFlow}
        version={geologyVersion}
        onClose={() => {}}
        onSave={vi.fn()}
      />
    </App>,
  );
  for (const node of geologyVersion.definition.nodes) {
    expect(
      screen.getByRole("switch", { name: `${node.title}：必须由人决定` }),
    ).toBeDisabled();
    const reviewer = screen.getByRole("switch", {
      name: `${node.title}：独立 AI 审核`,
    });
    if (["apply", "finish"].includes(node.id)) expect(reviewer).toBeEnabled();
    else expect(reviewer).toBeDisabled();
  }
});

it("preserves declared upstream output bindings when an operator node is renamed", async () => {
  vi.spyOn(computeApi, "algorithms").mockResolvedValue({
    items: [
      {
        id: 1,
        projectTagId: 3,
        identifier: "ndvi",
        name: "NDVI计算",
        description: "指数计算",
        category: "遥感",
        author: "平台",
        enabled: true,
        versions: [computeVersion],
        canManage: true,
      },
    ],
  });
  const definition = {
    ...researchSpec,
    inputRequirements: [
      {
        key: "source",
        label: "原始影像",
        description: "影像资料",
        dataTypes: ["raster" as const],
        required: true,
        requiredFields: [],
      },
    ],
    nodes: [
      {
        ...researchSpec.nodes[0]!,
        id: "first",
        title: "第一步计算",
        kind: "operator" as const,
        algorithmVersionId: 4,
        dataRoles: ["source"],
        inputBindings: { image: { role: "source" } },
      },
      {
        ...researchSpec.nodes[1]!,
        id: "second",
        title: "第二步计算",
        kind: "operator" as const,
        algorithmVersionId: 4,
        dependsOn: ["first"],
        inputBindings: { image: { nodeId: "first", outputKey: "ndvi" } },
      },
    ],
  };
  const save = vi.fn().mockResolvedValue(undefined);
  render(
    <App>
      <BusinessFlowEditor
        open
        flow={researchFlow}
        version={{ ...researchVersion, definition }}
        onClose={() => {}}
        onSave={save}
      />
    </App>,
  );
  fireEvent.click(
    screen.getAllByText("算子输入来源（资料角色或上游输出）")[1]!,
  );
  const binding = screen.getByRole("textbox", {
    name: "第二步计算：算子输入来源",
  });
  expect(binding).toHaveValue(
    JSON.stringify({ image: { nodeId: "first", outputKey: "ndvi" } }, null, 2),
  );
  fireEvent.change(screen.getAllByRole("textbox", { name: "节点编码" })[0]!, {
    target: { value: "source_calc" },
  });
  expect(binding).toHaveValue(
    JSON.stringify(
      { image: { nodeId: "source_calc", outputKey: "ndvi" } },
      null,
      2,
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "保存并发布" }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(save.mock.calls[0]?.[1].nodes[1]).toMatchObject({
    dependsOn: ["source_calc"],
    inputBindings: { image: { nodeId: "source_calc", outputKey: "ndvi" } },
  });
  expect(computeApi.algorithms).toHaveBeenCalledOnce();
});

it("allows independent review before a generic human decision without making that decision optional", () => {
  const definition = {
    ...researchSpec,
    nodes: [
      {
        ...researchSpec.nodes[0]!,
        kind: "human" as const,
        review: { ai: false, human: true, maxRevisions: 0 },
      },
      researchSpec.nodes[1]!,
    ],
  };
  render(
    <App>
      <BusinessFlowEditor
        open
        flow={researchFlow}
        version={{ ...researchVersion, definition }}
        onClose={() => {}}
        onSave={vi.fn()}
      />
    </App>,
  );
  const ai = screen.getByRole("switch", { name: "分析项目资料：独立 AI 审核" });
  expect(ai).toBeEnabled();
  fireEvent.click(ai);
  expect(ai).toBeChecked();
  const human = screen.getByRole("switch", {
    name: "分析项目资料：必须由人决定",
  });
  expect(human).toBeChecked();
  expect(human).toBeDisabled();
});

it("preserves a human-only node's revision limit while independent AI review is toggled", async () => {
  const definition = {
    ...researchSpec,
    nodes: [
      {
        ...researchSpec.nodes[0]!,
        kind: "human" as const,
        review: { ai: false, human: true, maxRevisions: 0 },
      },
      researchSpec.nodes[1]!,
    ],
  };
  const save = vi.fn().mockResolvedValue(undefined);
  render(
    <App>
      <BusinessFlowEditor
        open
        flow={researchFlow}
        version={{ ...researchVersion, definition }}
        onClose={() => {}}
        onSave={save}
      />
    </App>,
  );
  const ai = screen.getByRole("switch", { name: "分析项目资料：独立 AI 审核" });
  const human = screen.getByRole("switch", {
    name: "分析项目资料：必须由人决定",
  });
  const node = ai.closest(".business-flow-editor-node") as HTMLElement;
  const limit = within(node).getByRole("spinbutton");
  expect(ai).not.toBeChecked();
  expect(human).toBeChecked();
  expect(human).toBeDisabled();
  fireEvent.change(limit, { target: { value: "2" } });
  fireEvent.blur(limit);
  expect(limit).toHaveDisplayValue("2");
  fireEvent.click(ai);
  expect(ai).toBeChecked();
  expect(within(node).getByRole("spinbutton")).toHaveDisplayValue("2");
  fireEvent.click(ai);
  expect(ai).not.toBeChecked();
  expect(within(node).getByRole("spinbutton")).toHaveDisplayValue("2");
  fireEvent.click(screen.getByRole("button", { name: "保存并发布" }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(save.mock.calls[0]?.[1].nodes[0].review).toMatchObject({
    ai: false,
    human: true,
    maxRevisions: 2,
  });
});
