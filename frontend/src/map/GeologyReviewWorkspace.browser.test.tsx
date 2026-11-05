import { App } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { resetProjectSession, setActiveProject } from "../projects/session";
import { agentApi } from "../api/agent";
import { workflowReport } from "../agent/workflowReport.testFixtures";
import GeologyReviewWorkspace from "./GeologyReviewWorkspace";
import {
  afterReviewMap,
  beforeReviewMap,
  reviewDifferences,
  reviewQuery,
  reviewWorkflow,
} from "./geologyReview.testFixtures";
import platformStyles from "../styles.css?inline";
import workspaceStyles from "./geology-review-workspace.css?inline";
const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ bootstrap: { map: { mapboxAccessToken: "" } } }),
}));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  requestJson: request,
}));
function Location() {
  const location = useLocation();
  return <output aria-label="当前位置">{location.pathname}</output>;
}
function show(
  projectTagId: string | null = "3",
  suggestionId: string | null = null,
) {
  return render(
    <App>
      <style>{platformStyles + workspaceStyles}</style>
      <MemoryRouter>
        <GeologyReviewWorkspace
          workflowId="review-workflow"
          projectTagId={projectTagId}
          suggestionId={suggestionId}
        />
        <Location />
      </MemoryRouter>
    </App>,
  );
}
function respond(actual = false) {
  request.mockImplementation(async (url: string) => {
    if (url.startsWith("/api/agent/workflows/review-workflow/"))
      return reviewWorkflow(actual);
    const id = Number(url.match(/resources\/(\d+)\/query/)?.[1]);
    if (id === 101) return reviewQuery(id, beforeReviewMap);
    if (id === 201) return reviewQuery(id, afterReviewMap);
    if (id === 202) return reviewQuery(id, reviewDifferences);
    throw new Error(`未预期的接口：${url}`);
  });
}
async function mapsReady(after = false) {
  const before = await screen.findByLabelText("待检查地质图地图");
  const right = screen.getByLabelText(
    after ? "修正后地质图地图" : "建议修改范围地图",
  );
  await waitFor(
    () => {
      expect(before).toHaveAttribute("aria-busy", "false");
      expect(right).toHaveAttribute("aria-busy", "false");
    },
    { timeout: 20000 },
  );
  expect(
    screen.queryByText("地图渲染失败，请刷新或核对图件后重试。"),
  ).not.toBeInTheDocument();
  return { before, right };
}
beforeEach(() => {
  vi.restoreAllMocks();
  request.mockReset();
  resetProjectSession();
  setActiveProject("3");
  respond();
});

it("批准前只查询待检查图，右图显示相同本地矢量和真实建议范围，无底图请求", async () => {
  const worker = vi.spyOn(window, "Worker");
  show();
  await mapsReady();
  expect(screen.getByText("建议修改，尚未执行")).toBeVisible();
  expect(screen.queryByText("修正后地质图")).not.toBeInTheDocument();
  const units = document.querySelectorAll('[data-layer="geological-units"]');
  expect(units).toHaveLength(2);
  expect(units[0]!.innerHTML).toBe(units[1]!.innerHTML);
  expect(document.querySelector('[class*="mapbox"], canvas')).toBeNull();
  const queries = request.mock.calls.filter(([url]) =>
    String(url).includes("/query/"),
  );
  expect(queries).toHaveLength(1);
  expect(queries[0]![0]).toBe("/api/catalog/resources/101/query/");
  expect(
    request.mock.calls.every(
      ([url, options]) =>
        !(options as { method?: string } | undefined)?.method ||
        String(url).endsWith("/query/"),
    ),
  ).toBe(true);
  const remoteTiles = performance
    .getEntriesByType("resource")
    .filter((entry) =>
      /api\.mapbox\.com\/(styles|v4)|tianditu|tiles\.mapbox/.test(entry.name),
    );
  expect(remoteTiles).toHaveLength(0);
  expect(worker).not.toHaveBeenCalled();
  await page.screenshot({
    path: "../../test-results/geology-map-preview-desktop.png",
    animations: "disabled",
  });
});

it.each(["no_changes", "requires_evidence"])(
  "检查完成%s只读取并展示未修改原图，不伪造修正成果",
  async (kind) => {
    vi.spyOn(agentApi, "prepareWorkflowReport").mockResolvedValue(
      workflowReport({ label: "检查报告" }),
    );
    const workflow = reviewWorkflow();
    workflow.status = "succeeded";
    workflow.modificationReview = undefined;
    workflow.plan.reviewOutcome = { kind, checkTaskId: "actual-check" };
    request.mockImplementation(async (url: string) => {
      if (url.startsWith("/api/agent/workflows/review-workflow/"))
        return workflow;
      if (url === "/api/catalog/resources/101/query/")
        return reviewQuery(101, beforeReviewMap);
      throw new Error(`未预期的接口：${url}`);
    });
    show();
    const before = await screen.findByLabelText("待检查地质图地图");
    const unchanged = screen.getByLabelText("检查后原图地图");
    await waitFor(
      () => {
        expect(before).toHaveAttribute("aria-busy", "false");
        expect(unchanged).toHaveAttribute("aria-busy", "false");
      },
      { timeout: 20000 },
    );
    expect(
      screen.getByText(
        kind === "no_changes"
          ? "检查已完成，未修改地图"
          : "检查已完成，待补充证据",
      ),
    ).toBeVisible();
    expect(screen.queryByLabelText("修正后地质图地图")).not.toBeInTheDocument();
    expect(screen.queryByText("建议修改，尚未执行")).not.toBeInTheDocument();
    expect(screen.queryByText("实际修改范围")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /定位修改处/ }),
    ).not.toBeInTheDocument();
    expect(
      request.mock.calls.filter(([url]) => String(url).endsWith("/query/")),
    ).toHaveLength(1);
    const units = document.querySelectorAll('[data-layer="geological-units"]');
    expect(units).toHaveLength(2);
    expect(units[0]!.innerHTML).toBe(units[1]!.innerHTML);
  },
);

it("真实三份图件使用统一配色，点击同一对象的不同修改可区分并同步定位缩放", async () => {
  respond(true);
  show();
  const canvases = await mapsReady(true);
  expect(screen.getByText("真实修正结果")).toBeVisible();
  expect(
    request.mock.calls
      .filter(([url]) => String(url).includes("/query/"))
      .map(([url]) => url)
      .sort(),
  ).toEqual([
    "/api/catalog/resources/101/query/",
    "/api/catalog/resources/201/query/",
    "/api/catalog/resources/202/query/",
  ]);
  const vectors = screen.getAllByRole("group", { name: "本地矢量图层" });
  const oldView = vectors[0]!.getAttribute("viewBox");
  fireEvent.click(screen.getAllByRole("button", { name: "放大地图" })[0]!);
  expect(vectors[0]!.getAttribute("viewBox")).not.toBe(oldView);
  expect(vectors[0]!.getAttribute("viewBox")).toBe(
    vectors[1]!.getAttribute("viewBox"),
  );
  const ageButton = screen.getByRole("button", { name: /更新地层时代/ });
  fireEvent.click(ageButton);
  expect(ageButton).toHaveClass("is-selected");
  expect(screen.getByText("早白垩世")).toBeVisible();
  expect(screen.getByText("晚三叠世")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /定位修改处/ }));
  const vector = canvases.before.querySelector("svg")!;
  expect(vector).toHaveAttribute(
    "viewBox",
    vectors[1]!.getAttribute("viewBox"),
  );
  const difference = vector.querySelectorAll(
    '[data-layer="actual-differences"] g',
  )[0]!;
  fireEvent.click(difference);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /填补内部漏填/ })).toHaveClass(
      "is-selected",
    ),
  );
  expect(screen.getByText("未分类空白")).toBeVisible();
  await page.screenshot({
    path: "../../test-results/geology-map-result-desktop.png",
    animations: "disabled",
  });
});

it("完成后的建议链接和刷新均恢复同一条实际修改", async () => {
  respond(true);
  show("3", "suggest-age");
  await mapsReady(true);
  expect(screen.getByRole("button", { name: /更新地层时代/ })).toHaveClass(
    "is-selected",
  );
  fireEvent.click(screen.getByRole("button", { name: /刷新结果/ }));
  await mapsReady(true);
  expect(screen.getByRole("button", { name: /更新地层时代/ })).toHaveClass(
    "is-selected",
  );
  expect(
    request.mock.calls.filter(([url]) =>
      String(url).startsWith("/api/agent/workflows/review-workflow/"),
    ),
  ).toHaveLength(2);
});

it("缺少批准记录时不查询修正成果，批准后入库未齐时给出明确反馈", async () => {
  const missingApproval = reviewWorkflow(true);
  missingApproval.modificationReview!.approvedSuggestionIds = [];
  request.mockResolvedValueOnce(missingApproval);
  const first = show();
  expect(
    await screen.findByText("修正成果缺少已保存的批准记录，请先核对任务状态"),
  ).toBeVisible();
  expect(request).toHaveBeenCalledTimes(1);
  first.unmount();
  request.mockReset();
  const partial = reviewWorkflow(true);
  partial.plan.stages = [
    {
      identifier: "geology-map-correct",
      outputs: [{ key: "corrected", resourceId: 201 }],
    },
  ];
  request.mockResolvedValueOnce(partial);
  show();
  expect(
    await screen.findByText("修正结果与实际修改范围尚未全部就绪，请稍后刷新"),
  ).toBeVisible();
  expect(request).toHaveBeenCalledTimes(1);
});

it("拒绝跨项目入口及资源查询失败或截断，不展示不完整地图", async () => {
  const cross = show("4");
  expect(
    await screen.findByText("请切换到检查任务所属项目后查看"),
  ).toBeVisible();
  expect(request).not.toHaveBeenCalled();
  cross.unmount();
  request.mockResolvedValueOnce({ ...reviewWorkflow(), projectId: 4 });
  const mismatch = show(null);
  expect(
    await screen.findByText("检查任务不属于当前项目，请切换项目后查看"),
  ).toBeVisible();
  expect(request).toHaveBeenCalledTimes(1);
  mismatch.unmount();
  request.mockReset();
  request
    .mockResolvedValueOnce(reviewWorkflow())
    .mockRejectedValueOnce(
      Object.assign(new Error("无权查看此资源"), { status: 403 }),
    );
  const denied = show();
  expect(await screen.findByText("无权查看此资源")).toBeVisible();
  expect(screen.queryByLabelText("待检查地质图地图")).not.toBeInTheDocument();
  denied.unmount();
  request.mockReset();
  request.mockResolvedValueOnce(reviewWorkflow()).mockResolvedValueOnce({
    ...reviewQuery(101, beforeReviewMap),
    limitExceeded: true,
  });
  show();
  expect(
    await screen.findByText("图件超过双图预览范围，请缩小检查范围后查看"),
  ).toBeVisible();
  expect(screen.queryByLabelText("待检查地质图地图")).not.toBeInTheDocument();
});

it("390像素下地图、说明与定位操作可用，并可返回对话", async () => {
  await page.viewport(390, 900);
  try {
    respond(true);
    const view = show();
    await mapsReady(true);
    expect(view.container.scrollWidth).toBeLessThanOrEqual(390);
    for (const card of view.container.querySelectorAll<HTMLElement>(
      ".geology-review-map-area, .geology-review-map-inspector",
    ))
      expect(card.getBoundingClientRect().right).toBeLessThanOrEqual(390);
    await page.screenshot({
      path: "../../test-results/geology-map-result-390.png",
      animations: "disabled",
      fullPage: true,
    });
    screen.getByText("实际修改了哪里").scrollIntoView({ block: "start" });
    await page.screenshot({
      path: "../../test-results/geology-map-inspector-390.png",
      animations: "disabled",
      fullPage: true,
    });
    fireEvent.click(screen.getByRole("button", { name: /返回对话/ }));
    expect(screen.getByLabelText("当前位置").textContent).toBe(
      "/agent/workbench",
    );
  } finally {
    await page.viewport(1600, 900);
  }
});
