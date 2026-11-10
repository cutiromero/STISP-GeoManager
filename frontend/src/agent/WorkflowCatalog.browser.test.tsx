import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { agentApi } from "../api/agent";
import type { AgentWorkflowUpload } from "../api/generated/types.gen";
import GenericWorkflowUploads from "./GenericWorkflowUploads";

afterEach(() => vi.restoreAllMocks());

const item: AgentWorkflowUpload = {
  id: "4f1c2a9e-7b3d-4c61-9a2e-1d5f6b7c8a90",
  batchId: "a".repeat(32),
  resourceId: 812,
  source: "catalog",
  name: "系统岩性图",
  fileName: "系统岩性图",
  dataType: "vector",
  sizeBytes: 128,
  roleHint: "lithology",
  workflowId: null,
  createdAt: "2026-11-04T08:00:00Z",
  profile: {
    kind: "vector",
    crs: "EPSG:4326",
    geometryTypes: ["Polygon"],
    featureCount: 4,
    bandCount: null,
    width: null,
    height: null,
    bounds: [96, 35, 97, 36],
    fields: [],
    warnings: [],
  },
};

it("搜索系统数据、加入与上传并列，并仅移除目录引用", async () => {
  vi.spyOn(agentApi, "workflowCatalogResources").mockResolvedValue({
    total: 41,
    page: 1,
    pageSize: 20,
    directories: [{ id: 4, name: "演示资料" }],
    items: [
      {
        id: 812,
        name: "系统岩性图",
        dataType: "vector",
        description: "岩性",
        directoryId: 4,
        directoryName: "演示资料",
        createdAt: "2026-11-04T08:00:00Z",
        updatedAt: "2026-11-04T08:00:00Z",
      },
    ],
  });
  vi.spyOn(agentApi, "addWorkflowCatalogReferences").mockResolvedValue({
    items: [item],
  });
  vi.spyOn(agentApi, "restoreLogicConfiguration").mockResolvedValue({
    configuration: null,
    items: [],
    unavailableResourceIds: [],
  });
  vi.spyOn(agentApi, "deleteWorkflowUpload").mockResolvedValue(undefined);
  vi.spyOn(agentApi, "uploadWorkflowBatch").mockResolvedValue({
    items: [
      {
        ...item,
        id: "another-upload",
        resourceId: 813,
        source: "upload",
        name: "上传构造图",
        fileName: "上传构造图.geojson",
      },
    ],
    errors: [],
  });
  const { container } = render(
    <App>
      <GenericWorkflowUploads
        batchId={item.batchId}
        model="mock"
        inputs={{}}
        onInputsChange={vi.fn()}
        uploadOnly
      />
    </App>,
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "选择系统数据" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "选择系统数据" }));
  const dialog = await screen.findByRole("dialog");
  await waitFor(() =>
    expect(agentApi.workflowCatalogResources).toHaveBeenCalled(),
  );
  fireEvent.click(within(dialog).getByTitle("2"));
  await waitFor(() =>
    expect(agentApi.workflowCatalogResources).toHaveBeenLastCalledWith(
      "",
      expect.anything(),
      2,
      undefined,
    ),
  );
  fireEvent.change(
    within(dialog).getByRole("combobox", { name: "选择系统数据资源" }),
    {
      target: { value: "系统" },
    },
  );
  await waitFor(() =>
    expect(agentApi.workflowCatalogResources).toHaveBeenLastCalledWith(
      "系统",
      expect.objectContaining({ signal: expect.anything() }),
      1,
      undefined,
    ),
  );
  fireEvent.mouseDown(
    within(dialog).getByRole("combobox", { name: "按数据目录筛选" }),
  );
  fireEvent.click(
    await screen.findByText("演示资料", {
      selector: ".ant-select-item-option-content",
    }),
  );
  await waitFor(() =>
    expect(agentApi.workflowCatalogResources).toHaveBeenLastCalledWith(
      "系统",
      expect.anything(),
      1,
      4,
    ),
  );
  fireEvent.mouseDown(
    within(dialog).getByRole("combobox", { name: "选择系统数据资源" }),
  );
  const option = await screen.findByRole("group", { name: "系统岩性图" });
  expect(option.textContent).toBe(
    "系统岩性图（矢量 · 演示资料 · 登记 2026-11-04）",
  );
  await waitFor(() => {
    expect(option).toBeVisible();
    expect(
      within(option).getByText("系统", { selector: "mark" }),
    ).toBeVisible();
  });
  fireEvent.click(option);
  fireEvent.click(within(dialog).getByRole("button", { name: "加入本次任务" }));
  await waitFor(() =>
    expect(
      agentApi.addWorkflowCatalogReferences,
    ).toHaveBeenCalledExactlyOnceWith(item.batchId, [812]),
  );
  await waitFor(() =>
    expect(
      screen
        .getAllByText("系统岩性图")
        .some((node) => node.closest(".agent-demo-fields")),
    ).toBe(true),
  );
  fireEvent.change(container.querySelector('input[type="file"]')!, {
    target: { files: [new File(["{}"], "上传构造图.geojson")] },
  });
  expect(await screen.findByText("上传构造图.geojson")).toBeInTheDocument();
  expect(screen.getByText("系统数据")).toBeInTheDocument();
  expect(screen.getByText("上传资料")).toBeInTheDocument();
  const row = screen
    .getAllByText("系统岩性图")
    .map((node) => node.closest(".agent-demo-fields"))
    .find(Boolean)! as HTMLElement;
  fireEvent.click(within(row).getByRole("button", { name: /移\s*除/ }));
  await waitFor(() =>
    expect(
      screen
        .queryAllByText("系统岩性图")
        .some((node) => node.closest(".agent-demo-fields")),
    ).toBe(false),
  );
  expect(agentApi.deleteWorkflowUpload).toHaveBeenCalledExactlyOnceWith(
    item.id,
  );
  expect(screen.getByText("上传构造图.geojson")).toBeInTheDocument();
});

function RestoredPanel() {
  const [open, setOpen] = useState(true);
  const [count, setCount] = useState(0);
  return (
    <App>
      <ButtonForTest open={open} count={count} onOpen={() => setOpen(true)} />
      <div hidden={!open}>
        <GenericWorkflowUploads
          batchId={item.batchId}
          model="mock"
          inputs={{}}
          onInputsChange={vi.fn()}
          uploadOnly
          onClose={() => setOpen(false)}
          onCountChange={setCount}
        />
      </div>
    </App>
  );
}

function ButtonForTest({
  open,
  count,
  onOpen,
}: {
  open: boolean;
  count: number;
  onOpen: () => void;
}) {
  return !open && <button onClick={onOpen}>已选 {count} 份资料 · 展开</button>;
}

it("服务端恢复的资料收起后保留，重新展开可移除且失效资源有提示", async () => {
  vi.spyOn(agentApi, "restoreLogicConfiguration").mockResolvedValue({
    configuration: {
      resourceIds: [812, 813],
      roles: { lithology: 812 },
      fieldMapping: { lithology: { name: "DCMC" } },
      prompt: "沿用要求",
      reasoningEffort: "low",
    },
    items: [item],
    unavailableResourceIds: [813],
  });
  vi.spyOn(agentApi, "deleteWorkflowUpload").mockResolvedValue(undefined);
  const mounted = render(<RestoredPanel />);
  expect(await screen.findByText("系统岩性图")).toBeVisible();
  expect(screen.getByText(/1 份上次资料已失效/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "收起" }));
  expect(
    screen.queryByRole("region", { name: "上传本次资料" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "已选 1 份资料 · 展开" }));
  expect(screen.getByText("系统岩性图")).toBeVisible();
  expect(agentApi.restoreLogicConfiguration).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: /移\s*除/ }));
  await waitFor(() =>
    expect(
      screen
        .queryAllByText("系统岩性图")
        .some((node) => node.closest(".agent-demo-fields")),
    ).toBe(false),
  );
  mounted.unmount();
});
