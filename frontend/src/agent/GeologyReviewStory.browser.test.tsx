import { App } from "antd";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import type {
  AgentWorkflow,
  AgentWorkflowStep,
} from "../api/generated/types.gen";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import GeologyReviewStory from "./GeologyReviewStory";
import WorkflowResults from "./WorkflowResults";
import WorkflowPanel from "./WorkflowPanel";
import ResearchIntentCard from "./ResearchIntentCard";
import { computeRun } from "./computeFlow.testFixtures";
import { researchDemoLaunch } from "./researchDemoLaunch";
import platformStyles from "../styles.css?inline";
import agentStyles from "./agent.css?inline";
import storyStyles from "./geology-review-story.css?inline";
import { workflowReport } from "./workflowReport.testFixtures";

const decision = {
  problem: "地图内部空白是否漏填？",
  findings: ["地图内发现 240 平方米的未分类空白，被同一地质单元包围。"],
  judgement: "制图范围完整，专家规则的适用条件成立，建议填补这块漏填。",
  algorithmReason: "检查完整制图范围、围合类别与例外条件，再按批准范围填补。",
  resultSummary: "检查返回一处可修正问题。",
  uncertainties: [],
  nextAction: "geology-map-correct",
  evidenceRefs: [
    {
      kind: "knowledge" as const,
      id: "52",
      title: "完整制图范围的内部漏填检查",
      revision: 2,
    },
  ],
  modelMode: "real" as const,
  modelName: "Qwen",
};
const step = (
  id: number,
  kind: string,
  message: string,
  extra: Partial<AgentWorkflowStep> = {},
): AgentWorkflowStep => ({
  id,
  sequence: id,
  kind,
  status: "succeeded",
  message,
  action: {},
  inputRefs: {},
  outputRefs: {},
  metrics: {},
  computeTaskId: "",
  errorCode: "",
  startedAt: "",
  finishedAt: "",
  ...extra,
});
const polygon = {
  type: "Polygon" as const,
  coordinates: [
    [
      [99, 35],
      [99.002, 35],
      [99.002, 35.001],
      [99, 35.001],
      [99, 35],
    ],
  ],
};
function fixture(): AgentWorkflow {
  return {
    id: "map-review-actual",
    projectId: 3,
    workflowType: "geology_map_review",
    goal: "检查待提交地质图",
    model: "qwen",
    status: "waiting_approval",
    detail: "请批准要修正的范围",
    currentStep: "review_modifications",
    iteration: 3,
    operatorSteps: 1,
    maxIterations: 8,
    maxOperatorSteps: 12,
    executeOperators: true,
    resourceIds: [101, 102, 103],
    algorithmVersionId: null,
    parameters: {},
    resultIds: [],
    runtime: "worker",
    createdAt: "",
    updatedAt: "",
    importResults: true,
    resultResourceIds: [],
    planHash: "current-plan",
    plan: {
      phase: "review_modifications",
      inputs: { initial_map: 101, coverage: 102, rules: 103 },
      inputNames: { initial_map: "待检查地质图" },
      stages: [{ name: "check" }, { name: "edit" }],
    },
    evidence: [
      {
        id: 52,
        revision: 2,
        title: "完整制图范围的内部漏填检查",
        statement:
          "完整覆盖且内部空白被同一单元包围时，在核对水体及未调查区例外后可提出填补建议。",
        conditions: ["制图范围完整覆盖", "无水体或未调查区例外"],
        sources: [
          {
            title: "项目整理规则",
            locator: "规则说明第 2 条",
            excerpt: "核对完整覆盖和例外条件。",
          },
        ],
      },
      {
        id: 53,
        revision: 1,
        title: "八宝山组地层时代",
        statement: "本例对应地区的八宝山组时代定义为晚三叠世。",
        conditions: ["地层名称及地区符合条目范围"],
        sources: [
          { title: "测试知识样本", locator: "八宝山组条目（界面测试夹具）" },
        ],
      },
    ],
    steps: [
      step(
        1,
        "search_expert_knowledge",
        "已检索到完整覆盖与内部漏填的适用规则。",
      ),
      step(2, "analysis_decision", "选择检查地图", {
        decision: {
          ...decision,
          findings: [],
          nextAction: "geology-map-check",
        },
      }),
      step(3, "analysis_decision", "形成建议", { decision }),
    ],
    modificationReview: {
      proposalHash: "proposal-current",
      approvedSuggestionIds: [],
      suggestions: [
        {
          id: "suggestion-gap",
          kind: "fill_gap",
          featureId: "plot-12",
          title: "填补内部漏填",
          currentState: "未分类空白",
          suggestedState: "八宝山组",
          reason:
            "空白被八宝山组完全包围，且当前资料排除了水体与未调查区例外。",
          areaM2: 240,
          ruleId: "coverage-rule",
          knowledgeRefs: [
            { id: 52, revision: 2, title: "完整制图范围的内部漏填检查" },
          ],
          preview: polygon,
          bounds: [99, 35, 99.002, 35.001],
        },
        {
          id: "suggestion-age",
          kind: "set_age",
          featureId: "plot-18",
          title: "更新地层时代",
          currentState: "早白垩世",
          suggestedState: "晚三叠世",
          reason: "地区与地层名称符合本条知识适用范围，时代属性与定义不一致。",
          areaM2: 3600,
          ruleId: "age-rule",
          knowledgeRefs: [{ id: 53, revision: 1, title: "八宝山组地层时代" }],
          preview: polygon,
          bounds: [99, 35, 99.002, 35.001],
        },
      ],
    },
  };
}
function RoutePosition() {
  const location = useLocation();
  return (
    <output aria-label="当前页面路径">
      {location.pathname + location.search}
    </output>
  );
}

function show(workflow = fixture(), review = vi.fn()) {
  const view = render(
    <App>
      <style>{platformStyles + agentStyles + storyStyles}</style>
      <MemoryRouter>
        <RoutePosition />
        <WorkflowResults
          compact
          workflow={workflow}
          onReview={review}
          onConfirm={vi.fn()}
        />
      </MemoryRouter>
    </App>,
  );
  return { ...view, review };
}
beforeEach(() => vi.restoreAllMocks());

it("直接展示本次具体知识修订和实际算法版本，不把待执行工具写成完成", () => {
  const workflow = fixture();
  workflow.plan.algorithms = {
    "geology-map-check": {
      name: "地质成果智能检查",
      manifest: { version: "1.0.1" },
    },
    "geology-map-correct": {
      name: "地质成果受约束修正",
      manifest: { version: "1.0.2" },
    },
  };
  workflow.plan.stages = [
    {
      name: "check",
      identifier: "geology-map-check",
      taskId: "actual-check",
      status: "succeeded",
    },
    { name: "edit", identifier: "geology-map-correct", status: "pending" },
  ];
  show(workflow);
  const basis = within(screen.getByLabelText("本次知识与算法"));
  expect(basis.getByText("完整制图范围的内部漏填检查（修订 2）")).toBeVisible();
  expect(
    basis.getByText("检查：地质成果智能检查 1.0.1 / 已实际执行"),
  ).toBeVisible();
  expect(
    basis.getByText("修正：地质成果受约束修正 1.0.2 / 尚未执行"),
  ).toBeVisible();
});

it.each(["no_changes", "requires_evidence"])(
  "仅检查结论%s保留原图入口，不显示不存在的修正图或复核完成",
  (kind) => {
    const workflow = fixture();
    workflow.status = "succeeded";
    workflow.modificationReview = undefined;
    workflow.resultResourceIds = [900];
    workflow.plan.stages = [
      {
        name: "check",
        outputs: [{ key: "issues", kind: "table", resourceId: 900 }],
      },
    ];
    workflow.plan.reviewOutcome = { kind, checkTaskId: "actual-check" };
    workflow.steps.push(
      step(4, "analysis_decision", "检查完成", {
        decision: {
          ...decision,
          nextAction: "finish",
          judgement: "原图保持不变",
          resultSummary: "检查结果已读取",
        },
      }),
    );
    vi.spyOn(agentApi, "prepareWorkflowReport").mockResolvedValue(
      workflowReport({ label: "检查报告" }),
    );
    show(workflow);
    expect(
      screen.getByText(
        kind === "no_changes"
          ? "检查已完成，未修改地图"
          : "检查已完成，待补充证据",
      ),
    ).toBeVisible();
    expect(screen.queryByText("复核完成")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "查看待检查地质图与修正后地质图" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "查看待检查地质图" }),
    ).toHaveAttribute("href", "/map?resourceId=101&projectTagId=3");
    expect(
      screen.getByRole("link", { name: "在地理工作台查看待检查图" }),
    ).toHaveAttribute("href", "/map?resourceId=101&projectTagId=3");
    expect(
      screen.queryByRole("link", { name: "打开独立对比页" }),
    ).not.toBeInTheDocument();
  },
);

it("仅批准明确选中的建议，保存审核意见而不走通用确认", async () => {
  const { review } = show();
  expect(
    screen.getByRole("button", { name: "批准选中的建议并修正" }),
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "确认执行" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText("等待用户批准", {
      selector: ".geology-story-current > strong",
    }),
  ).toBeVisible();
  expect(
    screen
      .getByRole("img", { name: "填补内部漏填的修改范围" })
      .querySelector("path")
      ?.getAttribute("d"),
  ).toContain("M");
  fireEvent.click(screen.getByRole("checkbox", { name: "填补内部漏填" }));
  fireEvent.change(screen.getByRole("textbox", { name: "修改建议审核意见" }), {
    target: { value: "仅批准漏填，时代问题继续核实" },
  });
  fireEvent.click(screen.getByRole("button", { name: "批准选中的建议并修正" }));
  expect(review).not.toHaveBeenCalled();
  fireEvent.click(await screen.findByRole("button", { name: "批准并修正" }));
  await waitFor(() =>
    expect(review).toHaveBeenCalledWith(
      "approve",
      "仅批准漏填，时代问题继续核实",
      ["suggestion-gap"],
    ),
  );
});

it("拒绝需要确认，查看知识来源与地图位置不会执行修改", async () => {
  const { review } = show();
  const source = screen.getAllByText(/专家知识 \/ 完整制图范围/)[0]!;
  fireEvent.click(source);
  fireEvent.click(
    screen.getAllByText("完整制图范围的内部漏填检查 / 版本 2")[0]!,
  );
  await waitFor(() =>
    expect(screen.getByText("规则说明第 2 条", { exact: false })).toBeVisible(),
  );
  expect(
    screen
      .getAllByRole("link", { name: "在地图上查看位置" })[0]
      ?.getAttribute("href"),
  ).toContain("geologyReview=map-review-actual&suggestion=suggestion-gap");
  // The map opens in a new tab; the agent page stays where it is.
  const locationLink = screen.getAllByRole("link", {
    name: "在地图上查看位置",
  })[0]!;
  expect(locationLink).toHaveAttribute("target", "_blank");
  const pathBefore = screen.getByLabelText("当前页面路径").textContent;
  fireEvent.click(locationLink);
  expect(screen.getByLabelText("当前页面路径")).toHaveTextContent(
    pathBefore ?? "",
  );
  expect(review).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "拒绝建议" }));
  expect(review).not.toHaveBeenCalled();
  fireEvent.click(await screen.findByRole("button", { name: "确认拒绝" }));
  await waitFor(() =>
    expect(review).toHaveBeenCalledWith("reject", "拒绝本次修改建议"),
  );
});

it("建议哈希变化后清除旧选择，刷新后恢复实际批准记录", () => {
  const { rerender, review } = show();
  fireEvent.click(screen.getByRole("checkbox", { name: "填补内部漏填" }));
  const next = fixture();
  next.modificationReview!.proposalHash = "changed-proposal";
  const renderWorkflow = (value: AgentWorkflow) => (
    <App>
      <style>{platformStyles + agentStyles + storyStyles}</style>
      <MemoryRouter>
        <WorkflowResults compact workflow={value} onReview={review} />
      </MemoryRouter>
    </App>
  );
  rerender(renderWorkflow(next));
  expect(
    screen.getByRole("checkbox", { name: "填补内部漏填" }),
  ).not.toBeChecked();
  expect(
    screen.getByRole("button", { name: "批准选中的建议并修正" }),
  ).toBeDisabled();
  next.status = "paused";
  next.modificationReview!.approvedSuggestionIds = ["suggestion-gap"];
  rerender(renderWorkflow(next));
  expect(screen.getByText("已批准")).toBeVisible();
  expect(screen.getByText("未批准")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "批准选中的建议并修正" }),
  ).not.toBeInTheDocument();
});

it("复核解释来自实际模型结果，更换问题位置会更新范围预览", () => {
  const next = fixture();
  next.status = "succeeded";
  next.steps.push(
    step(4, "analysis_decision", "复核完成", {
      decision: {
        ...decision,
        nextAction: "finish",
        resultSummary:
          "240 平方米内部漏填已补齐；未批准的时代问题仍需继续核实。",
      },
    }),
  );
  const view = render(
    <App>
      <MemoryRouter>
        <RoutePosition />
        <GeologyReviewStory workflow={next} />
      </MemoryRouter>
    </App>,
  );
  expect(
    screen.getByText(
      "240 平方米内部漏填已补齐；未批准的时代问题仍需继续核实。",
    ),
  ).toBeVisible();
  const original = screen
    .getByRole("img", { name: "填补内部漏填的修改范围" })
    .querySelector("path")
    ?.getAttribute("d");
  next.modificationReview!.suggestions[0]!.preview = {
    type: "Polygon",
    coordinates: [
      [
        [98, 34],
        [98.001, 34],
        [98.001, 34.003],
        [98, 34.003],
        [98, 34],
      ],
    ],
  };
  view.rerender(
    <App>
      <MemoryRouter>
        <RoutePosition />
        <GeologyReviewStory workflow={next} />
      </MemoryRouter>
    </App>,
  );
  expect(
    screen
      .getByRole("img", { name: "填补内部漏填的修改范围" })
      .querySelector("path")
      ?.getAttribute("d"),
  ).not.toBe(original);
  expect(
    screen
      .getByRole("link", { name: "查看待检查地质图与修正后地质图" })
      .getAttribute("href"),
  ).toBe("/map?geologyReview=map-review-actual&projectTagId=3");
  const compareLink = screen.getByRole("link", {
    name: "查看待检查地质图与修正后地质图",
  });
  expect(
    screen.queryByRole("link", { name: "打开独立对比页" }),
  ).not.toBeInTheDocument();
  expect(compareLink).toHaveAttribute("target", "_blank");
  const pathBefore = screen.getByLabelText("当前页面路径").textContent;
  fireEvent.click(compareLink);
  expect(screen.getByLabelText("当前页面路径")).toHaveTextContent(
    pathBefore ?? "",
  );
});

it.each([1200, 390])("在 %s 像素下保留紧凑审核和真实范围", async (width) => {
  await page.viewport(width, 1000);
  try {
    show();
    const story = screen.getByLabelText("地质成果检查与修正");
    expect(story.scrollWidth).toBeLessThanOrEqual(story.clientWidth + 1);
    expect(story.getBoundingClientRect().right).toBeLessThanOrEqual(width);
    expect(within(story).getByText("晚三叠世")).toBeVisible();
    await page.screenshot({
      path: `../../test-results/geology-review-${width}.png`,
      animations: "disabled",
      fullPage: true,
    });
    screen
      .getByRole("button", { name: "批准选中的建议并修正" })
      .scrollIntoView({ block: "center" });
    await page.screenshot({
      path: `../../test-results/geology-review-approval-${width}.png`,
      animations: "disabled",
      fullPage: true,
    });
  } finally {
    await page.viewport(1600, 900);
  }
});

it("MH-workflow表单用角色明确选择新场景，并把选中建议透传API", async () => {
  const saved = { ...fixture(), projectId: 1 };
  sessionStorage.setItem("workflow-session:80:1", saved.workflowType);
  sessionStorage.setItem(
    `workflow-session:80:1:${saved.workflowType}`,
    saved.id,
  );
  vi.spyOn(agentApi, "researchDemoSummaries").mockResolvedValue({
    items: [
      {
        scenario: "geology_map_review",
        projectId: 1,
        projectName: "公开",
        title: "地质成果智能检查与修正",
      },
    ],
  });
  vi.spyOn(agentApi, "researchDemos").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "workflowHistory").mockResolvedValue({
    items: [saved],
    total: 1,
    offset: 0,
    limit: 30,
    hasMore: false,
  });
  vi.spyOn(agentApi, "bootstrap").mockResolvedValue({
    models: [],
    knowledgeDomains: [],
  } as never);
  vi.spyOn(agentApi, "resources").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(computeApi, "algorithms").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(computeApi, "inputs").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(agentApi, "workflows").mockResolvedValue({
    items: [saved],
    total: 1,
  });
  const confirm = vi
    .spyOn(agentApi, "confirmWorkflow")
    .mockResolvedValue({ ...saved, status: "queued" });
  vi.spyOn(agentApi, "workflow")
    .mockResolvedValueOnce(saved)
    .mockResolvedValue({
      ...saved,
      status: "queued",
    });
  render(
    <App>
      <MemoryRouter>
        <WorkflowPanel model="qwen" resourceIds={[]} userId={80} embedded />
      </MemoryRouter>
    </App>,
  );
  expect(
    await screen.findByRole("combobox", { name: "待检查地质图" }),
  ).toBeVisible();
  expect(screen.getByRole("combobox", { name: "制图范围" })).toBeVisible();
  expect(screen.getByRole("combobox", { name: "专家规则" })).toBeVisible();
  fireEvent.click(screen.getByRole("checkbox", { name: "更新地层时代" }));
  fireEvent.click(screen.getByRole("button", { name: "批准选中的建议并修正" }));
  fireEvent.click(await screen.findByRole("button", { name: "批准并修正" }));
  await waitFor(() =>
    expect(confirm).toHaveBeenCalledWith(saved.id, saved.planHash, {
      decision: "approve",
      feedback: "",
      selectedSuggestionIds: ["suggestion-age"],
    }),
  );
});

it("自然聊天中的建议审核传递当前计划和精确选中范围", async () => {
  const saved = fixture();
  const run = {
    ...computeRun(),
    researchIntent: {
      originRunId: 8,
      revision: "current-intent",
      scenario: "geology_map_review" as const,
      status: "waiting_approval" as const,
      goal: "检查待提交地质图",
      message: "等待批准建议",
      questions: [],
      inputs: { initial_map: 101, coverage: 102, rules: 103 },
      parameters: {},
      workflowId: saved.id,
      inputSummary: [],
    },
  };
  vi.spyOn(agentApi, "workflow").mockResolvedValue(saved);
  vi.spyOn(agentApi, "poll").mockResolvedValue({ run, events: [], cursor: 0 });
  const confirm = vi
    .spyOn(agentApi, "confirmWorkflow")
    .mockResolvedValue({ ...saved, status: "queued" });
  render(
    <App>
      <MemoryRouter>
        <ResearchIntentCard run={run} onChanged={vi.fn()} />
      </MemoryRouter>
    </App>,
  );
  fireEvent.click(
    await screen.findByRole("checkbox", { name: "填补内部漏填" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "批准选中的建议并修正" }));
  fireEvent.click(await screen.findByRole("button", { name: "批准并修正" }));
  await waitFor(() =>
    expect(confirm).toHaveBeenCalledWith(saved.id, saved.planHash, {
      decision: "approve",
      feedback: "",
      selectedSuggestionIds: ["suggestion-gap"],
    }),
  );
  expect(
    researchDemoLaunch(
      {
        scenario: "geology_map_review",
        projectId: 3,
        prompt: "检查待检查地质图",
        token: "launch-review",
      },
      "3",
    )?.scenario,
  ).toBe("geology_map_review");
});
