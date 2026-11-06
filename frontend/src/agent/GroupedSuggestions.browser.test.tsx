import { App } from "antd";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { reviewWorkflow } from "../map/geologyReview.testFixtures";
import MultiElementStory from "./MultiElementStory";
import GenericWorkflowUploads from "./GenericWorkflowUploads";

const { api } = vi.hoisted(() => ({
  api: {
    workflowUploads: vi.fn().mockResolvedValue({ items: [] }),
    workflowCatalogResources: vi.fn().mockResolvedValue({
      items: [1, 2, 3].map((id) => ({
        id,
        name: `资料 ${id}`,
        dataType: "vector",
        createdAt: "2026-11-04",
        directoryId: null,
      })),
      total: 3,
      page: 1,
      pageSize: 20,
      directories: [],
    }),
    addWorkflowCatalogReferences: vi.fn().mockResolvedValue({ items: [] }),
    recognizeWorkflowRoles: vi
      .fn()
      .mockResolvedValue({ items: [], questions: [] }),
  },
}));
vi.mock("../api/agent", () => ({ agentApi: api }));

it("组摘要按原因计数，全量候选仅经用户勾选纳入，确认分别显示两种批准数量", async () => {
  const workflow = reviewWorkflow();
  workflow.workflowType = "geology_generic";
  const first = workflow.modificationReview!.suggestions[0]!;
  const ordinary = {
    ...first,
    id: "model-one",
    kind: "multi_element" as const,
    element: "lithology" as const,
    status: "suggested" as const,
    action: "remove",
  };
  const held = Array.from({ length: 11 }, (_, index) => ({
    ...ordinary,
    id: `held-${index}`,
    featureId: `H${index}`,
    status: index < 8 ? ("review" as const) : ("exception" as const),
    candidateAction: "remove",
    reason: `对象H${index}独有的完整核查原因，不应拼接到组摘要`,
  }));
  workflow.modificationReview!.suggestions = [ordinary, ...held];
  workflow.plan.reviewIndex = {
    total: 12,
    suggestedIds: [ordinary.id],
    candidateIds: held.map((item) => item.id),
    groups: [
      {
        element: "lithology",
        ruleId: first.ruleId,
        action: null,
        held: true,
        count: 11,
        ids: held.map((item) => item.id),
        reasons: {
          "置信度0.6–0.8，需专家裁定": 8,
          "置信度≥0.8，规则例外候选": 3,
        },
      },
    ],
  };
  const review = vi.fn();
  render(
    <App>
      <MemoryRouter>
        <MultiElementStory workflow={workflow} onReview={review} />
      </MemoryRouter>
    </App>,
  );
  expect(screen.getByText(/已选择 1/)).toBeVisible();
  const all = screen.getByRole("checkbox", {
    name: "全部待裁定与例外按候选处置",
  });
  expect(all).not.toBeChecked();
  fireEvent.click(all);
  expect(screen.getByText(/已选择 12/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "批准所选操作并继续" }));
  await waitFor(() =>
    expect(screen.getByText(/有效建议 1 项、用户裁定 11 项/)).toBeVisible(),
  );
  expect(review).toHaveBeenCalledOnce();
  expect(review.mock.calls[0]![2]).toHaveLength(12);
  fireEvent.click(all);
  expect(screen.getByText(/已选择 1/)).toBeVisible();
  fireEvent.click(
    screen.getByText(/待裁定与例外（共/, { selector: "summary" }),
  );
  fireEvent.click(
    screen.getByText(new RegExp(`岩性 / ${first.ruleId} · 11 个对象`), {
      selector: "summary",
    }),
  );
  expect(screen.getByText(/置信度0.6–0.8，需专家裁定.*8\s*处/)).toBeVisible();
  expect(screen.getByText(/置信度≥0.8，规则例外候选.*3\s*处/)).toBeVisible();
  for (const node of await screen.findAllByText(held[0]!.reason))
    expect(node).not.toBeVisible();
  fireEvent.click(
    screen.getByText(/H0 \/ 需地质判断/, { selector: "summary" }),
  );
  expect(
    screen.getAllByText(held[0]!.reason).some((node) => {
      const box = node.getBoundingClientRect();
      return box.width > 0 && box.height > 0;
    }),
  ).toBe(true);
});

it("模型建议默认选择，待裁定候选仅在用户明确选择后批准", async () => {
  const workflow = reviewWorkflow();
  workflow.workflowType = "geology_generic";
  const first = workflow.modificationReview!.suggestions[0]!;
  workflow.modificationReview!.suggestions = [
    {
      ...first,
      id: "ordinary",
      kind: "multi_element",
      element: "lithology",
      status: "suggested",
      action: "set_code",
    },
    {
      ...first,
      id: "held",
      featureId: "H1",
      kind: "multi_element",
      element: "lithology",
      status: "exception",
      ruleId: "L-02",
      action: "reclassify",
      suggestedState: "reclassify D₁γ",
      candidateAction: "reclassify",
      candidateTargetCode: "D₁γ",
    },
  ];
  const review = vi.fn();
  const view = render(
    <App>
      <MemoryRouter>
        <MultiElementStory workflow={workflow} onReview={review} />
      </MemoryRouter>
    </App>,
  );
  expect(screen.getByText(/已选择 1/)).toBeVisible();
  expect(
    screen.getByRole("checkbox", { name: /全部待裁定与例外按候选处置/ }),
  ).not.toBeChecked();
  fireEvent.click(
    screen.getByText(/待裁定与例外（共/, { selector: "summary" }),
  );
  fireEvent.click(
    screen.getByText(/岩性 \/ L-02 · 1 个对象/, { selector: "summary" }),
  );
  fireEvent.click(
    await screen.findByText(/H1 \/ 规则例外候选/, { selector: "summary" }),
  );
  const retained = screen.getByText(/H1 \/ 规则例外候选/).closest("details")!;
  fireEvent.mouseDown(
    screen.getByRole("combobox", { name: "L-02组待裁定处置" }),
  );
  fireEvent.click(await screen.findByText("按本组候选处置：重分类为 D₁γ"));
  expect(screen.getByText(/已选择 2/)).toBeVisible();
  view.rerender(
    <App>
      <MemoryRouter>
        <MultiElementStory
          workflow={{
            ...workflow,
            updatedAt: "next-poll",
            planHash: "next-stage",
          }}
          onReview={review}
        />
      </MemoryRouter>
    </App>,
  );
  expect(retained.open).toBe(true);
  expect(screen.getByText(/已选择 2/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "批准所选操作并继续" }));
  await waitFor(() =>
    expect(review).toHaveBeenCalledWith("approve", "", ["ordinary", "held"]),
  );
});

it("按组批准超过30对象，展开后可取消个别对象，例外不被纳入", async () => {
  const workflow = reviewWorkflow();
  workflow.workflowType = "geology_generic";
  const first = workflow.modificationReview!.suggestions[0]!;
  workflow.modificationReview!.suggestions = [
    ...Array.from({ length: 70 }, (_, index) => ({
      ...first,
      id: `object-${index}`,
      featureId: `F${index}`,
      groupId: "group-1",
      kind: "multi_element" as const,
      element: "lithology" as const,
      ruleId: "L-01",
      action: "reclassify",
      status: "suggested" as const,
    })),
    {
      ...first,
      id: "protected",
      groupId: "review-1",
      kind: "multi_element",
      element: "lithology",
      status: "exception",
    },
  ];
  const review = vi.fn();
  render(
    <App>
      <MemoryRouter>
        <MultiElementStory workflow={workflow} onReview={review} />
      </MemoryRouter>
    </App>,
  );
  expect(
    screen.getByText(/70 个对象/, { selector: "summary" }).closest("details"),
  ).not.toHaveAttribute("open");
  expect(await screen.findByLabelText("整组批准（70 个对象）")).toBeChecked();
  fireEvent.click(screen.getByText(/70 个对象/, { selector: "summary" }));
  await waitFor(() =>
    expect(document.querySelectorAll(".multi-element-suggestion")).toHaveLength(
      50,
    ),
  );
  document
    .querySelectorAll<HTMLDetailsElement>(".multi-element-suggestion")
    .forEach((item) => {
      item.open = true;
    });
  const individual = await screen.findAllByRole("checkbox", {
    name: /批准此对象/,
  });
  expect(individual).toHaveLength(50);
  fireEvent.click(individual[0]!);
  fireEvent.click(screen.getByRole("button", { name: /查看更多对象/ }));
  document
    .querySelectorAll<HTMLDetailsElement>(".multi-element-suggestion")
    .forEach((item) => {
      item.open = true;
    });
  expect(screen.getAllByRole("checkbox", { name: /批准此对象/ })).toHaveLength(
    70,
  );
  fireEvent.click(screen.getByRole("button", { name: "批准所选操作并继续" }));
  await waitFor(() => expect(review).toHaveBeenCalled());
  expect(review.mock.calls[0]![2]).toHaveLength(69);
  expect(review.mock.calls[0]![2]).not.toContain("object-0");
  expect(review.mock.calls[0]![2]).not.toContain("protected");
});

it("全部分组待裁定时仍显示组卡片，不提供自动批准", async () => {
  const workflow = reviewWorkflow();
  workflow.workflowType = "geology_generic";
  workflow.modificationReview!.suggestions = [];
  workflow.plan.stages = [
    {
      name: "apply",
      groupDecisions: [
        {
          group_id: "review-only",
          disposition: "review",
          reason: "需要人工核对",
        },
      ],
      results: [
        {
          groups: [
            {
              group_id: "review-only",
              element: "lithology",
              rule_id: "L-01",
              count: 12,
            },
          ],
        },
      ],
    },
  ];
  render(
    <App>
      <MemoryRouter>
        <MultiElementStory workflow={workflow} />
      </MemoryRouter>
    </App>,
  );
  const held = await screen.findByText("待裁定与例外（共 1 组 / 12 个对象）");
  expect(held.closest("details")).not.toHaveAttribute("open");
  fireEvent.click(held);
  expect(screen.getByText(/岩性 \/ L-01 · 12 个对象/)).toBeVisible();
  expect(screen.queryByLabelText(/整组批准/)).not.toBeInTheDocument();
});

it.each([1461, 360])(
  "%ipx 审批先显示合并的可执行组，待裁定与例外默认折叠",
  async (width) => {
    await page.viewport(width, 812);
    const workflow = reviewWorkflow();
    workflow.workflowType = "geology_generic";
    const first = workflow.modificationReview!.suggestions[0]!;
    workflow.modificationReview!.suggestions = Array.from(
      { length: 60 },
      (_, index) => ({
        ...first,
        id: `target-${index}`,
        groupId: `backend-group-${index}`,
        kind: "multi_element",
        element: "lithology",
        ruleId: "L-01",
        action: "reclassify",
        status: "suggested",
        suggestedState: `reclassify ${index % 2 ? "C" : "O"}`,
      }),
    );
    workflow.plan.stages = [
      {
        name: "apply",
        results: [
          {
            groups: Array.from({ length: 20 }, (_, index) => ({
              group_id: `held-${index}`,
              element: "lithology",
              rule_id: "L-02",
              count: 2,
            })),
          },
        ],
        groupDecisions: Array.from({ length: 20 }, (_, index) => ({
          group_id: `held-${index}`,
          disposition: "review",
          reason: "证据不足",
        })),
      },
    ];
    const mounted = render(
      <App>
        <MemoryRouter>
          <MultiElementStory workflow={workflow} onReview={vi.fn()} />
        </MemoryRouter>
      </App>,
    );
    try {
      const executable = await screen.findByText(
        "岩性 / L-01 / 重分类 · 60 个对象",
        { selector: "summary" },
      );
      const held = screen.getByText("待裁定与例外（共 1 组 / 40 个对象）", {
        selector: "summary",
      });
      expect(
        executable.compareDocumentPosition(held) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(executable.closest("details")).not.toHaveAttribute("open");
      expect(held.closest("details")).not.toHaveAttribute("open");
      fireEvent.click(executable);
      await waitFor(() =>
        expect(executable.closest("details")).toHaveAttribute("open"),
      );
      expect(
        screen.getByText("重分类为 O：30 个对象；重分类为 C：30 个对象"),
      ).toBeVisible();
      expect(screen.getByText("整组批准（60 个对象）")).toBeVisible();
      fireEvent.click(executable);
      await waitFor(() =>
        expect(executable.closest("details")).not.toHaveAttribute("open"),
      );
      fireEvent.click(executable);
      await waitFor(() =>
        expect(screen.getByText("整组批准（60 个对象）")).toBeVisible(),
      );
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    } finally {
      mounted.unmount();
      await page.viewport(1600, 900);
    }
  },
);

it("系统数据连续快速鼠标点选不会覆盖之前选项", async () => {
  render(
    <App>
      <GenericWorkflowUploads
        batchId={"a".repeat(32)}
        model="configured"
        inputs={{}}
        onInputsChange={vi.fn()}
      />
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: "选择系统数据" }));
  await waitFor(() => expect(api.workflowCatalogResources).toHaveBeenCalled());
  const input = screen.getByRole("combobox", { name: "选择系统数据资源" });
  fireEvent.mouseDown(input);
  await waitFor(() =>
    expect(document.querySelectorAll(".ant-select-item-option").length).toBe(3),
  );
  const options = [...document.querySelectorAll(".ant-select-item-option")];
  act(() => {
    options.forEach((option) => fireEvent.click(option));
  });
  fireEvent.click(screen.getByRole("button", { name: "加入本次任务" }));
  await waitFor(() =>
    expect(api.addWorkflowCatalogReferences).toHaveBeenCalledWith(
      "a".repeat(32),
      [1, 2, 3],
    ),
  );
});

it("5552对象默认零对象行，展开每次50条，可搜索编号并取消后提交完整集合", async () => {
  const workflow = reviewWorkflow();
  workflow.workflowType = "geology_generic";
  const first = workflow.modificationReview!.suggestions[0]!;
  workflow.modificationReview!.suggestions = Array.from(
    { length: 5552 },
    (_, index) => ({
      ...first,
      id: `object-${index}`,
      featureId: `F${index}`,
      element: "lithology",
      ruleId: "L-01",
      action: "reclassify",
      status: "suggested",
    }),
  );
  const review = vi.fn();
  const mounted = render(
    <App>
      <MemoryRouter>
        <MultiElementStory workflow={workflow} onReview={review} />
      </MemoryRouter>
    </App>,
  );
  expect(
    mounted.container.querySelectorAll(".multi-element-suggestion"),
  ).toHaveLength(0);
  expect(screen.getByLabelText("整组批准（5552 个对象）")).toBeChecked();
  const summary = screen.getByText(/5552 个对象/, { selector: "summary" });
  fireEvent.click(summary);
  await waitFor(() =>
    expect(
      mounted.container.querySelectorAll(".multi-element-suggestion"),
    ).toHaveLength(50),
  );
  fireEvent.change(screen.getByLabelText("搜索对象编号 L-01"), {
    target: { value: "F5551" },
  });
  await waitFor(() =>
    expect(
      mounted.container.querySelectorAll(".multi-element-suggestion"),
    ).toHaveLength(1),
  );
  fireEvent.click(screen.getByText("对象：F5551").closest("summary")!);
  fireEvent.click(screen.getByRole("checkbox", { name: /批准此对象/ }));
  fireEvent.click(summary);
  await waitFor(() =>
    expect(
      mounted.container.querySelectorAll(".multi-element-suggestion"),
    ).toHaveLength(0),
  );
  fireEvent.click(screen.getByRole("button", { name: "批准所选操作并继续" }));
  await waitFor(() => expect(review).toHaveBeenCalled());
  expect(review.mock.calls[0]![2]).toHaveLength(5551);
  expect(review.mock.calls[0]![2]).not.toContain("object-5551");
});
