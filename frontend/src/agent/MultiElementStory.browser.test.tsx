import { App } from "antd";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { reviewWorkflow } from "../map/geologyReview.testFixtures";
import MultiElementStory from "./MultiElementStory";
import storyStyles from "./geology-review-story.css?inline";

export function multiWorkflow() {
  const workflow = reviewWorkflow();
  workflow.workflowType = "geology_multi_element_reasoning";
  workflow.parameters = { segment: "all" };
  workflow.detail = "检查完成，请核对实测依据并批准所选建议";
  workflow.plan.inputs = { lithology: 101, faults: 102 };
  workflow.plan.inputNames = {
    lithology: "海德乌拉模拟识别岩性图",
    faults: "海德乌拉模拟构造图",
  };
  workflow.plan.upstreamVersions = {
    lithology: { resourceId: 101, revision: 2 },
    faults: { resourceId: 102, revision: 1 },
  };
  workflow.modificationReview!.suggestions =
    workflow.modificationReview!.suggestions.map((item, index) => ({
      ...item,
      kind: "multi_element",
      element: index ? "structure" : "lithology",
      action: index ? "review" : "fix_symbol",
      title: index ? "构造线需补影像核实" : "名称与地质代号不一致",
      status: index ? "review" : "suggested",
      observations: { confidence: 0.58, area_km2: 0.2 },
      ruleConditions: ["名称存在于冻结图例别名表"],
      exceptions: ["新单元需专家确认"],
      ruleRefs: [
        {
          id: "L-03",
          version: "1.0.0",
          title: "单元名称与代号一致性",
          knowledgeId: 601,
          revision: 1,
          source: "示范区图例 / 已冻结名称表",
        },
      ],
    }));
  return workflow;
}

it("建议默认收起，展开可核对实测、具体规则和例外，待裁定不被全选", async () => {
  const review = vi.fn();
  const workflow = multiWorkflow();
  workflow.modificationReview!.suggestions[0]!.observations = {
    confidence: 0.58,
    dominant_code: "Tnc²",
    group_areas_m2: { carbonate: 841840.999999, carbonate_interbed: 626545 },
    group_ratios: { carbonate: 0.573310423, carbonate_interbed: 0.426689577 },
    mineral: "方解石化",
  };
  render(
    <App>
      <MemoryRouter>
        <style>{storyStyles}</style>
        <MultiElementStory workflow={workflow} onReview={review} />
      </MemoryRouter>
    </App>,
  );
  fireEvent.click(
    screen.getByText(/个对象/, {
      selector: ".multi-element-suggestion-list > div > details > summary",
    }),
  );
  await screen.findByText("岩性 / 名称与地质代号不一致");
  expect(screen.getByText("岩性 / 名称与地质代号不一致")).toBeVisible();
  const details = screen
    .getByText("岩性 / 名称与地质代号不一致")
    .closest("details")!;
  expect(details).not.toHaveAttribute("open");
  fireEvent.click(details.querySelector("summary")!);
  expect(within(details).getByText("模拟分类置信度")).toBeVisible();
  expect(within(details).getByText("主要重叠地质单元")).toBeVisible();
  expect(
    within(details).getByText("碳酸盐岩：84.18 公顷；含碳酸盐夹层：62.65 公顷"),
  ).toBeVisible();
  expect(
    within(details).getByText("碳酸盐岩：57.33%；含碳酸盐夹层：42.67%"),
  ).toBeVisible();
  expect(
    within(details).getByText("L-03 / 单元名称与代号一致性"),
  ).toBeVisible();
  expect(within(details).getByText("新单元需专家确认")).toBeVisible();
  expect(screen.getByText(/已选择 1/)).toBeVisible();
  expect(
    screen.getByRole("checkbox", { name: "全部待裁定与例外按候选处置" }),
  ).not.toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "批准所选操作并继续" }));
  fireEvent.click(await screen.findByRole("button", { name: "批准并继续" }));
  await waitFor(() =>
    expect(review).toHaveBeenCalledWith("approve", "", ["suggest-gap"]),
  );
  await page.screenshot({
    path: "../../test-results/multi-element-evidence-approval.png",
    animations: "disabled",
  });
});

it("用户可明确不修改并继续，空建议也能继续，不冒充审批", async () => {
  const workflow = multiWorkflow();
  workflow.modificationReview!.suggestions = [];
  const review = vi.fn();
  render(
    <MemoryRouter>
      <MultiElementStory workflow={workflow} onReview={review} />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole("button", { name: "本轮无修改，继续分析" }));
  expect(review).toHaveBeenCalledWith(
    "approve",
    "本轮未形成修改建议，保留数据继续分析",
    [],
  );
});

it("批准卡片说明未采用建议，不自动勾选保留的建议", () => {
  const workflow = multiWorkflow();
  workflow.plan.stages = [
    {
      name: "apply",
      editValidation: {
        discardedCount: 2,
        errors: [
          { index: 2, issue_id: "bad-1", reason: "权重超出范围" },
          { index: 3, issue_id: "bad-2", reason: "权重超出范围" },
        ],
      },
    },
  ];
  const review = vi.fn();
  render(
    <MemoryRouter>
      <MultiElementStory workflow={workflow} onReview={review} />
    </MemoryRouter>,
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "模型另提出 2 项建议因权重超出范围未采用；其余建议仍需逐项人工确认。",
  );
  expect(
    screen.getByRole("checkbox", { name: /全部待裁定与例外按候选处置/ }),
  ).not.toBeChecked();
  expect(review).not.toHaveBeenCalled();
});

it("names an uploaded-data task by its own data and states the missing inputs", () => {
  const workflow = multiWorkflow();
  workflow.workflowType = "geology_generic";
  workflow.plan.missingRoles = ["coverage", "units"];
  render(
    <App>
      <MemoryRouter>
        <MultiElementStory workflow={workflow} onReview={vi.fn()} />
      </MemoryRouter>
    </App>,
  );
  const story = screen.getByLabelText("地质综合推理");
  expect(within(story).getByText("本次资料")).toBeVisible();
  expect(within(story).queryByText("演示案例")).not.toBeInTheDocument();
  expect(
    within(story).getByText(/未提供：研究区范围、填图单元表/),
  ).toBeVisible();
});
