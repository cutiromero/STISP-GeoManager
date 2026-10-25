import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import * as client from "../api/client";
import { downloadComputeFile } from "../api/compute";
import type {
  AgentWorkflowValidation,
  AgentWorkflowValidationFile,
} from "../api/generated/types.gen";
import { resetProjectSession, setActiveProject } from "../projects/session";
import WorkflowValidationPanel from "./WorkflowValidationPanel";
import "../agent/agent.css";

vi.mock("../api/compute", () => ({ downloadComputeFile: vi.fn() }));
vi.mock("../api/client", () => ({
  requestJson: vi.fn(),
  requestForm: vi.fn(),
}));

const baseUrl = "/api/agent/workflows/actual-workflow/validation/";
const file: AgentWorkflowValidationFile = {
  key: "evaluation-report",
  fileName: "独立评价说明.md",
  contentType: "text/markdown",
  sizeBytes: 1024,
  checksum: "saved-sha256",
  previewUrl: `${baseUrl}files/evaluation-report/preview/`,
  downloadUrl: `${baseUrl}files/evaluation-report/download/`,
  canDownload: true,
};
function validation(
  overrides: Partial<AgentWorkflowValidation> = {},
): AgentWorkflowValidation {
  return {
    workflowId: "actual-workflow",
    available: true,
    scope: "输入为模拟识别成果，独立评价采用隔离参考数据。",
    summary: "实际复查发现两处问题已修正。",
    sections: [
      {
        key: "checks",
        title: "规则评价",
        summary: "按实际检查记录逐项统计。",
        columns: [
          { key: "name", label: "项目" },
          { key: "value", label: "结果" },
        ],
        rows: [
          { name: "剩余问题", value: 0 },
          { name: "是否遗漏", value: false },
          { name: "未覆盖指标", value: null },
        ],
      },
    ],
    files: [file],
    ...overrides,
  };
}
function show(workflowId = "actual-workflow") {
  return render(
    <App>
      <WorkflowValidationPanel workflowId={workflowId} />
    </App>,
  );
}
function expand() {
  fireEvent.click(
    screen.getByRole("button", { name: /^(collapsed |expanded )?独立评价$/ }),
  );
}
const request = () => vi.mocked(client.requestJson);

beforeEach(() => {
  vi.restoreAllMocks();
  vi.mocked(downloadComputeFile).mockReset().mockResolvedValue(undefined);
  resetProjectSession();
  setActiveProject("3");
  request().mockReset().mockResolvedValue(validation());
});

it("reads only after expanding and preserves zero, false and undefined scalars without recomputing", async () => {
  show();
  expect(request()).not.toHaveBeenCalled();
  expand();
  await screen.findByText("实际复查发现两处问题已修正。");
  await waitFor(() =>
    expect(
      screen.getByText("输入为模拟识别成果，独立评价采用隔离参考数据。"),
    ).toBeVisible(),
  );
  const section = within(screen.getByRole("region", { name: "规则评价" }));
  expect(section.getByRole("cell", { name: "0" })).toBeVisible();
  expect(section.getByRole("cell", { name: "否" })).toBeVisible();
  expect(section.getByRole("cell", { name: "未定义" })).toBeVisible();
  expand();
  expand();
  await waitFor(() =>
    expect(request()).toHaveBeenCalledExactlyOnceWith(baseUrl),
  );
  expect(
    screen.queryByRole("button", { name: /计算|生成|入库/ }),
  ).not.toBeInTheDocument();
});

it("previews saved Markdown safely and downloads the permitted original file", async () => {
  request().mockImplementation(async (url) =>
    url === baseUrl
      ? validation()
      : {
          fileName: file.fileName,
          contentType: "text/markdown",
          truncated: true,
          content:
            "# 评价结论\n实际结果为 **两处修正**。\n<script>window.validationInjected=true</script>",
        },
  );
  show();
  expand();
  fireEvent.click(
    await screen.findByRole("button", { name: `在线预览 ${file.fileName}` }),
  );
  await screen.findByRole("heading", { name: "评价结论" });
  await waitFor(() => expect(screen.getByText("两处修正")).toBeVisible());
  expect(
    screen.getByText("<script>window.validationInjected=true</script>"),
  ).toBeVisible();
  expect(
    screen.getByText("预览已截断，完整内容见原始评价文件。"),
  ).toBeVisible();
  expect(document.querySelector(".agent-report-preview script")).toBeNull();
  expect(request()).toHaveBeenLastCalledWith(file.previewUrl);
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  fireEvent.click(
    screen.getByRole("button", { name: `下载 ${file.fileName}` }),
  );
  await waitFor(() =>
    expect(downloadComputeFile).toHaveBeenCalledExactlyOnceWith(
      file.downloadUrl,
      file.fileName,
    ),
  );
  expect(
    request().mock.calls.every(
      ([, options]) => !options?.method || options.method === "GET",
    ),
  ).toBe(true);
});

it("uses the server download capability and offers no preview for other file types", async () => {
  request().mockResolvedValue(
    validation({
      files: [
        {
          ...file,
          fileName: "规则统计.csv",
          contentType: "text/csv",
          previewUrl: null,
          canDownload: false,
        },
      ],
    }),
  );
  show();
  expand();
  await screen.findByText("规则统计.csv");
  expect(
    screen.queryByRole("button", { name: /在线预览|下载/ }),
  ).not.toBeInTheDocument();
  expect(downloadComputeFile).not.toHaveBeenCalled();
});

it("explains an unavailable evaluation without substituting workflow statistics", async () => {
  request().mockResolvedValue(
    validation({
      available: false,
      summary: "当前任务尚未登记独立评价。",
      sections: [],
      files: [],
    }),
  );
  show();
  expand();
  await screen.findByText("当前任务尚未登记独立评价。");
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(request()).toHaveBeenCalledExactlyOnceWith(baseUrl);
});

it("retries failed reads and file previews through the same read-only endpoints", async () => {
  request().mockRejectedValueOnce(new Error("评价暂时无法读取"));
  show();
  expand();
  await screen.findByText("评价暂时无法读取");
  fireEvent.click(screen.getByRole("button", { name: "重试读取" }));
  const previewButton = await screen.findByRole("button", {
    name: `在线预览 ${file.fileName}`,
  });
  request().mockRejectedValueOnce(new Error("评价文件校验失败"));
  fireEvent.click(previewButton);
  await screen.findByText("评价文件校验失败");
  request().mockResolvedValueOnce({
    fileName: file.fileName,
    contentType: "text/markdown",
    truncated: false,
    content: "# 已保存评价",
  });
  fireEvent.click(previewButton);
  await screen.findByRole("heading", { name: "已保存评价" });
  expect(request().mock.calls.map(([url]) => url)).toEqual([
    baseUrl,
    baseUrl,
    file.previewUrl,
    file.previewUrl,
  ]);
});

it("ignores an earlier workflow response after changing the selected workflow", async () => {
  let resolveEarlier: (value: AgentWorkflowValidation) => void = () => {};
  request().mockReturnValueOnce(
    new Promise<AgentWorkflowValidation>((resolve) => {
      resolveEarlier = resolve;
    }),
  );
  const mounted = show();
  expand();
  mounted.rerender(
    <App>
      <WorkflowValidationPanel workflowId="new-workflow" />
    </App>,
  );
  expect(request()).toHaveBeenCalledOnce();
  expand();
  await screen.findByText("实际复查发现两处问题已修正。");
  await act(async () =>
    resolveEarlier(validation({ summary: "此前任务的过期评价" })),
  );
  expect(screen.queryByText("此前任务的过期评价")).not.toBeInTheDocument();
  expect(request()).toHaveBeenLastCalledWith(
    "/api/agent/workflows/new-workflow/validation/",
  );
});

it("keeps wide validation tables and file controls within a phone viewport", async () => {
  await page.viewport(390, 844);
  request().mockResolvedValue(
    validation({
      sections: [
        {
          key: "wide",
          title: "岩性对照",
          summary: "同一口径比较。",
          columns: [
            { key: "method", label: "方法" },
            { key: "metric", label: "评价指标" },
            { key: "result", label: "实际结果" },
          ],
          rows: [
            {
              method: "保持原始图斑字段进行对照评价",
              metric: "独立参考下的区域统计指标",
              result: "0.92",
            },
          ],
        },
      ],
      files: [
        { ...file, fileName: "地质多要素逻辑推理独立评价与置信度标定说明.md" },
      ],
    }),
  );
  try {
    show();
    expand();
    await screen.findByText("岩性对照");
    await waitFor(() => expect(screen.getByText("岩性对照")).toBeVisible());
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
      window.innerWidth,
    );
    await page.screenshot({
      path: "../../test-results/workflow-validation-390.png",
      animations: "disabled",
    });
  } finally {
    await page.viewport(1600, 900);
  }
});
