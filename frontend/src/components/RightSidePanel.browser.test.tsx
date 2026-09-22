import { fireEvent, render, screen } from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { describe, expect, it, vi } from "vitest";
import { cloneDefaultVectorSymbolization } from "../symbolization";
import { appTheme } from "../theme";
import type {
  DataResourceProfile,
  LoadedVectorLayer,
  ResourceListItem,
} from "../types";
import RightSidePanel from "./RightSidePanel";

const rasterResource = {
  id: 31,
  name: "塔里木河胡杨分类结果",
  code: "tarim-poplar-classification",
  dataType: "raster",
  domainType: "remote_sensing",
  spatialExtent: "88.32,40.07,88.41,40.17",
  coordinateSystem: "EPSG:3857",
  fileFormat: "COG",
  status: "active",
} as ResourceListItem;

const rasterProfile = {
  resource: rasterResource,
  fields: [],
  featureCount: null,
  geometryType: "Raster",
  bounds: [88.32, 40.07, 88.41, 40.17],
  raster: {
    id: 31,
    name: rasterResource.name,
    code: rasterResource.code,
    status: "ready",
    bandCount: 3,
    bounds4326: [88.32, 40.07, 88.41, 40.17],
    rasterKind: "imagery",
    sourceFormat: "GTiff",
    sourceFileSize: 24_000_000,
    processedFileSize: 18_000_000,
    sourceFileName: "tarim_rgb.tif",
    defaultRules: {
      mode: "rgb",
      bands: [3, 2, 1],
      opacity: 92,
      nodata: { enabled: true },
      stretch: { enabled: true, type: "minmax", perBand: {} },
    },
    metadata: {
      size: [12_444, 18_151],
      driver: "GTiff",
      coordinateSystem: 3857,
      bands: [
        {
          band: 1,
          type: "UInt16",
          description: "蓝光波段",
          colorInterpretation: "Blue",
          min: 112,
          max: 6240,
          isInteger: true,
        },
        {
          band: 2,
          type: "UInt16",
          description: "绿光波段",
          colorInterpretation: "Green",
          min: 98,
          max: 7180,
          isInteger: true,
        },
        {
          band: 3,
          type: "UInt16",
          description: "红光波段",
          colorInterpretation: "Red",
          min: 105,
          max: 8020,
          isInteger: true,
        },
      ],
    },
  },
} as DataResourceProfile;

function renderRasterPanel() {
  return render(
    <ConfigProvider locale={zhCN} theme={appTheme}>
      <AntApp>
        <RightSidePanel
          currentView={null}
          mapConfig={{
            defaultBasemap: "osm",
            defaultCenter: [88, 40],
            defaultZoom: 6,
            mapboxAccessToken: "",
          }}
          selectedFeature={null}
          selectedLayer={null}
          selectedResource={rasterResource}
          selectedResourceProfile={rasterProfile}
          visualizationSummary={null}
          visualizationSummaryError={null}
          visualizationSummaryLoading={false}
        />
      </AntApp>
    </ConfigProvider>,
  );
}

describe("RightSidePanel raster insight", () => {
  it("uses raster-specific overview, band and quality views", async () => {
    renderRasterPanel();

    expect(screen.getByText("栅格数据集概览")).toBeInTheDocument();
    expect(screen.getByText("像元值域（元数据）")).toBeInTheDocument();
    expect(screen.queryByText("数值字段分布")).not.toBeInTheDocument();
    expect(screen.queryByText("分类字段构成")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /波段/ }));
    expect(await screen.findByText("波段值域与数据类型")).toBeInTheDocument();
    expect(screen.getAllByText("蓝光波段").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("tab", { name: /质量/ }));
    expect(await screen.findByText("栅格可用性检查")).toBeInTheDocument();
    expect(screen.getByText("COG 预处理")).toBeInTheDocument();
    expect(screen.queryByText("第三阶段占位")).not.toBeInTheDocument();
  });
});

describe("RightSidePanel vector insight", () => {
  it("keeps field-matrix keys unique when a numeric field is also categorical", async () => {
    const resource = {
      ...rasterResource,
      id: 41,
      name: "数值分类重叠资源",
      code: "numeric-category-overlap",
      dataType: "vector",
      domainType: "vector",
      coordinateSystem: "EPSG:4326",
      fileFormat: "GPKG",
    } as ResourceListItem;
    const layer = {
      id: "overlap-layer",
      name: resource.name,
      layerType: "vector",
      sourceResource: resource,
      geojson: {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: { type: "Point", coordinates: [87, 42] },
            properties: { xiaolei: -9999 },
          },
          {
            type: "Feature",
            geometry: { type: "Point", coordinates: [88, 43] },
            properties: { xiaolei: -9999 },
          },
        ],
      },
      geometryType: "Point",
      visible: true,
      summary: "2/2 条",
      metadata: {},
      symbolization: cloneDefaultVectorSymbolization(),
      fields: [
        {
          name: "xiaolei",
          type: "integer",
          nullable: false,
          sampleValues: [-9999],
          description: "xiaolei",
        },
      ],
      query: { attributeFilters: [], spatialFilter: null },
    } as LoadedVectorLayer;
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    render(
      <ConfigProvider locale={zhCN} theme={appTheme}>
        <AntApp>
          <RightSidePanel
            currentView={null}
            mapConfig={{
              defaultBasemap: "osm",
              defaultCenter: [88, 40],
              defaultZoom: 6,
              mapboxAccessToken: "",
            }}
            selectedFeature={null}
            selectedLayer={layer}
            selectedResource={resource}
            selectedResourceProfile={null}
            visualizationSummary={null}
            visualizationSummaryError={null}
            visualizationSummaryLoading={false}
          />
        </AntApp>
      </ConfigProvider>,
    );

    fireEvent.click(screen.getByRole("tab", { name: /要素/ }));
    expect(
      await screen.findByLabelText("字段可视化热力矩阵"),
    ).toBeInTheDocument();
    expect(
      consoleError.mock.calls.some((args) =>
        args.some((arg) => typeof arg === "string" && arg.includes("same key")),
      ),
    ).toBe(false);
    consoleError.mockRestore();
  });
});
