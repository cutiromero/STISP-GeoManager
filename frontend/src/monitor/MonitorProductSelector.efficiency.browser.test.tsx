import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { expect, it } from "vitest";
import type {
  MonitoringProduct,
  ResourceListItem,
} from "../api/generated/types.gen";
import MonitorProductSelector from "./MonitorProductSelector";
import { useMonitorProductSelection } from "./useMonitorProductSelection";

const current = "11111111-1111-4111-8111-111111111111";
const previous = "22222222-2222-4222-8222-222222222222";
const earlier = "33333333-3333-4333-8333-333333333333";
function product(id: number, batch: string, source = 10): MonitoringProduct {
  return {
    id,
    name: `分类成果${id}`,
    kind: "model",
    resourceId: 100 + id,
    sourceResourceIds: [source],
    registeredAt: "2026-11-14T08:00:00Z",
    model: { variant: "完整六类" },
    provenance: {
      type: "system_interpretation",
      batchId: batch,
      taskId: `task-${id}`,
      workflowId: batch,
      createdAt: `2026-11-14T0${id}:00:00Z`,
      creator: "处理人甲",
      owned: true,
    },
  } as MonitoringProduct;
}
const items = [
  product(1, current),
  product(2, previous),
  product(3, earlier),
  product(4, previous, 20),
];
const references = [
  { id: 501, name: "人工标准A", dataType: "raster" },
  { id: 502, name: "人工标准B", dataType: "vector" },
] as ResourceListItem[];
function Harness({
  batch = current,
  source = 10,
}: {
  batch?: string;
  source?: number;
}) {
  const selection = useMonitorProductSelection({
    items,
    references,
    currentBatchId: batch,
    sourceId: source,
  });
  return (
    <App>
      <MonitorProductSelector selection={selection} />
      <output aria-label="所选成果">
        {selection.selected?.id ?? selection.reference?.id ?? "empty"}
      </output>
      <output aria-label="当前任务批次">{batch}</output>
    </App>
  );
}
async function choose(label: RegExp | string) {
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "选择成果版本" }));
  fireEvent.click(
    await screen.findByText(label, {
      selector: ".ant-select-item-option-content span",
    }),
  );
}
it("binds current results to the exact batch and does not silently show an older result", async () => {
  const view = render(<Harness />);
  expect(screen.getByLabelText("所选成果")).toHaveTextContent("1");
  view.rerender(<Harness batch="44444444-4444-4444-8444-444444444444" />);
  await waitFor(() =>
    expect(screen.getByLabelText("所选成果")).toHaveTextContent("empty"),
  );
  expect(screen.getByText("本次任务尚无该样区成果")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("radio", { name: "历史解译", exact: true }));
  await choose(/22222222/);
  expect(screen.getByLabelText("所选成果")).toHaveTextContent("2");
  expect(screen.getByLabelText("当前任务批次")).toHaveTextContent("44444444");
});
it("chooses between multiple historical batches while keeping their identities visible", async () => {
  render(<Harness />);
  fireEvent.click(screen.getByRole("radio", { name: "历史解译", exact: true }));
  await choose(/33333333/);
  expect(screen.getByLabelText("所选成果")).toHaveTextContent("3");
  expect(
    screen.getByText("批次 33333333", {
      selector: ".monitor-product-identity > span",
    }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("当前任务批次")).toHaveTextContent(current);
});
it("separates a user-chosen standard from system interpretation and history", async () => {
  render(<Harness />);
  fireEvent.click(screen.getByRole("radio", { name: "标准成果", exact: true }));
  await choose(/人工标准B/);
  expect(screen.getByLabelText("所选成果")).toHaveTextContent("502");
  expect(screen.getByText("数据资源 #502 · 上传资料")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("radio", { name: "本次解译", exact: true }));
  expect(screen.getByLabelText("所选成果")).toHaveTextContent("1");
});
it("does not substitute a historical result for a region missing from the current batch", async () => {
  const view = render(<Harness />);
  view.rerender(<Harness source={20} />);
  await waitFor(() =>
    expect(screen.getByLabelText("所选成果")).toHaveTextContent("empty"),
  );
  fireEvent.click(screen.getByRole("radio", { name: "历史解译", exact: true }));
  expect(screen.getByLabelText("所选成果")).toHaveTextContent("4");
});

it("keeps all origin tabs and batch information inside a narrow card", async () => {
  const view = render(
    <div style={{ width: 240 }}>
      <Harness />
    </div>,
  );
  const selector = view.container.querySelector<HTMLElement>(
    ".monitor-product-selector",
  )!;
  const box = selector.getBoundingClientRect();
  expect(selector.scrollWidth).toBeLessThanOrEqual(selector.clientWidth + 1);
  for (const label of selector.querySelectorAll<HTMLElement>(
    ".ant-segmented-item-label",
  )) {
    const item = label.getBoundingClientRect();
    expect(item.left).toBeGreaterThanOrEqual(box.left - 1);
    expect(item.right).toBeLessThanOrEqual(box.right + 1);
  }
  expect(
    screen.getByText("批次 11111111", {
      selector: ".monitor-product-identity > span",
    }),
  ).toBeVisible();
});
