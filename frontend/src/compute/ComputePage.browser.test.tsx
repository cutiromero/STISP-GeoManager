import { App as AntApp } from "antd";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import type {
  ComputeAlgorithm,
  ComputeRuntimeStatus,
  ComputeTask,
  ComputeVersion,
} from "../api/compute";
import { setLocale } from "../i18n";
import platformStyles from "../styles.css?inline";
import computeStyles from "./compute.css?inline";
import taskStyles from "./compute-tasks.css?inline";

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
      <style>{platformStyles + computeStyles + taskStyles}</style>
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

const longTaskName =
  "检查待提交的区域地质解译地图，查阅专家知识，说明地层时代和内部漏填问题的依据，形成建议，经用户批准后调用算法修正地图，再核对实际变化并生成检查报告和面积统计。";
const task: ComputeTask = {
  id: "task-map-check",
  name: longTaskName,
  projectTagId: 1,
  ownerName: "科研用户",
  algorithmName: "地质图属性与完整性检查",
  version,
  status: "running",
  stage: "正在检查地图属性与空间关系",
  progress: 42,
  error: "",
  parameters: { factor: 2 },
  inputs: [],
  outputs: [],
  createdAt: "2026-10-14T03:25:00Z",
  startedAt: "2026-10-14T03:25:08Z",
  finishedAt: null,
  trial: false,
  unread: true,
  retryOf: null,
  attemptCount: 1,
};

describe("计算任务排布", () => {
  it.each([1600, 390])(
    "在 %s 像素下保持长任务、状态与操作在页面范围内",
    async (width) => {
      await page.viewport(width, 900);
      try {
        api.tasks.mockResolvedValue({
          items: [
            task,
            {
              ...task,
              id: "task-ndvi",
              name: "研究区植被指数计算",
              algorithmName: "NDVI植被指数",
              status: "succeeded",
              stage: "计算完成",
              progress: 100,
              unread: false,
            },
            {
              ...task,
              id: "task-failed",
              name: "局部地图检查",
              status: "failed",
              stage: "检查失败",
              error: "缺少时代属性，请补充字段后重新提交",
              progress: 0,
              unread: false,
            },
          ],
          total: 3,
        });
        const view = show();
        const tasksTab = await screen.findByRole("tab", { name: "我的任务" });
        fireEvent.click(tasksTab);
        await waitFor(() =>
          expect(tasksTab).toHaveAttribute("aria-selected", "true"),
        );
        const list = await screen.findByRole("region", {
          name: "计算任务列表",
        });
        await within(list).findByText("共 3 项");
        expect(within(list).getByText("42%")).toBeVisible();
        expect(
          within(list).getByText("缺少时代属性，请补充字段后重新提交"),
        ).toBeVisible();
        expect(within(list).getByLabelText("未读任务")).toBeVisible();
        expect(
          within(list).getAllByRole("button", { name: "查看详情" }),
        ).toHaveLength(3);
        for (const row of list.querySelectorAll<HTMLElement>(
          ".compute-task-row",
        )) {
          expect(row.scrollWidth).toBeLessThanOrEqual(row.clientWidth + 1);
          expect(row.getBoundingClientRect().right).toBeLessThanOrEqual(width);
        }
        const title = list.querySelector<HTMLElement>(".compute-task-title");
        expect(title?.getBoundingClientRect().height).toBeLessThan(52);
        expect(view.container.scrollWidth).toBeLessThanOrEqual(width);
        await page.screenshot({
          path: `../../test-results/compute-tasks-${width}.png`,
          animations: "disabled",
          fullPage: true,
        });
        fireEvent.click(within(list).getByText("完整任务说明"));
        expect(list.querySelector(".compute-task-description p")).toBeVisible();
        expect(
          list.querySelector(".compute-task-description p")?.textContent,
        ).toBe(longTaskName);
        expect(list.scrollWidth).toBeLessThanOrEqual(list.clientWidth + 1);
        view.unmount();
      } finally {
        await page.viewport(1600, 900);
      }
    },
  );

  it("保留详情入口、已读操作和服务端状态筛选", async () => {
    api.tasks.mockResolvedValue({ items: [task], total: 1 });
    api.task.mockResolvedValue(task);
    api.action.mockResolvedValue(task);
    const view = show();
    fireEvent.click(await screen.findByRole("tab", { name: "我的任务" }));
    const list = await screen.findByRole("region", { name: "计算任务列表" });
    fireEvent.click(
      await within(list).findByRole("button", { name: "查看详情" }),
    );
    await waitFor(() => expect(api.task).toHaveBeenCalledWith(task.id));
    expect(api.action).toHaveBeenCalledWith(task.id, "read");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.mouseDown(within(list).getByLabelText("筛选任务状态"));
    const completed = await screen.findAllByText("已完成");
    fireEvent.click(completed[completed.length - 1]!);
    await waitFor(() =>
      expect(api.tasks).toHaveBeenCalledWith(
        expect.objectContaining({ status: "succeeded", page: 1 }),
      ),
    );
    view.unmount();
  });
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
