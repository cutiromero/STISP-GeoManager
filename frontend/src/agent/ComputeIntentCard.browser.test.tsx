import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { agentApi } from "../api/agent";
import ComputeIntentCard from "./ComputeIntentCard";
import { computeIntent, computeRun } from "./computeFlow.testFixtures";
import "./agent.css";

beforeEach(() => {
  vi.restoreAllMocks();
});
async function selectBand(label: string, band: number) {
  fireEvent.mouseDown(screen.getByRole("combobox", { name: label }));
  fireEvent.click(
    await screen.findByText(`第 ${band} 波段`, {
      selector:
        ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-content",
    }),
  );
}
function show(intent = computeIntent) {
  const onChanged = vi.fn();
  const rendered = render(
    <AntApp>
      <ComputeIntentCard runId={8} intent={intent} onChanged={onChanged} />
    </AntApp>,
  );
  return { ...rendered, onChanged };
}

it("requires explicit bands rather than silently using manifest defaults", async () => {
  const submit = vi
    .spyOn(agentApi, "updateComputeIntent")
    .mockResolvedValue(computeRun());
  show();
  await screen.findByText("研究区影像 · 8 波段");
  fireEvent.click(screen.getByRole("button", { name: "开始计算" }));
  await screen.findAllByText("请补充此参数");
  expect(submit).not.toHaveBeenCalled();
  expect(screen.getByRole("combobox", { name: "红光波段" })).toHaveValue("");
  await selectBand("红光波段", 3);
  await selectBand("近红外波段", 8);
  fireEvent.click(screen.getByRole("button", { name: "开始计算" }));
  await waitFor(() => expect(submit).toHaveBeenCalledOnce());
  expect(submit).toHaveBeenCalledWith(8, {
    action: "submit",
    planRevision: "checked-plan-1",
    inputs: { image: 10 },
    parameters: { red: 3, nir: 8 },
    autoImport: false,
  });
});

it("preserves explicit automatic import and prevents duplicate button submissions", async () => {
  let resolve!: (run: ReturnType<typeof computeRun>) => void;
  const submit = vi.spyOn(agentApi, "updateComputeIntent").mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const intent = {
    ...computeIntent,
    status: "ready" as const,
    parameters: { red: 3, nir: 8 },
    missingParameters: [],
    autoImport: true,
  };
  const { onChanged } = show(intent);
  expect(
    screen.getByRole("checkbox", { name: "完成后自动入库" }),
  ).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "开始计算" }));
  fireEvent.click(screen.getByRole("button", { name: "开始计算" }));
  await waitFor(() => expect(submit).toHaveBeenCalledOnce());
  expect(submit).toHaveBeenCalledWith(
    8,
    expect.objectContaining({
      autoImport: true,
      parameters: { red: 3, nir: 8 },
    }),
  );
  const updated = computeRun({
    ...intent,
    status: "submitted",
    taskId: "real-task",
    planRevision: "submitted-plan",
  });
  resolve(updated);
  await waitFor(() => expect(onChanged).toHaveBeenCalledWith(updated));
});

it("clears band selections after switching to another image", async () => {
  show({ ...computeIntent, parameters: { red: 3, nir: 8 } });
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "输入影像" }));
  fireEvent.click(
    await screen.findByText("另一幅影像 · 4 波段", {
      selector: ".ant-select-item-option-content",
    }),
  );
  await waitFor(() =>
    expect(screen.getByRole("combobox", { name: "近红外波段" })).toHaveValue(
      "",
    ),
  );
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "近红外波段" }));
  expect(
    screen.queryByText("第 8 波段", {
      selector: ".ant-select-item-option-content",
    }),
  ).not.toBeInTheDocument();
});

it("shows server validation failure and never claims a task was submitted", async () => {
  vi.spyOn(agentApi, "updateComputeIntent").mockRejectedValue(
    new Error("这张影像已失去访问权限，请重新选择"),
  );
  show({ ...computeIntent, parameters: { red: 3, nir: 8 } });
  fireEvent.click(screen.getByRole("button", { name: "开始计算" }));
  await screen.findByText("这张影像已失去访问权限，请重新选择");
  expect(screen.queryByText("计算完成")).not.toBeInTheDocument();
});

it("fits the setup card on a narrow screen", async () => {
  await page.viewport(390, 844);
  const { container } = show();
  await screen.findByText("研究区影像 · 8 波段");
  expect(container.scrollWidth).toBeLessThanOrEqual(390);
  await page.screenshot({
    path: "../../test-results/compute-intent-mobile.png",
  });
  await page.viewport(1600, 900);
});

it("refreshes a changed plan instead of repeatedly submitting a stale revision", async () => {
  const changed = computeRun({
    ...computeIntent,
    planRevision: "checked-plan-2",
    parameters: { red: 3, nir: 8 },
  });
  vi.spyOn(agentApi, "updateComputeIntent").mockRejectedValue(
    Object.assign(new Error("计算配置已更新"), { status: 409 }),
  );
  const reload = vi.spyOn(agentApi, "computeIntent").mockResolvedValue(changed);
  const { onChanged } = show({
    ...computeIntent,
    parameters: { red: 3, nir: 8 },
  });
  fireEvent.click(screen.getByRole("button", { name: "开始计算" }));
  await waitFor(() => expect(onChanged).toHaveBeenCalledWith(changed));
  expect(reload).toHaveBeenCalledWith(8);
});
