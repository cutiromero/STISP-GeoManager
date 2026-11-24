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
      {JSON.stringify({
        path: location.pathname,
        search: location.search,
        state: location.state,
      })}
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
  expect(screen.getByText("核对本节点结果后，选择通过或返修。")).toBeVisible();
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
  fireEvent.click(screen.getByRole("button", { name: "开始任务" }));
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

it("opens the Manans monitoring-shaped flow in the Agent workbench", async () => {
  const flow = { ...researchFlow, name: "玛纳斯冰川解译", code: "manans-glacier-interpretation" };
  const version = {
    ...researchVersion,
    definition: {
      ...researchSpec,
      inputRequirements: [{
        key: "image",
        label: "玛纳斯原始影像",
        description: "选择一景原始影像",
        dataTypes: ["raster" as const],
        required: true,
        requiredFields: [],
      }],
      nodes: researchSpec.nodes.map((node) => node.id !== researchSpec.nodes[0]?.id ? node : {
        ...node,
        contract: {
          goal: "解译",
          acceptance: ["真实影像"],
          requiredOutputs: [
            { name: "classification", semanticType: "raster" },
            { name: "statistics", semanticType: "table" },
          ],
          tools: ["finish_node"],
        },
      }),
    },
  };
  vi.mocked(businessFlowsApi.list).mockResolvedValue({ items: [summary(flow, version)], canManage: false });
  vi.mocked(businessFlowsApi.detail).mockResolvedValue({ ...researchDetail, flow, version, versions: [version] });
  show();
  await screen.findByRole("heading", { name: flow.name });
  fireEvent.click(screen.getByRole("button", { name: "开始任务" }));
  const location = JSON.parse(screen.getByLabelText("当前导航").textContent!);
  expect(location.path).toBe("/agent/workbench");
  expect(location.state.businessFlowLaunch.versionId).toBe(version.id);
  expect(screen.queryByRole("dialog", { name: "准备监测任务" })).not.toBeInTheDocument();
});

it("shows a simple flow without inventing AI or human checkpoints", async () => {
  show();
  await screen.findByRole("heading", { name: geologyFlow.name });
  fireEvent.click(screen.getByRole("button", { name: /项目资料摘要/ }));
  await screen.findByRole("heading", { name: researchFlow.name });
  expect(screen.getByText("无需结果审核")).toBeVisible();
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

function selectEditorNode(title: string) {
  fireEvent.click(
    screen.getByRole("button", {
      name: (name) => name.startsWith(`${title}，`),
    }),
  );
}

function openNodeIdentity() {
  fireEvent.click(screen.getByText("节点标识", { selector: "summary" }));
  return screen.getByRole("textbox", { name: "节点编码" });
}

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
  selectEditorNode("审核与处置建议");
  const approval = screen.getByRole("switch", {
    name: "审核与处置建议：必须由人决定",
  });
  expect(approval).toBeChecked();
  expect(approval).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "添加节点" }),
  ).not.toBeInTheDocument();
  expect(openNodeIdentity()).toBeDisabled();
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
  const publish = screen.getByRole("button", { name: "保存并发布" });
  fireEvent.click(screen.getByRole("radio", { name: "科研目的" }));
  const instructions =
    "确定哪些岩性差异值得现场复核，用区域地质标准核对可比的字段。";
  fireEvent.change(
    screen.getByRole("textbox", { name: "科研目的与判断依据" }),
    {
      target: { value: instructions },
    },
  );
  const question = "对照两幅图前应核对哪种填图比例尺？";
  fireEvent.change(screen.getByRole("textbox", { name: "待查证的知识问题" }), {
    target: { value: question },
  });
  fireEvent.click(screen.getByRole("radio", { name: "资料与交付" }));
  const outputs = screen.getByRole("textbox", { name: "交付要求" });
  fireEvent.change(outputs, { target: { value: "岩性复核清单" } });
  fireEvent.click(screen.getByRole("radio", { name: "节点设计" }));
  const node = openNodeIdentity();
  node.focus();
  fireEvent.change(node, { target: { value: "research_changed" } });
  expect(screen.getByRole("textbox", { name: "节点编码" })).toBe(node);
  expect(node).toHaveFocus();
  for (const [name, purpose, guidance] of [
    [
      "分析项目资料",
      "识别不能直接对照的岩性单元。",
      "用字段语义和样本定位差异。",
    ],
    [
      "整理科研成果",
      "确定外业核查的优先次序。",
      "按证据完整度整理带图斑编号的清单。",
    ],
  ]) {
    selectEditorNode(name!);
    expect(
      document.querySelectorAll(".business-flow-editor-node"),
    ).toHaveLength(1);
    fireEvent.change(screen.getByRole("textbox", { name: "节点目的" }), {
      target: { value: purpose },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "判断与交付" }), {
      target: { value: guidance },
    });
  }
  selectEditorNode("分析项目资料");
  fireEvent.click(
    screen.getByRole("checkbox", { name: "允许按资料选择已发布算子" }),
  );
  const acceptance = screen.getByRole("textbox", { name: "验收条件" });
  fireEvent.change(acceptance, {
    target: { value: "差异可以追溯到具体的图斑编号" },
  });
  fireEvent.click(publish);
  fireEvent.click(publish);
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(save.mock.calls[0]?.[1].skill.instructions).toBe(instructions);
  expect(save.mock.calls[0]?.[1].skill.knowledgeQuestions).toEqual([question]);
  expect(save.mock.calls[0]?.[1].nodes[0].contract).toMatchObject({
    goal: "识别不能直接对照的岩性单元。",
    acceptance: ["差异可以追溯到具体的图斑编号"],
    tools: expect.arrayContaining([
      "operator_catalog",
      "preflight_operator",
      "run_operator",
    ]),
  });
  expect(save.mock.calls[0]?.[1].nodes[1].dependsOn).toEqual([
    "research_changed",
  ]);
  await act(async () => complete());
});

it("adds a branch after the node chosen in the diagram on a narrow screen", async () => {
  await page.viewport(390, 844);
  try {
    render(
      <App>
        <BusinessFlowEditor open onClose={() => {}} onSave={vi.fn()} />
      </App>,
    );
    selectEditorNode("整理科研成果");
    fireEvent.click(screen.getByRole("button", { name: "添加节点" }));
    expect(screen.getByRole("button", { name: /^新节点，/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("textbox", { name: "节点名称" })).toHaveValue("");
    const dialog = screen.getByRole("dialog");
    expect(dialog.getBoundingClientRect().width).toBeLessThanOrEqual(390);
    expect(dialog.querySelectorAll(".business-flow-editor-node")).toHaveLength(
      1,
    );
  } finally {
    await page.viewport(1440, 900);
  }
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
      const action = screen.getByRole("button", { name: "开始任务" });
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
    selectEditorNode(node.title);
    expect(
      screen.getByRole("switch", { name: `${node.title}：必须由人决定` }),
    ).toBeDisabled();
    const reviewer = screen.getByRole("switch", {
      name: `${node.title}：独立审核`,
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
  selectEditorNode("第二步计算");
  fireEvent.click(screen.getByText("算子输入来源（资料角色或上游输出）"));
  const binding = screen.getByRole("textbox", {
    name: "第二步计算：算子输入来源",
  });
  expect(binding).toHaveValue(
    JSON.stringify({ image: { nodeId: "first", outputKey: "ndvi" } }, null, 2),
  );
  selectEditorNode("第一步计算");
  fireEvent.change(openNodeIdentity(), {
    target: { value: "source_calc" },
  });
  selectEditorNode("第二步计算");
  fireEvent.click(screen.getByText("算子输入来源（资料角色或上游输出）"));
  expect(
    screen.getByRole("textbox", { name: "第二步计算：算子输入来源" }),
  ).toHaveValue(
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
  const ai = screen.getByRole("switch", { name: "分析项目资料：独立审核" });
  expect(ai).toBeEnabled();
  fireEvent.click(ai);
  expect(ai).toBeChecked();
  const human = screen.getByRole("switch", {
    name: "分析项目资料：必须由人决定",
  });
  expect(human).toBeChecked();
  expect(human).toBeDisabled();
});

it("preserves a human-only node's revision limit while independent review is toggled", async () => {
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
  const ai = screen.getByRole("switch", { name: "分析项目资料：独立审核" });
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

it("lets a researcher create and edit definitions when the server grants authoring", async () => {
  const localDetail = { ...researchDetail, canManage: true };
  vi.mocked(businessFlowsApi.list).mockResolvedValue({
    items: [summary(researchFlow, researchVersion)],
    canManage: true,
  });
  vi.mocked(businessFlowsApi.detail).mockResolvedValue(localDetail);
  vi.spyOn(computeApi, "algorithms").mockResolvedValue({ items: [], total: 0 });
  const create = vi
    .spyOn(businessFlowsApi, "create")
    .mockResolvedValue(localDetail);
  const publish = vi
    .spyOn(businessFlowsApi, "publish")
    .mockResolvedValue(localDetail);
  show();
  fireEvent.click(await screen.findByRole("button", { name: /新建业务流/ }));
  const createDialog = await screen.findByRole("dialog");
  const fields = within(createDialog);
  fireEvent.change(fields.getByRole("textbox", { name: /流程名称/ }), {
    target: { value: "科研流程" },
  });
  fireEvent.change(fields.getByRole("textbox", { name: /流程编码/ }), {
    target: { value: "research-example" },
  });
  fireEvent.click(fields.getByRole("radio", { name: "科研目的" }));
  fireEvent.change(
    fields.getByRole("textbox", { name: "科研目的与判断依据" }),
    {
      target: {
        value: "核对样地资料是否能用于比较不同年份，结合实际抽样口径判断。",
      },
    },
  );
  fireEvent.click(fields.getByRole("radio", { name: "资料与交付" }));
  fireEvent.change(fields.getByRole("textbox", { name: "交付要求" }), {
    target: { value: "跨年可比性核查清单" },
  });
  fireEvent.click(fields.getByRole("radio", { name: "节点设计" }));
  for (const [name, purpose, instruction] of [
    ["分析项目资料", "核对两年的抽样口径。", "比较样地编号、时间和采样间距。"],
    [
      "整理科研成果",
      "确定可以纳入跨年对比的样地。",
      "交付可比样地及其源记录引用。",
    ],
  ]) {
    fireEvent.click(
      fields.getByRole("button", {
        name: (label) => label.startsWith(`${name}，`),
      }),
    );
    fireEvent.change(fields.getByRole("textbox", { name: "节点目的" }), {
      target: { value: purpose },
    });
    fireEvent.change(fields.getByRole("textbox", { name: "判断与交付" }), {
      target: { value: instruction },
    });
  }
  fireEvent.click(fields.getByRole("button", { name: "保存并发布" }));
  await waitFor(() => expect(create).toHaveBeenCalledOnce());
  expect(create.mock.calls[0]?.[0].definition.schemaVersion).toBe(2);
  expect(create.mock.calls[0]?.[0].definition.executionMode).toBeUndefined();
  await waitFor(() => expect(createDialog).not.toBeVisible());

  fireEvent.click(
    await screen.findByRole("button", { name: "编辑业务流", exact: true }),
  );
  const editor = within(await screen.findByRole("dialog"));
  const instruction = "核对输入资料，依据实际结果说明适用范围。";
  fireEvent.change(editor.getByRole("textbox", { name: "判断与交付" }), {
    target: { value: instruction },
  });
  fireEvent.click(editor.getByRole("button", { name: "保存并发布" }));
  await waitFor(() => expect(publish).toHaveBeenCalledOnce());
  expect(publish.mock.calls[0]?.[1].definition.nodes[0]?.instruction).toBe(
    instruction,
  );
});

it("shows shared availability and keeps shared definitions readonly in a private project", async () => {
  const shared = { ...researchFlow, projectId: 1 };
  vi.mocked(businessFlowsApi.list).mockResolvedValue({
    items: [summary(shared, researchVersion)],
    canManage: true,
  });
  vi.mocked(businessFlowsApi.detail).mockResolvedValue({
    ...researchDetail,
    flow: shared,
    canManage: false,
  });
  show();
  await screen.findByRole("heading", { name: shared.name });
  expect(screen.getByText("所有项目可用")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "编辑业务流" }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "开始业务流", exact: true }),
  );
  const location = JSON.parse(screen.getByLabelText("当前导航").textContent!);
  expect(location.search).toContain("projectTagId=3");
});

it("drops the previous project's selected flow when the project boundary remounts", async () => {
  const body = () => (
    <>
      <style>{platformStyles}</style>
      <App>
        <MemoryRouter
          initialEntries={["/business-flows?flow=1&projectTagId=3"]}
        >
          <BusinessFlowsPage key={session.project} />
          <Location />
        </MemoryRouter>
      </App>
    </>
  );
  const view = render(body());
  await screen.findByRole("heading", { name: geologyFlow.name });
  const previousDetailCalls = vi.mocked(businessFlowsApi.detail).mock.calls
    .length;
  vi.mocked(businessFlowsApi.list).mockResolvedValue({
    items: [summary(researchFlow, researchVersion)],
    canManage: false,
  });
  session.project = "4";
  view.rerender(body());
  await screen.findByRole("heading", { name: researchFlow.name });
  expect(
    vi
      .mocked(businessFlowsApi.detail)
      .mock.calls.slice(previousDetailCalls)
      .map((call) => call[0]),
  ).toEqual([researchFlow.id]);
  expect(screen.getByLabelText("当前导航").textContent).not.toContain("flow=1");
  expect(screen.queryByText("业务流暂时无法打开")).not.toBeInTheDocument();
});
