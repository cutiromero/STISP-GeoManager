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
vi.mock("./LocalGeologyReviewMaps", () => ({
  default: (props: unknown) => {
    maps(props);
    return <div>岩性双图已显示</div>;
  },
}));

it("主岩性就绪立即可见，默认只用临时轮廓定位当前处，勾选后显示修改范围", async () => {
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
  expect(maps.mock.calls.at(-1)![0].spotlight.outlineOnly).toBe(true);
  expect(maps.mock.calls.at(-1)![0].bounds).not.toBeNull();
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

it("补载修改记录时不误报尚无，完成后才显示真实空态", async () => {
  const workflow = reviewWorkflow(true);
  workflow.workflowType = "geology_generic";
  const primary = {
    workflow,
    before: beforeReviewMap,
    after: afterReviewMap,
    differences: { type: "FeatureCollection", features: [] },
    beforeName: "原图",
    afterName: "结果",
  };
  let finish!: () => void;
  loader.mockImplementation((options) => {
    options.onPrimary(primary);
    return new Promise((resolve) => {
      finish = () => resolve(primary);
    });
  });
  render(
    <App>
      <MemoryRouter>
        <GeologyWorkbenchCompare
          workflowId={workflow.id}
          projectId="3"
          projectTagId="3"
          suggestionId={null}
          canLoad
          comparisonVisible
          registerLayer={vi.fn()}
          onVisibilityChange={vi.fn()}
          onSuggestionChange={vi.fn()}
        />
      </MemoryRouter>
    </App>,
  );
  expect(await screen.findByText("正在加载修改记录…")).toBeVisible();
  expect(screen.queryByText(/当前尚无可显示/)).not.toBeInTheDocument();
  await act(async () => finish());
  expect(await screen.findByText(/当前尚无可显示/)).toBeVisible();
});

it("先选要素规则动作组，再跳到组内第N处并用上一处下一处浏览", async () => {
  const workflow = reviewWorkflow(true);
  workflow.workflowType = "geology_generic";
  const differences = {
    ...reviewDifferences,
    features: Array.from({ length: 61 }, (_, index) => ({
      ...reviewDifferences.features[0]!,
      properties: {
        ...reviewDifferences.features[0]!.properties,
        feature_id: `object-${index}`,
        element: index < 60 ? "lithology" : "structure",
        rule_id: index < 60 ? "L-01" : "S-01",
        action: index < 60 ? "set_code" : "exclude",
        new_value: `新单元${index}`,
      },
    })),
  };
  loader.mockResolvedValue({
    workflow,
    before: beforeReviewMap,
    after: afterReviewMap,
    differences,
    beforeName: "原图",
    afterName: "结果",
  });
  render(
    <App>
      <MemoryRouter>
        <GeologyWorkbenchCompare
          workflowId={workflow.id}
          projectId="3"
          projectTagId="3"
          suggestionId={null}
          canLoad
          comparisonVisible
          registerLayer={vi.fn()}
          onVisibilityChange={vi.fn()}
          onSuggestionChange={vi.fn()}
        />
      </MemoryRouter>
    </App>,
  );
  await screen.findByText("第 1 处，共 61 处");
  const position = screen.getByRole("spinbutton", { name: "组内位置" });
  fireEvent.change(position, { target: { value: "50" } });
  fireEvent.blur(position);
  expect(await screen.findByText("第 50 处，共 61 处")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "下一处修改" }));
  expect(await screen.findByText("第 51 处，共 61 处")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "上一处修改" }));
  expect(await screen.findByText("第 50 处，共 61 处")).toBeVisible();
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "修改分组" }));
  fireEvent.click(
    await screen.findByText(/构造 \/ S-01/, {
      selector: ".ant-select-item-option-content",
    }),
  );
  expect(await screen.findByText("第 61 处，共 61 处")).toBeVisible();
  expect(screen.getByRole("button", { name: "上一处修改" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "下一处修改" })).toBeDisabled();
});
