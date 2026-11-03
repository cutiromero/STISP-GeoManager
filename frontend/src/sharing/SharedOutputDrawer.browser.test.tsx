import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SharedOutputDrawer from "./SharedOutputDrawer";
import { sharedOutput, shareTarget } from "./sharingTestFixtures";

const mocks = vi.hoisted(() => ({
  open: vi.fn(),
  preview: vi.fn(),
  task: vi.fn(),
  tasks: vi.fn(),
  download: vi.fn(),
  choose: vi.fn(),
  currentProject: "1",
}));
vi.mock("../api/sharing", () => ({ sharingApi: { open: mocks.open } }));
vi.mock("../api/compute", () => ({
  computeApi: { preview: mocks.preview, task: mocks.task, tasks: mocks.tasks },
  downloadComputeFile: mocks.download,
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => ({
    current: mocks.currentProject,
    choose: mocks.choose,
  }),
}));

function Location() {
  const location = useLocation();
  return (
    <span data-testid="location">
      {location.pathname}
      {location.search}
    </span>
  );
}
function show() {
  return render(
    <ConfigProvider locale={zhCN}>
      <AntApp>
        <MemoryRouter initialEntries={["/compute?sharedInvitation=23"]}>
          <SharedOutputDrawer invitationId={23} onClose={vi.fn()} />
          <Location />
        </MemoryRouter>
      </AntApp>
    </ConfigProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.currentProject = "1";
  mocks.open.mockResolvedValue({
    target: shareTarget({
      kind: "compute_output",
      objectId: 71,
      name: "检查报告",
      openUrl: "/compute?sharedInvitation=23",
    }),
    output: sharedOutput(),
  });
  mocks.preview.mockResolvedValue({
    kind: "report",
    metadata: { format: "markdown" },
    columns: ["问题", "处置"],
    rows: [["时代与名称不一致", "更新时代属性"]],
  });
  mocks.download.mockResolvedValue(undefined);
});

describe("one accepted compute output", () => {
  it("previews and downloads only the selected file without fetching its task", async () => {
    show();
    expect(
      await screen.findByText("检查报告.md / 2.0 KiB"),
    ).toBeInTheDocument();
    expect(await screen.findByText("时代与名称不一致")).toBeInTheDocument();
    expect(mocks.preview).toHaveBeenCalledWith(71);
    expect(mocks.preview).toHaveBeenCalledOnce();
    expect(mocks.task).not.toHaveBeenCalled();
    expect(mocks.tasks).not.toHaveBeenCalled();
    expect(screen.queryByText("输入数据")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "入库" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "下载" }));
    await waitFor(() =>
      expect(mocks.download).toHaveBeenCalledWith(
        "/api/compute/outputs/71/download/",
        "检查报告.md",
      ),
    );
    expect(mocks.open).toHaveBeenCalledTimes(2);
  });

  it("does not preview or download before switching to the authorized project", async () => {
    mocks.currentProject = "2";
    show();
    const switchButton = await screen.findByRole("button", {
      name: "切换项目",
    });
    expect(screen.getByRole("button", { name: "下载" })).toBeDisabled();
    expect(mocks.preview).not.toHaveBeenCalled();
    fireEvent.click(switchButton);
    expect(mocks.choose).toHaveBeenCalledWith("1");
    expect(mocks.download).not.toHaveBeenCalled();
  });

  it("shows a safe error when the share has been revoked", async () => {
    mocks.open.mockRejectedValue(new Error("分享已失效或没有访问权限"));
    show();
    expect(
      await screen.findByText("分享已失效或没有访问权限"),
    ).toBeInTheDocument();
    expect(mocks.preview).not.toHaveBeenCalled();
    expect(mocks.task).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "下载" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the shared file usable when preview data is incomplete", async () => {
    mocks.preview.mockResolvedValue({ canChat: true });
    show();
    expect(
      await screen.findByText("分享服务返回内容不完整，请稍后重试"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载" })).toBeEnabled();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("rechecks permission on download and stops when access was withdrawn", async () => {
    show();
    const download = await screen.findByRole("button", { name: "下载" });
    mocks.open.mockRejectedValueOnce(new Error("分享已失效"));
    fireEvent.click(download);
    expect(await screen.findByText("分享已失效")).toBeInTheDocument();
    expect(mocks.download).not.toHaveBeenCalled();
  });

  it("opens a spatial output directly without exposing sibling outputs", async () => {
    mocks.open.mockResolvedValue({
      target: shareTarget({ kind: "compute_output", objectId: 71 }),
      output: sharedOutput({
        kind: "vector",
        label: "修改范围",
        fileName: "changes.geojson",
      }),
    });
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "在地理工作台查看" }),
    );
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/map?computeOutputId=71&projectTagId=1",
    );
    expect(mocks.task).not.toHaveBeenCalled();
    expect(mocks.tasks).not.toHaveBeenCalled();
  });
});
