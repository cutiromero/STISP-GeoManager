import { fireEvent, render, screen, within } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import {
  reviewWorkflow,
  beforeReviewMap,
} from "../map/geologyReview.testFixtures";
import RetainedIssueReview from "./RetainedIssueReview";
const { mapQuery } = vi.hoisted(() => ({ mapQuery: vi.fn() }));
vi.mock("../map/geologyReviewData", async (original) => ({
  ...(await original<typeof import("../map/geologyReviewData")>()),
  queryReviewMap: mapQuery,
}));

function task() {
  const workflow = reviewWorkflow();
  const base = workflow.modificationReview!.suggestions[0]!;
  workflow.workflowType = "geology_generic";
  workflow.plan.retainedReview = {
    active: true,
    automaticSuggestionIds: Array.from({ length: 196 }, (_, n) => `auto-${n}`),
    candidateIds: ["held-1", "held-2"],
  };
  workflow.modificationReview!.suggestions = [
    {
      ...base,
      id: "held-1",
      kind: "multi_element",
      element: "lithology",
      featureId: "F-01",
      ruleId: "L-06",
      status: "review",
      candidateAction: "reclassify",
      candidateTargetCode: "Qp3pal",
      reason: "紧凑度异常，需要核对冲积扇例外",
    },
    {
      ...base,
      id: "held-2",
      kind: "multi_element",
      element: "structure",
      featureId: "F-02",
      ruleId: "S-04",
      status: "exception",
      candidateAction: "exclude",
      reason: "存在例外条件，需明确裁定",
    },
  ];
  workflow.plan.reviewIndex = { total: 2, candidateIds: ["held-1", "held-2"] };
  return workflow;
}

it("核查仅加载当前成果单图，切换对象和勾选不重新请求底图", async () => {
  const workflow = task();
  workflow.plan.inputs = { lithology: 501, faults: 502 };
  mapQuery.mockReset();
  mapQuery.mockImplementation(async (id: number) =>
    id === 501 ? beforeReviewMap : { type: "FeatureCollection", features: [] },
  );
  const view = render(
    <App>
      <MemoryRouter>
        <RetainedIssueReview workflow={workflow} onReview={vi.fn()} />
      </MemoryRouter>
    </App>,
  );
  await screen.findByText("待核查对象（尚未执行）");
  expect(
    view.container.querySelectorAll(".geology-review-map-pair section"),
  ).toHaveLength(1);
  expect(screen.queryByText("本次检查采用的地质资料")).toBeNull();
  expect(screen.getByText("待核查对象（尚未执行）")).toBeVisible();
  expect(
    view.container.querySelectorAll('[data-layer="geological-units"] path')
      .length,
  ).toBeGreaterThan(2);
  expect(mapQuery).toHaveBeenCalledTimes(2);
  expect(mapQuery).toHaveBeenCalledWith(
    501,
    expect.objectContaining({ displayGeometry: true, loadStyle: true }),
  );
  fireEvent.click(screen.getByRole("checkbox", { name: "处置F-01" }));
  fireEvent.click(screen.getAllByRole("button", { name: "F-02" })[0]!);
  expect(mapQuery).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("button", { name: "定位所选对象" })).toBeEnabled();
  expect(
    view.container.querySelector('[data-layer="story-focus"] path'),
  ).not.toBeNull();
});
it("仅展示人工候选，默认全部保留，选择后只提交明确对象", () => {
  const onReview = vi.fn();
  render(
    <App>
      <MemoryRouter>
        <RetainedIssueReview workflow={task()} onReview={onReview} />
      </MemoryRouter>
    </App>,
  );
  expect(screen.getByText(/196 项已核验处置沿用原授权/)).toBeVisible();
  expect(screen.queryByText("auto-0")).toBeNull();
  const first = screen.getByRole("checkbox", { name: "处置F-01" });
  expect(first).not.toBeChecked();
  fireEvent.click(first);
  fireEvent.click(screen.getByRole("button", { name: "执行所选 1 项并继续" }));
  expect(onReview).toHaveBeenCalledExactlyOnceWith(
    "approve",
    "",
    ["held-1"],
    {},
  );
  expect(screen.getByRole("checkbox", { name: "处置F-02" })).not.toBeChecked();
});
it("真实几何可视化并可通过对象名展开依据", () => {
  const view = render(
    <App>
      <MemoryRouter>
        <RetainedIssueReview workflow={task()} readonly />
      </MemoryRouter>
    </App>,
  );
  expect(
    view.container.querySelectorAll("svg [data-feature-id]").length,
  ).toBeGreaterThan(0);
  fireEvent.click(screen.getAllByRole("button", { name: "F-01" })[0]!);
  expect(
    within(screen.getByRole("article", { name: "当前对象依据" })).getByRole(
      "heading",
      { name: "F-01 · L-06" },
    ),
  ).toBeVisible();
  expect(screen.queryByRole("checkbox", { name: "处置F-01" })).toBeNull();
});
it("未选择对象时确认只保留，不产生默认人工批准", () => {
  const onReview = vi.fn();
  render(
    <App>
      <MemoryRouter>
        <RetainedIssueReview workflow={task()} onReview={onReview} />
      </MemoryRouter>
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: "保留未选对象并继续" }));
  expect(onReview).toHaveBeenCalledExactlyOnceWith("approve", "", [], {});
});

it("can select a candidate directly from its mapped evidence", () => {
  const onReview = vi.fn();
  render(
    <App>
      <MemoryRouter>
        <RetainedIssueReview workflow={task()} onReview={onReview} />
      </MemoryRouter>
    </App>,
  );
  fireEvent.click(screen.getAllByRole("button", { name: "F-01" })[0]!);
  fireEvent.click(
    screen.getByRole("checkbox", { name: "选择当前对象的候选处置" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "执行所选 1 项并继续" }));
  expect(onReview).toHaveBeenCalledExactlyOnceWith(
    "approve",
    "",
    ["held-1"],
    {},
  );
});

it("蚀变对象勾选后显示实际候选动作，保留后再选不会沿用静默keep", async () => {
  const workflow = task();
  const item = workflow.modificationReview!.suggestions[0]!;
  Object.assign(item, {
    featureId: "AG-01",
    element: "alteration",
    candidateAction: "exclude",
    candidateTargetCode: "",
    allowedActions: ["keep", "exclude", "downweight"],
  });
  const onReview = vi.fn();
  render(
    <App>
      <MemoryRouter>
        <RetainedIssueReview workflow={workflow} onReview={onReview} />
      </MemoryRouter>
    </App>,
  );
  fireEvent.click(screen.getAllByRole("button", { name: "AG-01" })[0]!);
  fireEvent.click(
    screen.getByRole("checkbox", { name: "选择当前对象的候选处置" }),
  );
  const action = screen.getByRole("combobox", { name: "当前蚀变对象处置" });
  expect(action.closest(".ant-select")).toHaveTextContent("剔除");
  fireEvent.mouseDown(action);
  fireEvent.click(
    await screen.findByText("保留", {
      selector: ".ant-select-item-option-content",
    }),
  );
  expect(
    screen.getByRole("checkbox", { name: "选择当前对象的候选处置" }),
  ).not.toBeChecked();
  fireEvent.click(
    screen.getByRole("checkbox", { name: "选择当前对象的候选处置" }),
  );
  expect(action.closest(".ant-select")).toHaveTextContent("剔除");
  fireEvent.click(screen.getByRole("button", { name: "执行所选 1 项并继续" }));
  expect(onReview).toHaveBeenCalledExactlyOnceWith(
    "approve",
    "",
    ["held-1"],
    {},
  );
});
