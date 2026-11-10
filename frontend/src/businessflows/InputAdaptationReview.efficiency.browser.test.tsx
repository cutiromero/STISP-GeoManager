import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App } from "antd";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { businessFlowsApi } from "../api/businessFlows";
import { ApiError } from "../api/client";
import type {
  BusinessFlowInputPlan,
  BusinessFlowInputPreparation,
} from "../api/generated/types.gen";
import InputAdaptationReview from "./InputAdaptationReview";

const request: BusinessFlowInputPreparation = {
  versionId: 3,
  inputs: { observations: 81 },
};
function plan(
  status: "convert" | "needs_choice" | "needs_parameters" = "convert",
): BusinessFlowInputPlan {
  return {
    ready: status === "convert",
    items: [
      {
        role: "observations",
        sourceId: 81,
        sourceName: "区域观测栅格",
        sourceType: "raster",
        sourceRevision: "2026-11-10T00:00:00Z",
        sourceBands: 3,
        targetTypes: ["table"],
        targetSemantics: "raster_band_statistics_v1",
        status,
        fields: ["类别", "区域"],
        ...(status !== "needs_choice"
          ? { versionId: 9, parameters: { band: 0 } }
          : {}),
        candidates: [
          {
            versionId: 9,
            name: "栅格波段统计转表",
            description: "读取实际波段生成统计表",
            targetType: "table",
            parameters: [
              {
                key: "band",
                label: "统计波段",
                type: "integer",
                default: 0,
                min: 0,
                max: 1024,
              },
            ],
          },
        ],
      },
    ],
  };
}
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(businessFlowsApi, "prepareInputs").mockResolvedValue(plan());
});
afterEach(() => {
  vi.restoreAllMocks();
});
function show(value = request) {
  const onStatus = vi.fn(),
    onChoices = vi.fn();
  const view = render(
    <App>
      <InputAdaptationReview
        flowId={1}
        request={value}
        disabled={false}
        onStatus={onStatus}
        onChoices={onChoices}
      />
    </App>,
  );
  return {
    ...view,
    onStatus,
    onChoices,
    update: (next: BusinessFlowInputPreparation) =>
      view.rerender(
        <App>
          <InputAdaptationReview
            flowId={1}
            request={next}
            disabled={false}
            onStatus={onStatus}
            onChoices={onChoices}
          />
        </App>,
      ),
  };
}
it("prepares non-geological data once and changes only declared conversion parameters", async () => {
  const view = show();
  await screen.findByText("区域观测栅格");
  expect(screen.getByText("栅格 → 表格")).toBeVisible();
  expect(businessFlowsApi.prepareInputs).toHaveBeenCalledOnce();
  const field = screen.getByRole("spinbutton");
  fireEvent.change(field, { target: { value: "2" } });
  expect(view.onChoices).toHaveBeenLastCalledWith({
    observations: { versionId: 9, parameters: { band: 2 } },
  });
  expect(view.onStatus.mock.calls.at(-1)?.[1]).toBe(true);
  view.update({ inputs: { observations: 81 }, versionId: 3 });
  await act(async () => {
    await new Promise((done) => setTimeout(done, 240));
  });
  expect(businessFlowsApi.prepareInputs).toHaveBeenCalledOnce();
});
it("requires an explicit choice when task semantics are ambiguous", async () => {
  vi.mocked(businessFlowsApi.prepareInputs).mockResolvedValue(
    plan("needs_choice"),
  );
  const view = show();
  await screen.findByText("区域观测栅格");
  expect(view.onStatus.mock.calls.at(-1)?.[1]).toBe(false);
  fireEvent.mouseDown(screen.getByRole("combobox"));
  fireEvent.click(await screen.findByText("栅格波段统计转表"));
  expect(view.onChoices).toHaveBeenLastCalledWith({
    observations: { versionId: 9, parameters: {} },
  });
});
it("clears old converter choices and ignores a late plan after changing the source", async () => {
  let resolve!: (value: BusinessFlowInputPlan) => void;
  vi.mocked(businessFlowsApi.prepareInputs).mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const view = show();
  await waitFor(() =>
    expect(businessFlowsApi.prepareInputs).toHaveBeenCalledOnce(),
  );
  const second = plan();
  second.items[0]!.sourceName = "新的观测资料";
  second.items[0]!.sourceId = 82;
  vi.mocked(businessFlowsApi.prepareInputs).mockResolvedValue(second);
  view.update({ versionId: 3, inputs: { observations: 82 } });
  await screen.findByText("新的观测资料");
  await act(async () => {
    resolve(plan());
  });
  expect(screen.queryByText("区域观测栅格")).not.toBeInTheDocument();
  expect(screen.getByText("新的观测资料")).toBeVisible();
  expect(businessFlowsApi.prepareInputs).toHaveBeenCalledTimes(2);
});
it("hides a formerly readable plan after explicit revocation", async () => {
  const view = show();
  await screen.findByText("区域观测栅格");
  vi.mocked(businessFlowsApi.prepareInputs).mockRejectedValue(
    new ApiError("资料已撤权", 403),
  );
  view.update({
    ...request,
    inputAdapters: { observations: { versionId: 9, parameters: { band: 1 } } },
  });
  await screen.findByText("资料已撤权");
  expect(screen.queryByText("区域观测栅格")).not.toBeInTheDocument();
  expect(view.onStatus.mock.calls.at(-1)?.[1]).toBe(false);
});
