import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type {
  AgentWorkflow,
  AgentFieldMappingReview,
} from "../api/generated/types.gen";
import { reviewWorkflow } from "../map/geologyReview.testFixtures";
import FieldMappingReview from "./FieldMappingReview";
import LogicTaskWorkspace from "./LogicTaskWorkspace";
import { workflowReport } from "./workflowReport.testFixtures";
import "./agent.css";

function task(extra: Partial<AgentWorkflow> = {}): AgentWorkflow {
  return {
    ...reviewWorkflow(true),
    workflowType: "geology_generic",
    status: "succeeded",
    view: "card",
    steps: [],
    evidence: [],
    plan: { phase: "completed", stages: [] },
    taskSummary: {
      sourceCount: 3,
      initialIssueCount: 241,
      executedDispositionCount: 196,
      remainingIssueCount: 142,
      prospectZoneCount: 0,
      retainedIssueCount: 45,
      reviewIssueCount: 36,
      exceptionIssueCount: 9,
      completedCalculations: 5,
      totalCalculations: 5,
    },
    ...extra,
  };
}
function show(workflow = task(), extra = {}) {
  return render(
    <App>
      <MemoryRouter>
        <LogicTaskWorkspace workflow={workflow} {...extra} />
      </MemoryRouter>
    </App>,
  );
}
beforeEach(() => {
  vi.spyOn(agentApi, "workflow").mockImplementation(async () =>
    task({ view: "inspection" }),
  );
  vi.spyOn(agentApi, "prepareWorkflowReport").mockResolvedValue(
    workflowReport(),
  );
  vi.spyOn(computeApi, "task");
});
afterEach(() => vi.restoreAllMocks());

it("完成首屏显示实际结果和四阶段，无预取或重复确认；成果按需读取", async () => {
  const workflow = task();
  show(workflow);
  expect(screen.getAllByRole("tab")).toHaveLength(3);
  expect(
    screen.getByLabelText("四个分析阶段").querySelectorAll("li"),
  ).toHaveLength(4);
  const metrics = within(screen.getByLabelText("实际结果统计"));
  for (const number of ["196", "142", "0"])
    expect(metrics.getByText(number)).toBeVisible();
  expect(screen.getByText("45 条待裁定与例外已保留")).toBeVisible();
  expect(screen.getByRole("link", { name: "查看前后对比" })).toHaveAttribute(
    "target",
    "_blank",
  );
  expect(agentApi.workflow).not.toHaveBeenCalled();
  expect(agentApi.prepareWorkflowReport).not.toHaveBeenCalled();
  expect(computeApi.task).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("tab", { name: "过程与依据" }));
  expect(screen.getByLabelText("分析阶段与依据")).toHaveTextContent(
    "初检返回 241",
  );
  expect(agentApi.workflow).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("tab", { name: "成果" }));
  await waitFor(() =>
    expect(agentApi.prepareWorkflowReport).toHaveBeenCalledWith(workflow.id),
  );
});

it("暂停直接生效，停止位于更多且必须确认；暂停态只有一个继续按钮", async () => {
  const pause = vi.fn(),
    cancel = vi.fn(),
    resume = vi.fn();
  const running = task({
    status: "running",
    plan: { phase: "analyze", stages: [] },
  });
  const mounted = show(running, {
    onPause: pause,
    onCancel: cancel,
    onResume: resume,
  });
  fireEvent.click(screen.getByRole("button", { name: "暂停" }));
  expect(pause).toHaveBeenCalledOnce();
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "更多任务操作" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "停止任务" }));
  expect(cancel).not.toHaveBeenCalled();
  fireEvent.click(
    within(await screen.findByRole("dialog")).getByRole("button", {
      name: "停止任务",
    }),
  );
  expect(cancel).toHaveBeenCalledOnce();
  mounted.rerender(
    <App>
      <MemoryRouter>
        <LogicTaskWorkspace
          workflow={{ ...running, status: "paused" }}
          onResume={resume}
        />
      </MemoryRouter>
    </App>,
  );
  expect(screen.getAllByRole("button", { name: /^继续$/ })).toHaveLength(1);
});

it("字段修改在侧栏完成，切换标签和轮询保留草稿及自动处置选择", async () => {
  const mapping: AgentFieldMappingReview = {
    modelMode: "real",
    confirmed: false,
    questions: [],
    roles: [
      {
        role: "lithology",
        label: "地质图",
        fileName: "本次地质图.zip",
        resourceId: 1,
        fields: ["名称", "地层名称"],
        targets: [
          {
            key: "name",
            label: "名称",
            required: true,
            field: "名称",
            reason: "实际字段取值",
          },
        ],
      },
    ],
  };
  const confirm = vi.fn();
  const workflow = task({
    status: "waiting_approval",
    plan: { phase: "review_mapping", fieldMappingReview: mapping },
  });
  const input = (
    <FieldMappingReview
      workspace
      startAnalysis
      review={mapping}
      busy={false}
      onConfirm={confirm}
    />
  );
  const mounted = show(workflow, { inputReview: input });
  expect(screen.queryByRole("combobox")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "修改地质图字段" }));
  fireEvent.mouseDown(
    await screen.findByRole("combobox", { name: "地质图的名称" }),
  );
  fireEvent.click(
    await screen.findByText("地层名称", {
      selector: ".ant-select-item-option-content",
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "保存对应关系" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /自动执行已核验/ }));
  fireEvent.click(screen.getByRole("tab", { name: "过程与依据" }));
  mounted.rerender(
    <App>
      <MemoryRouter>
        <LogicTaskWorkspace
          workflow={{ ...workflow, updatedAt: "poll" }}
          inputReview={input}
        />
      </MemoryRouter>
    </App>,
  );
  fireEvent.click(screen.getByRole("tab", { name: "概览" }));
  expect(
    screen.getByRole("checkbox", { name: /自动执行已核验/ }),
  ).not.toBeChecked();
  expect(screen.getByText("名称：地层名称")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "确认并开始" }));
  expect(confirm).toHaveBeenCalledExactlyOnceWith(
    { lithology: { name: "地层名称" } },
    false,
  );
});

it("不同详情独立缓存，轮询不打断阅读，切换任务丢弃迟到响应", async () => {
  let resolve: (value: AgentWorkflow) => void = () => {};
  vi.mocked(agentApi.workflow).mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const mounted = show();
  fireEvent.click(screen.getByRole("button", { name: "查看资料与设置" }));
  await waitFor(() => expect(agentApi.workflow).toHaveBeenCalledOnce());
  mounted.rerender(
    <App>
      <MemoryRouter>
        <LogicTaskWorkspace
          workflow={task({ id: "new-task", projectId: 7, goal: "新任务" })}
        />
      </MemoryRouter>
    </App>,
  );
  await act(async () =>
    resolve(task({ view: "inspection", goal: "不应出现的旧资料" })),
  );
  fireEvent.click(screen.getByRole("button", { name: "查看资料与设置" }));
  await waitFor(() => expect(agentApi.workflow).toHaveBeenCalledTimes(2));
  expect(screen.queryByText("不应出现的旧资料")).toBeNull();
});

it("拒绝过期审批响应，只允许读取匹配当前planHash的处置范围", async () => {
  vi.mocked(agentApi.workflow).mockResolvedValue(
    task({ view: "inspection", planHash: "old" }),
  );
  show(
    task({
      status: "waiting_approval",
      planHash: "new",
      plan: { phase: "review_modifications" },
    }),
    { onReview: vi.fn() },
  );
  expect(
    await screen.findByText("处置方案已更新，请读取最新建议后再确认"),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "批准所选操作并继续" }),
  ).toBeNull();
});

it("下载按需校验权限，拒绝时不请求文件", async () => {
  vi.mocked(agentApi.prepareWorkflowReport).mockResolvedValue(
    workflowReport({ canDownload: false }),
  );
  const fetch = vi.spyOn(globalThis, "fetch");
  show();
  fireEvent.click(screen.getByRole("button", { name: "下载报告" }));
  await screen.findByText(/当前账号没有报告下载权限/);
  expect(fetch).not.toHaveBeenCalled();
});

it.each([
  { width: 1200, height: 850 },
  { width: 360, height: 800 },
])("$width px 布局无水平溢出，结果主操作可见", async (viewport) => {
  await page.viewport(viewport.width, viewport.height);
  const mounted = show();
  const workspace = screen.getByRole("region", { name: "工作流进度卡片" });
  expect(workspace.scrollWidth).toBeLessThanOrEqual(workspace.clientWidth);
  expect(screen.getByRole("button", { name: "下载报告" })).toBeVisible();
  await page.screenshot({
    path: `../../test-results/logic-workspace-${viewport.width}.png`,
  });
  mounted.unmount();
});

it("入库失败可重试同一成果，不要求重新分析", () => {
  const retry = vi.fn(),
    restart = vi.fn();
  show(
    task({
      status: "failed",
      detail: "结果入库失败，已保留任务与原结果",
      plan: { phase: "waiting_compute", stages: [] },
    }),
    { onRetryImports: retry, onRestart: restart },
  );
  fireEvent.click(screen.getByRole("button", { name: "重试成果入库" }));
  expect(retry).toHaveBeenCalledOnce();
  expect(restart).not.toHaveBeenCalled();
});
