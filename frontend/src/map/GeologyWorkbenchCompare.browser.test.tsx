import { App } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import mapboxgl from "mapbox-gl";
import { useState } from "react";
import { MemoryRouter, useSearchParams } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import type { ResourceProfileResponse } from "../api/generated/types.gen";
import { resetProjectSession, setActiveProject } from "../projects/session";
import { createEmptyLayerGroup } from "../utils/layerFactory";
import GeologyWorkbenchCompare from "./GeologyWorkbenchCompare";
import {
  afterReviewMap,
  beforeReviewMap,
  reviewDifferences,
  reviewQuery,
  reviewWorkflow,
} from "./geologyReview.testFixtures";
import platformStyles from "../styles.css?inline";
import reviewStyles from "./geology-review-workspace.css?inline";
import compareStyles from "./geology-workbench-compare.css?inline";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../api/client", () => ({
  requestJson: request,
  requestForm: vi.fn(),
}));
const registered = vi.fn().mockResolvedValue(undefined);

function profile(id: number): ResourceProfileResponse {
  return {
    resource: {
      ...createEmptyLayerGroup("测试").sourceResource,
      id,
      isQueryable: true,
      name:
        id === 101 ? "待检查地质图" : id === 201 ? "修正后地质图" : "修改范围",
    },
    fields: [],
    featureCount: 2,
    geometryType: "Polygon",
    bounds: [98.4, 35.6, 98.45, 35.62],
  };
}

function Harness({ canLoad = true }: { canLoad?: boolean }) {
  const [params, setParams] = useSearchParams();
  const [names, setNames] = useState<string[]>([]);
  return (
    <div className="workspace">
      <div
        className="workspace-body workspace-body-spatial-collapsed"
        style={{ width: "100%", height: 760 }}
      >
        <style>{platformStyles + reviewStyles + compareStyles}</style>
        <aside
          className="floating-panel floating-panel-left mobile-map-panel-hidden"
          aria-label="正常图层栏"
        >
          {names.join("、")}
        </aside>
        <main className="map-stage">
          <GeologyWorkbenchCompare
            workflowId="review-workflow"
            projectId="3"
            projectTagId="3"
            suggestionId={params.get("suggestion")}
            accessToken=""
            canLoad={canLoad}
            comparisonVisible={params.get("mapMode") !== "single"}
            registerLayer={async (resourceProfile, result) => {
              await registered(resourceProfile, result);
              setNames((values) => [
                ...new Set([...values, resourceProfile.resource.name]),
              ]);
            }}
            onVisibilityChange={(visible) => {
              const next = new URLSearchParams(params);
              if (visible) next.delete("mapMode");
              else next.set("mapMode", "single");
              setParams(next);
            }}
            onSuggestionChange={(id) => {
              const next = new URLSearchParams(params);
              if (id) next.set("suggestion", id);
              else next.delete("suggestion");
              setParams(next);
            }}
          />
        </main>
        <output aria-label="当前对比位置">{params.toString()}</output>
      </div>
    </div>
  );
}

function show(initial = "/map?geologyCompare=review-workflow", canLoad = true) {
  return render(
    <App>
      <MemoryRouter initialEntries={[initial]}>
        <Harness canLoad={canLoad} />
      </MemoryRouter>
    </App>,
  );
}

async function mapsReady() {
  const before = await screen.findByLabelText("待检查地质图地图");
  const after = screen.getByLabelText("修正后地质图地图");
  await waitFor(
    () => {
      expect(before).toHaveAttribute("aria-busy", "false");
      expect(after).toHaveAttribute("aria-busy", "false");
    },
    { timeout: 20000 },
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(mapboxgl.Map.prototype, "_authenticate").mockImplementation(
    () => {},
  );
  request.mockReset();
  registered.mockClear();
  resetProjectSession();
  setActiveProject("3");
  request.mockImplementation(async (url: string) => {
    if (url.includes("/workflows/")) return reviewWorkflow(true);
    const id = Number(url.match(/resources\/(\d+)\//)?.[1]);
    if (url.endsWith("/profile/")) return profile(id);
    return reviewQuery(
      id,
      id === 101
        ? beforeReviewMap
        : id === 201
          ? afterReviewMap
          : reviewDifferences,
    );
  });
});

it("embeds synchronized real maps while registering the same catalog layers, and switches to ordinary map tools without rereading", async () => {
  const sources = vi.spyOn(mapboxgl.Map.prototype, "addSource");
  show();
  await mapsReady();
  expect(registered).toHaveBeenCalledTimes(3);
  expect(screen.getByLabelText("正常图层栏")).toHaveTextContent(
    "待检查地质图、修正后地质图、修改范围",
  );
  expect(screen.getByText("第 1 处，共 2 处")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /下一处/ }));
  expect(screen.getByText("第 2 处，共 2 处")).toBeVisible();
  expect(screen.getByLabelText("地理工作台地质成果对比")).toHaveTextContent(
    "早白垩世 → 晚三叠世",
  );
  expect(screen.getByLabelText("当前对比位置")).toHaveTextContent(
    "suggestion=suggest-age",
  );
  expect(
    sources.mock.calls.filter(([id]) => id === "geological-units"),
  ).toHaveLength(2);
  const calls = request.mock.calls.length;
  fireEvent.click(
    screen.getByText("单图", { selector: ".ant-segmented-item-label" }),
  );
  expect(screen.queryByLabelText("待检查地质图地图")).not.toBeInTheDocument();
  expect(screen.getByLabelText("正常图层栏")).toHaveTextContent("修改范围");
  expect(screen.getByLabelText("当前对比位置")).toHaveTextContent(
    "mapMode=single",
  );
  fireEvent.click(
    screen.getByText("前后对比", { selector: ".ant-segmented-item-label" }),
  );
  await mapsReady();
  expect(screen.getByText("第 2 处，共 2 处")).toBeVisible();
  expect(request).toHaveBeenCalledTimes(calls);
  expect(screen.getByRole("link", { name: "独立对比页" })).toHaveAttribute(
    "href",
    "/map?geologyReview=review-workflow&projectTagId=3&suggestion=suggest-age",
  );
  await page.screenshot({
    path: "../../test-results/geology-workbench-compare-desktop.png",
    animations: "disabled",
  });
});

it("restores the selected actual change from the URL, refreshes the saved workflow, and keeps the same resource names", async () => {
  show("/map?geologyCompare=review-workflow&suggestion=suggest-age");
  await mapsReady();
  expect(screen.getByText("第 2 处，共 2 处")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /刷新成果/ }));
  await mapsReady();
  expect(screen.getByText("第 2 处，共 2 处")).toBeVisible();
  expect(screen.getByLabelText("正常图层栏")).toHaveTextContent(
    "待检查地质图、修正后地质图、修改范围",
  );
  expect(
    request.mock.calls.filter(([url]) => String(url).includes("/workflows/")),
  ).toHaveLength(2);
});

it("does not read protected resources when the user cannot load vectors", async () => {
  show(undefined, false);
  expect(
    await screen.findByText("当前账号没有查询和加载检查成果图层的权限"),
  ).toBeVisible();
  expect(request).not.toHaveBeenCalled();
  expect(registered).not.toHaveBeenCalled();
});

it("keeps both maps and navigation within a narrow viewport", async () => {
  await page.viewport(390, 900);
  try {
    const view = show();
    await mapsReady();
    const comparison = screen.getByLabelText("地理工作台地质成果对比");
    expect(comparison.getBoundingClientRect().right).toBeLessThanOrEqual(390);
    expect(view.container.scrollWidth).toBeLessThanOrEqual(390);
    expect(screen.getByRole("button", { name: /下一处/ })).toBeVisible();
    await page.screenshot({
      path: "../../test-results/geology-workbench-compare-390.png",
      animations: "disabled",
    });
  } finally {
    await page.viewport(1600, 900);
  }
});
