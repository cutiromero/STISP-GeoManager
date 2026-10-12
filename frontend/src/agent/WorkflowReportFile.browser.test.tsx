import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { agentApi } from "../api/agent";
import type { AgentWorkflowReport } from "../api/generated/types.gen";
import WorkflowReportFile from "./WorkflowReportFile";
import { workflowReport } from "./workflowReport.testFixtures";
import "./agent.css";

function Location() {
  const location = useLocation();
  return (
    <output aria-label="当前位置">
      {location.pathname}
      {location.search}
    </output>
  );
}
function show(id = "actual-workflow") {
  return render(
    <AntApp>
      <MemoryRouter>
        <WorkflowReportFile workflowId={id} projectId={2} />
        <Location />
      </MemoryRouter>
    </AntApp>,
  );
}
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(agentApi, "prepareWorkflowReport").mockResolvedValue(
    workflowReport(),
  );
});

it("prepares a durable report once and previews saved Markdown as controlled text", async () => {
  const preview = vi
    .spyOn(agentApi, "previewWorkflowReport")
    .mockResolvedValue({
      content:
        "# 生态调查报告\n实际统计得到 **4 个分区**。\n## 调查建议\n优先核对植被下降较明显的区域，并结合灌溉与土地利用记录解释变化。\n## 计算成果\n| 文件 | 内容 |\n| --- | --- |\n| zone_statistics.csv | 各分区变化统计 |\n| investigation_advice.csv | 调查顺序和建议 |",
      fileName: "ecology-analysis-report.md",
      contentType: "text/markdown",
      truncated: false,
    });
  const mounted = show();
  await screen.findByText("ecology-analysis-report.md · 2.0 KB");
  fireEvent.click(screen.getByRole("button", { name: "在线预览" }));
  await screen.findByRole("heading", { name: "生态调查报告" });
  await waitFor(() => expect(screen.getByText("4 个分区")).toBeVisible());
  mounted.rerender(
    <AntApp>
      <MemoryRouter>
        <WorkflowReportFile workflowId="actual-workflow" projectId={2} />
        <Location />
      </MemoryRouter>
    </AntApp>,
  );
  expect(agentApi.prepareWorkflowReport).toHaveBeenCalledOnce();
  expect(preview).toHaveBeenCalledWith("actual-workflow");
  await page.screenshot({
    path: "../../test-results/workflow-report-preview.png",
  });
});

it("imports the report once and displays the real project directory", async () => {
  const imported = workflowReport({
    resourceId: 310,
    resourceName: "生态调查分析报告",
    resourceLocation: "生态项目 / 数据资源 / 计算结果 / 生态调查分析报告",
  });
  const save = vi
    .spyOn(agentApi, "importWorkflowReport")
    .mockResolvedValue(imported);
  show();
  const button = await screen.findByRole("button", { name: "将报告入库" });
  fireEvent.click(button);
  fireEvent.click(button);
  await screen.findByText(imported.resourceLocation);
  expect(save).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "打开入库文档" }));
  expect(screen.getByRole("status", { name: "当前位置" })).toHaveTextContent(
    "/resources/catalog?resourceId=310&projectTagId=2",
  );
});

it("downloads the saved report with its provided filename", async () => {
  const fetchFile = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response("# 真实报告", {
      headers: { "content-type": "text/markdown" },
    }),
  );
  let filename = "";
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
    function (this: HTMLAnchorElement) {
      filename = this.download;
    },
  );
  show();
  fireEvent.click(await screen.findByRole("button", { name: "下载" }));
  await waitFor(() => expect(filename).toBe("ecology-analysis-report.md"));
  expect(fetchFile).toHaveBeenCalledWith(
    workflowReport().downloadUrl,
    expect.objectContaining({ credentials: "include" }),
  );
});

it("honors report capabilities and ignores a previous workflow's delayed response", async () => {
  let resolve!: (report: AgentWorkflowReport) => void;
  vi.mocked(agentApi.prepareWorkflowReport)
    .mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    )
    .mockResolvedValue(
      workflowReport({
        label: "新工作流报告",
        canDownload: false,
        canImport: false,
      }),
    );
  const mounted = show("previous");
  mounted.rerender(
    <AntApp>
      <MemoryRouter>
        <WorkflowReportFile workflowId="next" projectId={2} />
        <Location />
      </MemoryRouter>
    </AntApp>,
  );
  await screen.findByText("新工作流报告");
  await act(async () => resolve(workflowReport({ label: "旧工作流报告" })));
  expect(screen.queryByText("旧工作流报告")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "下载" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "将报告入库" }),
  ).not.toBeInTheDocument();
});
