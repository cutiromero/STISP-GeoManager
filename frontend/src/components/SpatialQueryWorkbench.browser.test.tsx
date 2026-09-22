import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { cloneDefaultVectorSymbolization } from "../symbolization";
import type { DataResource, LoadedVectorLayer } from "../types";
import SpatialQueryWorkbench from "./SpatialQueryWorkbench";

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
