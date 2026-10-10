import { App as AntApp } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ComputeAlgorithm,
  ComputeRuntimeStatus,
  ComputeVersion,
} from "../api/compute";
import { setLocale } from "../i18n";

const { api, scope } = vi.hoisted(() => ({
  api: {
    runtime: vi.fn(),
    algorithms: vi.fn(),
    categories: vi.fn(),
    tasks: vi.fn(),
    inputs: vi.fn(),
    preflight: vi.fn(),
    submit: vi.fn(),
    task: vi.fn(),
    action: vi.fn(),
    saveAlgorithm: vi.fn(),
  },
  scope: { current: "1" },
}));
vi.mock("../api/compute", () => ({
  computeApi: api,
  downloadComputeFile: vi.fn(),
}));
vi.mock("../components/WorkspaceHeader", () => ({
  default: () => <div>顶部导航</div>,
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({
    user: { id: 1, permissions: { canBrowseData: true } },
  }),
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => ({
    current: scope.current,
    projects: [
      { id: 1, name: "公开" },
      { id: 2, name: "科研项目" },
    ],
  }),
}));
import ComputePage from "./ComputePage";
import ComputeTaskForm from "./ComputeTaskForm";

const version: ComputeVersion = {
  id: 10,
  version: "2.1.0",
  status: "published",
  checksum: "abc",
  runtimeDigest: "sha256:abc",
  validated: true,
  createdAt: "2026-09-19T00:00:00Z",
  manifest: {
    schemaVersion: 1,
    identifier: "custom-table-scale",
    name: "管理员新增的表格算法",
    version: "2.1.0",
    description: "无需修改前端的扩展算法",
    author: "实验室",
    runtime: "python-geospatial-v1",
    timeoutSeconds: 300,
    deterministic: true,
    inputs: [
      { key: "table", label: "计算用表格", kind: "table", required: true },
    ],
    parameters: [
      {
        key: "factor",
        label: "缩放倍数",
        type: "number",
        required: true,
        default: 2,
        min: 0,
        max: 10,
      },
    ],
    outputs: [
      {
        key: "result",
        label: "处理结果",
        kind: "table",
        file: "result.csv",
        required: true,
      },
    ],
  },
};
const algorithm: ComputeAlgorithm = {
  id: 5,
  identifier: "custom-table-scale",
  name: version.manifest.name,
  description: version.manifest.description,
  category: "表格计算",
  author: "实验室",
  projectTagId: 1,
  enabled: true,
  canManage: false,
  versions: [version],
};
const runtime: ComputeRuntimeStatus = {
  available: true,
  detail: "计算环境就绪",
  workerOnline: true,
  runtimes: [],
  limits: {},
  permissions: {
    submit_task: true,
    view_own_task: true,
    cancel_own_task: true,
  },
};
const candidate = {
  id: 22,
  name: "项目数据表",
  kind: "table",
  projectTagId: 1,
  fields: ["region", "value"],
  bands: 0,
  crs: "",
  geometryTypes: [],
  sizeBytes: 100,
};
function show() {
  return render(
    <AntApp>
      <MemoryRouter>
        <ComputePage />
      </MemoryRouter>
    </AntApp>,
  );
}
beforeEach(async () => {
  await setLocale("zh-CN");
  vi.clearAllMocks();
  scope.current = "1";
  api.runtime.mockResolvedValue(runtime);
  api.algorithms.mockResolvedValue({ items: [algorithm], total: 1 });
  api.categories.mockResolvedValue({ items: [], total: 0 });
  api.tasks.mockResolvedValue({ items: [], total: 0 });
  api.inputs.mockResolvedValue({ items: [candidate], total: 1 });
  api.preflight.mockResolvedValue({
    valid: true,
    parameters: { factor: 2 },
    detail: "检查通过",
  });
  api.submit.mockResolvedValue({ id: "task-new" });
});

describe("通用计算界面", () => {
  it("动态显示管理员新算法并根据清单生成参数", async () => {
    const view = show();
    expect(await screen.findByText("管理员新增的表格算法")).toBeTruthy();
    fireEvent.mouseDown(await screen.findByText("选择版本开始计算"));
    fireEvent.click(await screen.findByText("2.1.0"));
    fireEvent.click(await screen.findByRole("button", { name: /执\s*行/ }));
    expect(await screen.findByLabelText("缩放倍数")).toBeTruthy();
    expect(screen.getByLabelText("计算用表格")).toBeTruthy();
    view.unmount();
  });
  it("隔离环境不可用时阻止提交并显示原因", async () => {
    api.runtime.mockResolvedValue({
      ...runtime,
      available: false,
      detail: "Windows重启后完成部署",
    });
    const view = show();
    expect(await screen.findByText("Windows重启后完成部署")).toBeTruthy();
    const selection = screen
      .getByText("选择版本开始计算")
      .closest(".ant-select");
    expect(selection?.classList.contains("ant-select-disabled")).toBe(true);
    expect(api.submit).not.toHaveBeenCalled();
    view.unmount();
  });
  it("带入资源并提交规范化参数，防止重复点击产生多个任务", async () => {
    const onSubmitted = vi.fn();
    const view = render(
      <AntApp>
        <MemoryRouter>
          <ComputeTaskForm
            version={version}
            resourceId={22}
            onClose={() => {}}
            onSubmitted={onSubmitted}
          />
        </MemoryRouter>
      </AntApp>,
    );
    await screen.findByText("项目数据表");
    fireEvent.change(screen.getByLabelText("缩放倍数"), {
      target: { value: "7" },
    });
    api.preflight.mockResolvedValue({
      valid: true,
      parameters: { factor: 7 },
      detail: "检查通过",
    });
    fireEvent.click(screen.getByRole("button", { name: "检查并提交" }));
    fireEvent.click(screen.getByRole("button", { name: "检查并提交" }));
    await waitFor(() => expect(api.submit).toHaveBeenCalledTimes(1));
    expect(api.submit.mock.calls[0]?.[0]).toMatchObject({
      versionId: 10,
      inputs: { table: 22 },
      parameters: { factor: 7 },
      trial: false,
    });
    expect(api.submit.mock.calls[0]?.[0].idempotencyKey).toBeTruthy();
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    view.unmount();
  });
  it("切换项目后卸载未提交表单并重新读取数据范围", async () => {
    const view = show();
    await screen.findByText("管理员新增的表格算法");
    fireEvent.mouseDown(screen.getByText("选择版本开始计算"));
    fireEvent.click(await screen.findByText("2.1.0"));
    fireEvent.click(await screen.findByRole("button", { name: /执\s*行/ }));
    await screen.findByLabelText("缩放倍数");
    scope.current = "2";
    view.rerender(
      <AntApp>
        <MemoryRouter>
          <ComputePage />
        </MemoryRouter>
      </AntApp>,
    );
    await waitFor(() => expect(screen.queryByLabelText("缩放倍数")).toBeNull());
    expect(api.algorithms.mock.calls.length).toBeGreaterThanOrEqual(2);
    view.unmount();
  });
});
