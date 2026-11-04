import { App } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import GeologyWorkbenchCompare from "./GeologyWorkbenchCompare";
import {
  beforeReviewMap,
  afterReviewMap,
  reviewDifferences,
  reviewWorkflow,
} from "./geologyReview.testFixtures";

const { loader, maps } = vi.hoisted(() => ({ loader: vi.fn(), maps: vi.fn() }));
vi.mock("./geologyWorkbenchCompareData", () => ({
  loadWorkbenchReviewComparison: loader,
}));
vi.mock("./GeologyReviewMaps", () => ({
  default: (props: unknown) => {
    maps(props);
    return <div>岩性双图已显示</div>;
  },
}));

it("主岩性就绪立即可见，默认无修改填充和高亮，勾选后显示修改范围", async () => {
  const workflow = reviewWorkflow(true);
  workflow.workflowType = "geology_generic";
  const primary = {
    workflow,
    before: beforeReviewMap,
    after: afterReviewMap,
    differences: reviewDifferences,
    beforeName: "原始岩性",
    afterName: "修正后岩性",
  };
  let finish: (() => void) | undefined;
  loader.mockImplementation((options) => {
    options.onPrimary(primary);
    return new Promise((resolve) => {
      finish = () => resolve(primary);
    });
  });
  render(
    <App>
      <MemoryRouter>
        <style>{`.phase-e-map-shell {position:relative;width:1000px;height:700px;--workspace-edge:12px;--map-control-bottom-clearance:0px;--side-panel-width:280px;--workspace-gap:8px;}`}</style>
        <div className="phase-e-map-shell">
          <GeologyWorkbenchCompare
            workflowId={workflow.id}
            projectId="3"
            projectTagId="3"
            suggestionId={null}
            accessToken=""
            canLoad
            comparisonVisible
            registerLayer={vi.fn()}
            onVisibilityChange={vi.fn()}
            onSuggestionChange={vi.fn()}
          />
        </div>
      </MemoryRouter>
    </App>,
  );
  expect(await screen.findByText("岩性双图已显示")).toBeVisible();
  expect(
    screen.queryByText("正在读取真实图件与检查记录…"),
  ).not.toBeInTheDocument();
  expect(maps.mock.calls.at(-1)![0].differences.features).toHaveLength(0);
  expect(maps.mock.calls.at(-1)![0].spotlight).toBeNull();
  expect(
    screen
      .getByRole("region", { name: "地理工作台地质成果对比" })
      .getBoundingClientRect().width,
  ).toBeGreaterThan(950);
  fireEvent.click(screen.getByLabelText("修正记录 / 实际修改范围"));
  await waitFor(() =>
    expect(
      maps.mock.calls.at(-1)![0].differences.features.length,
    ).toBeGreaterThan(0),
  );
  finish!();
});
