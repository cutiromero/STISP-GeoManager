import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { cloneDefaultVectorSymbolization } from "../symbolization";
import { workspacePanelTheme } from "../theme";
import type { DataResource, LoadedVectorLayer } from "../types";
import SpatialQueryWorkbench from "./SpatialQueryWorkbench";
import "../styles.css";

const resource: DataResource = {
  id: 10,
  name: "已加载数据",
  code: "loaded",
  dataType: "vector",
  category: null,
  source: "",
  provider: "",
  dataDate: null,
  spatialExtent: "",
  coordinateSystem: "EPSG:4326",
  fileFormat: "GPKG",
  description: "",
  qualityNote: "",
  status: "active",
  isQueryable: true,
  isRenderable: true,
  updatedAt: "2026-09-18",
};
const layer: LoadedVectorLayer = {
  id: "loaded-layer",
  name: "已加载图层",
  layerType: "vector",
  sourceResource: resource,
  geojson: { type: "FeatureCollection", features: [] },
  geometryType: "Point",
  visible: false,
  summary: "",
  metadata: {},
  symbolization: cloneDefaultVectorSymbolization(),
  fields: [],
};

function props(): ComponentProps<typeof SpatialQueryWorkbench> {
  return {
    layers: [layer],
    selectedResource: resource,
    selectedResourceProfile: {
      resource,
      fields: [],
      featureCount: 0,
      geometryType: "Point",
      bounds: [],
    },
    selectedLayer: null,
    spatialFilter: {
      mode: "rectangle",
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [0, 0],
            [1, 0],
            [1, 1],
            [0, 0],
          ],
        ],
      },
    },
    exportClipGeometry: null,
    activeDraw: null,
    spatialQuerying: false,
    spatialQueryResult: null,
    canExportData: false,
    exportTileZoomRange: { min: 0, max: 12 },
    canUseCurrentViewRange: true,
    canUseSelectedLayerRange: true,
    loadingResourceProfile: false,
    onSelectTargetResource: vi.fn(),
    onSelectTargetLayer: vi.fn(),
    onStartQueryDraw: vi.fn(),
    onClearSpatialFilter: vi.fn(),
    onImportSpatialFilter: vi.fn(),
    onUseCurrentViewRange: vi.fn(),
    onUseSelectedLayerRange: vi.fn(),
    onRunSpatialQuery: vi.fn(),
    onLoadSpatialResult: vi.fn(),
    onLocateSpatialResult: vi.fn(),
    onOpenSpatialResultTable: vi.fn(),
    onExportSpatialResult: vi.fn(),
    onClearSpatialResult: vi.fn(),
    onExportMapPng: vi.fn(),
  };
}

describe("spatial query loaded targets", () => {
  it("deduplicates loaded resources, includes hidden layers and excludes nonqueryable/local sources", async () => {
    const input = props();
    input.layers = [
      layer,
      { ...layer, id: "duplicate" },
      {
        ...layer,
        id: "disabled",
        sourceResource: {
          ...resource,
          id: 11,
          name: "不可查询",
          isQueryable: false,
        },
      },
      {
        ...layer,
        id: "local",
        sourceResource: { ...resource, id: -1, name: "本地绘图" },
      },
    ];
    render(
      <AntApp>
        <SpatialQueryWorkbench {...input} />
      </AntApp>,
    );
    fireEvent.mouseDown(
      screen.getByRole("combobox", { name: "选择已加载的矢量资源" }),
    );
    await waitFor(() =>
      expect(document.querySelectorAll(".ant-select-item-option")).toHaveLength(
        1,
      ),
    );
    expect(
      document.querySelector(".ant-select-item-option-content")?.textContent,
    ).toBe("已加载数据");
    expect(screen.getByRole("button", { name: /执行查询/ })).toBeEnabled();
  });

  it("disables queries when the selected source is removed or was never loaded", () => {
    const input = props();
    const view = render(
      <AntApp>
        <SpatialQueryWorkbench {...input} />
      </AntApp>,
    );
    expect(screen.getByRole("button", { name: /执行查询/ })).toBeEnabled();
    view.rerender(
      <AntApp>
        <SpatialQueryWorkbench {...input} layers={[]} />
      </AntApp>,
    );
    expect(screen.getByRole("button", { name: /执行查询/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /执行查询/ }));
    expect(input.onRunSpatialQuery).not.toHaveBeenCalled();
  });
});

describe("spatial query responsive layout", () => {
  it.each([
    { viewport: 1920, height: 1080, panelWidth: 1120 },
    { viewport: 1537, height: 600, panelWidth: 820 },
    { viewport: 1280, height: 720, panelWidth: 680 },
    { viewport: 1024, height: 650, panelWidth: 500 },
    { viewport: 390, height: 844, panelWidth: 358 },
  ])(
    "keeps controls separated in a $viewport px window and $panelWidth px panel",
    async ({ viewport, height, panelWidth }) => {
      await page.viewport(viewport, height);
      try {
        const input = props();
        const view = render(
          <ConfigProvider theme={workspacePanelTheme}>
            <AntApp>
              <aside
                className="floating-panel-bottom spatial-workbench-panel-open"
                style={{
                  left: 16,
                  right: "auto",
                  width: panelWidth,
                  height: 268,
                }}
              >
                <SpatialQueryWorkbench {...input} />
              </aside>
            </AntApp>
          </ConfigProvider>,
        );
        const grid = view.container.querySelector<HTMLElement>(
          ".spatial-workbench-grid",
        )!;
        const tools = view.container.querySelector<HTMLElement>(
          ".spatial-range-tools",
        )!;
        const metrics = view.container.querySelector<HTMLElement>(
          ".spatial-workbench-meta",
        )!;
        await waitFor(() => {
          expect(grid.clientWidth).toBeGreaterThan(100);
          expect(metrics.getBoundingClientRect().top).toBeGreaterThanOrEqual(
            tools.getBoundingClientRect().bottom - 1,
          );
        });
        expect(grid.scrollWidth).toBeLessThanOrEqual(grid.clientWidth + 1);
        for (const section of grid.querySelectorAll<HTMLElement>(
          ".spatial-workbench-section",
        )) {
          expect(section.scrollWidth).toBeLessThanOrEqual(
            section.clientWidth + 1,
          );
          for (const child of section.children) {
            expect(child.getBoundingClientRect().bottom).toBeLessThanOrEqual(
              section.getBoundingClientRect().bottom + 1,
            );
          }
          const heading = section.querySelector<HTMLElement>(
            ".spatial-section-heading",
          )!;
          const title = heading.querySelector<HTMLElement>(".ant-typography")!;
          expect(title.getBoundingClientRect().height).toBeLessThan(30);
          expect(title.getBoundingClientRect().right).toBeLessThanOrEqual(
            section.getBoundingClientRect().right,
          );
        }
        await page.screenshot({
          path: `../../test-results/spatial-workbench-${viewport}.png`,
          animations: "disabled",
          fullPage: true,
        });
        if (panelWidth <= 700) {
          expect(grid.scrollHeight).toBeGreaterThan(grid.clientHeight);
          grid.scrollTop = grid.scrollHeight;
          expect(grid.scrollTop).toBeGreaterThan(0);
          await page.screenshot({
            path: `../../test-results/spatial-workbench-${viewport}-scrolled.png`,
            animations: "disabled",
            fullPage: true,
          });
        }
        view.unmount();
      } finally {
        await page.viewport(1600, 900);
      }
    },
  );
});
