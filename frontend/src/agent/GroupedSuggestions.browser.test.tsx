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
  fireEvent.click(screen.getByText(/70 个对象/, { selector: "summary" }));
  fireEvent.click(await screen.findByLabelText("整组批准（70 个对象）"));
  const individual = await screen.findAllByRole("checkbox", {
    name: /批准此对象/,
  });
  expect(individual).toHaveLength(50);
  fireEvent.click(individual[0]!);
  fireEvent.click(screen.getByRole("button", { name: /查看更多对象/ }));
  expect(screen.getAllByRole("checkbox", { name: /批准此对象/ })).toHaveLength(
    70,
  );
  fireEvent.click(screen.getByRole("button", { name: "批准所选操作并继续" }));
  fireEvent.click(await screen.findByRole("button", { name: "批准并继续" }));
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
  expect(await screen.findByText(/12 个对象 · 整组待裁定/)).toBeVisible();
  expect(screen.queryByLabelText(/整组批准/)).not.toBeInTheDocument();
});

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
