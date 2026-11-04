import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
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
    items: [
      {
        id: 812,
        name: "系统岩性图",
        dataType: "vector",
        description: "岩性",
        origin: "uploaded_data",
        isComputeResult: false,
      },
    ],
  });
  vi.spyOn(agentApi, "addWorkflowCatalogReferences").mockResolvedValue({
    items: [item],
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
  fireEvent.click(screen.getByRole("button", { name: "选择系统数据" }));
  const dialog = await screen.findByRole("dialog");
  await waitFor(() =>
    expect(agentApi.workflowCatalogResources).toHaveBeenCalled(),
  );
  fireEvent.change(within(dialog).getByRole("combobox"), {
    target: { value: "系统" },
  });
  await waitFor(() =>
    expect(agentApi.workflowCatalogResources).toHaveBeenLastCalledWith(
      "系统",
      expect.objectContaining({ signal: expect.anything() }),
    ),
  );
  fireEvent.mouseDown(within(dialog).getByRole("combobox"));
  fireEvent.click(await screen.findByText("系统岩性图（矢量）"));
  fireEvent.click(within(dialog).getByRole("button", { name: "加入本次任务" }));
  await waitFor(() =>
    expect(
      agentApi.addWorkflowCatalogReferences,
    ).toHaveBeenCalledExactlyOnceWith(item.batchId, [812]),
  );
  expect(await screen.findByText("系统岩性图")).toBeInTheDocument();
  fireEvent.change(container.querySelector('input[type="file"]')!, {
    target: { files: [new File(["{}"], "上传构造图.geojson")] },
  });
  expect(await screen.findByText("上传构造图.geojson")).toBeInTheDocument();
  expect(screen.getByText("系统数据")).toBeInTheDocument();
  expect(screen.getByText("上传资料")).toBeInTheDocument();
  const row = screen
    .getByText("系统岩性图")
    .closest(".agent-demo-fields")! as HTMLElement;
  fireEvent.click(within(row).getByRole("button", { name: /移\s*除/ }));
  await waitFor(() =>
    expect(screen.queryByText("系统岩性图")).not.toBeInTheDocument(),
  );
  expect(agentApi.deleteWorkflowUpload).toHaveBeenCalledExactlyOnceWith(
    item.id,
  );
  expect(screen.getByText("上传构造图.geojson")).toBeInTheDocument();
});
