import {
  AimOutlined,
  BarChartOutlined,
  BulbOutlined,
  CameraOutlined,
  ClockCircleOutlined,
  CloseOutlined,
  DownloadOutlined,
  InfoCircleOutlined,
  TableOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import {
  App,
  Button,
  Descriptions,
  Empty,
  InputNumber,
  Segmented,
  Select,
  Space,
  Tabs,
  Tag,
  Typography,
} from "antd";
import type {
  MapImageExportFormat,
  MapImageExportOptions,
  TileZoomRange,
} from "../map/mapExport";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { DrawMode } from "../map/spatialDraw";
import type { GeoJsonGeometry, LoadedLayer, SpatialFilter } from "../types";
import { downloadBlob } from "../utils/download";
import { resourceSpatialExtent } from "../utils/resources";

type DrawPurpose = "query";

interface Props {
  selectedLayer: LoadedLayer | null;
  spatialFilter: SpatialFilter | null;
  exportClipGeometry: GeoJsonGeometry | null;
  activeDraw: { purpose: DrawPurpose; mode: NonNullable<DrawMode> } | null;
  canUseAiInterpretation: boolean;
  canExportMap: boolean;
  exportTileZoomRange: TileZoomRange;
  onStartQueryDraw: (mode: DrawMode | null) => void;
  onClearSpatialFilter: () => void;
  onImportSpatialFilter: (filter: SpatialFilter) => void;
  onExportMapPng: (options: MapImageExportOptions) => Promise<void>;
}

export default function WorkspaceBottomPanel({
  selectedLayer,
  spatialFilter,
  exportClipGeometry,
  activeDraw,
  canUseAiInterpretation,
  canExportMap,
  exportTileZoomRange,
  onStartQueryDraw,
  onClearSpatialFilter,
  onImportSpatialFilter,
  onExportMapPng,
}: Props) {
  const english = useEnglish();
  const currentGeometry = spatialFilter?.geometry ?? exportClipGeometry;
  return (
    <Tabs
      className="workspace-bottom-tabs"
      size="small"
      items={[
        {
          key: "spatial",
          label: (
            <span className="tab-label">
              <AimOutlined style={{ fontSize: 14 }} />
              {english ? "Spatial query" : "空间查询"}
            </span>
          ),
          children: (
            <SpatialQueryPanel
              spatialFilter={spatialFilter}
              exportClipGeometry={exportClipGeometry}
              activeDraw={activeDraw}
              onStartQueryDraw={onStartQueryDraw}
              onClearSpatialFilter={onClearSpatialFilter}
              onImportSpatialFilter={onImportSpatialFilter}
            />
          ),
        },
        {
          key: "estimate",
          label: (
            <span className="tab-label">
              <BarChartOutlined style={{ fontSize: 14 }} />
              {english ? "Hit estimate" : "命中预估"}
            </span>
          ),
          children: <HitEstimatePanel selectedLayer={selectedLayer} />,
        },
        {
          key: "result",
          label: (
            <span className="tab-label">
              <TableOutlined style={{ fontSize: 14 }} />
              {english ? "Results" : "结果"}
            </span>
          ),
          children: <MetadataPanel layer={selectedLayer} />,
        },
        {
          key: "time",
          label: (
            <span className="tab-label">
              <ClockCircleOutlined style={{ fontSize: 14 }} />
              {english ? "Time" : "时间"}
            </span>
          ),
          children: (
            <BottomPlaceholderPanel
              title={english ? "Time filter" : "时间筛选"}
              description={
                english
                  ? "Time ranges, monitoring periods, and time-series result links will be connected here."
                  : "后续在这里接入时间范围、监测周期和时序结果联动。"
              }
            />
          ),
        },
        {
          key: "legend",
          label: (
            <span className="tab-label">
              <InfoCircleOutlined style={{ fontSize: 14 }} />
              {english ? "Legend" : "图例"}
            </span>
          ),
          children: <LegendPlaceholderPanel />,
        },
        ...(canUseAiInterpretation
          ? [
              {
                key: "ai",
                label: (
                  <span className="tab-label">
                    <BulbOutlined style={{ fontSize: 14 }} />
                    {english ? "AI interpretation" : "AI智能解译"}
                  </span>
                ),
                children: (
                  <BottomPlaceholderPanel
                    title={english ? "AI interpretation" : "AI智能解译"}
                    description={
                      english
                        ? "Model selection, interpretation jobs, and result write-back will be connected here."
                        : "后续在这里接入模型选择、解译任务和结果回写。"
                    }
                  />
                ),
              },
            ]
          : []),
        ...(canExportMap
          ? [
              {
                key: "map-export",
                label: (
                  <span className="tab-label">
                    <CameraOutlined style={{ fontSize: 14 }} />
                    {english ? "Map export" : "地图导出"}
                  </span>
                ),
                children: (
                  <MapExportPanel
                    hasRange={Boolean(currentGeometry)}
                    tileZoomRange={exportTileZoomRange}
                    onExportMapPng={onExportMapPng}
                  />
                ),
              },
            ]
          : []),
      ]}
    />
  );
}

function SpatialQueryPanel({
  spatialFilter,
  exportClipGeometry,
  activeDraw,
  onStartQueryDraw,
  onClearSpatialFilter,
  onImportSpatialFilter,
}: Omit<
  Props,
  | "selectedLayer"
  | "canUseAiInterpretation"
  | "canExportMap"
  | "exportTileZoomRange"
  | "onExportMapPng"
>) {
  const english = useEnglish();
  const currentGeometry = spatialFilter?.geometry ?? exportClipGeometry;
  const rangeLabel = spatialFilter
    ? english
      ? `${spatialModeName(spatialFilter.mode, true)} drawn`
      : `已绘制${spatialModeName(spatialFilter.mode)}`
    : currentGeometry
      ? english
        ? "Area set"
        : "已设置范围"
      : english
        ? "No area set"
        : "未设置范围";

  return (
    <div className="spatial-query-grid">
      <section className="spatial-query-region spatial-query-tools">
        <div className="bottom-region-heading">
          <span>
            <AimOutlined style={{ fontSize: 15 }} />
            <strong>{english ? "Area tools" : "范围工具"}</strong>
          </span>
          <Tag color={currentGeometry ? "green" : "default"}>{rangeLabel}</Tag>
        </div>
        <DrawingPanel
          spatialFilter={spatialFilter}
          exportClipGeometry={exportClipGeometry}
          activeDraw={activeDraw}
          onStartQueryDraw={onStartQueryDraw}
          onClearSpatialFilter={onClearSpatialFilter}
          onImportSpatialFilter={onImportSpatialFilter}
        />
      </section>
    </div>
  );
}

function HitEstimatePanel({
  selectedLayer,
}: {
  selectedLayer: LoadedLayer | null;
}) {
  const english = useEnglish();
  return (
    <section className="spatial-query-region spatial-query-insight">
      <div className="bottom-region-heading">
        <span>
          <BarChartOutlined style={{ fontSize: 15 }} />
          <strong>{english ? "Query hit estimate" : "查询命中预估"}</strong>
        </span>
        <Typography.Text type="secondary">
          {english ? "Layout placeholder only" : "当前仅为布局占位"}
        </Typography.Text>
      </div>
      <div className="spatial-insight-grid">
        <div className="spatial-layer-card">
          <Typography.Text strong>
            {selectedLayer?.name ??
              (english ? "Select a loaded layer" : "请选择已加载图层")}
          </Typography.Text>
          <Typography.Text type="secondary">
            {selectedLayer
              ? selectedLayer.summary
              : english
                ? "After an area is drawn, linked query results will appear here."
                : "绘制范围后，后续查询结果将在这里联动展示。"}
          </Typography.Text>
        </div>
        <div
          className="spatial-hit-preview"
          role="img"
          aria-label={english ? "Query hit estimate chart" : "查询命中预估图"}
        >
          <span style={{ height: "44%" }} />
          <span style={{ height: "66%" }} />
          <span style={{ height: "82%" }} />
          <span style={{ height: "56%" }} />
          <span style={{ height: "72%" }} />
          <span style={{ height: "38%" }} />
        </div>
        <div className="spatial-symbol-list">
          <span>
            <i className="spatial-symbol spatial-symbol-border" />
            {english ? "Query boundary" : "查询范围边框"}
          </span>
          <span>
            <i className="spatial-symbol" />
            {english ? "Poplar forest distribution" : "胡杨林分布"}
          </span>
          <span>
            <i className="spatial-symbol spatial-symbol-water" />
            {english ? "Hydrological monitoring" : "水文监测"}
          </span>
        </div>
      </div>
    </section>
  );
}

function MetadataPanel({ layer }: { layer: LoadedLayer | null }) {
  const english = useEnglish();
  if (!layer) {
    return (
      <Empty
        className="bottom-panel-empty"
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={english ? "Select a loaded layer" : "请选择一个已加载图层"}
      />
    );
  }

  const metadata = {
    ...layer.metadata,
    空间范围:
      layer.metadata.空间范围 ?? resourceSpatialExtent(layer.sourceResource),
  };
  const entries = Object.entries(metadata).filter(
    ([, value]) => value !== undefined && value !== "",
  );

  return (
    <section className="bottom-card-panel">
      <div className="bottom-card-heading">
        <Space size={8}>
          <InfoCircleOutlined style={{ fontSize: 15 }} />
          <Typography.Text strong>{layer.name}</Typography.Text>
          <Tag color={layer.layerType === "vector" ? "green" : "blue"}>
            {layer.layerType === "vector"
              ? english
                ? "Vector"
                : "矢量"
              : english
                ? "Raster"
                : "栅格"}
          </Tag>
        </Space>
        <Typography.Text type="secondary">{layer.summary}</Typography.Text>
      </div>
      {entries.length > 0 ? (
        <Descriptions size="small" column={1} bordered>
          {entries.map(([key, value]) => (
            <Descriptions.Item key={key} label={key}>
              {String(value ?? "-")}
            </Descriptions.Item>
          ))}
        </Descriptions>
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={english ? "No metadata" : "暂无元数据"}
        />
      )}
    </section>
  );
}

function DrawingPanel({
  spatialFilter,
  exportClipGeometry,
  activeDraw,
  onStartQueryDraw,
  onClearSpatialFilter,
  onImportSpatialFilter,
}: Omit<
  Props,
  | "selectedLayer"
  | "canUseAiInterpretation"
  | "canExportMap"
  | "exportTileZoomRange"
  | "onExportMapPng"
>) {
  const { message } = App.useApp();
  const english = useEnglish();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const currentGeometry = spatialFilter?.geometry ?? exportClipGeometry;

  async function handleImportGeojson(file: File) {
    try {
      const geometry = geometryFromGeojson(JSON.parse(await file.text()));
      if (!geometry) {
        message.warning(
          english
            ? "No usable polygon area was found in the GeoJSON file"
            : "GeoJSON 中未找到可用的面状范围",
        );
        return;
      }
      onImportSpatialFilter({ mode: inferSpatialMode(geometry), geometry });
      message.success(english ? "Spatial area imported" : "空间范围已导入");
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to read the GeoJSON file"
            : "GeoJSON 文件读取失败",
      );
    } finally {
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  function handleExportGeojson() {
    if (!currentGeometry) {
      message.warning(
        english
          ? "Draw or import a spatial area first"
          : "请先绘制或导入空间范围",
      );
      return;
    }
    const geojson = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: { purpose: "spatial-range" },
          geometry: currentGeometry,
        },
      ],
    };
    const blob = new Blob([JSON.stringify(geojson, null, 2)], {
      type: "application/geo+json;charset=utf-8",
    });
    downloadBlob(
      blob,
      `spatial-range-${new Date()
        .toISOString()
        .slice(0, 19)
        .replace(/[-:T]/g, "")}.geojson`,
    );
  }

  return (
    <div className="drawing-panel-grid">
      <section className="drawing-control-block">
        <div className="spatial-range-control-row">
          <Segmented
            block
            className="spatial-range-mode-selector"
            value={activeDraw?.purpose === "query" ? activeDraw.mode : "none"}
            options={[
              { label: english ? "None" : "无", value: "none" },
              { label: english ? "Rectangle" : "矩形", value: "rectangle" },
              { label: english ? "Circle" : "圆", value: "circle" },
              { label: english ? "Ellipse" : "椭圆", value: "ellipse" },
              { label: english ? "Polygon" : "多边形", value: "polygon" },
            ]}
            onChange={(nextValue) =>
              onStartQueryDraw(
                nextValue === "none" ? null : (nextValue as DrawMode),
              )
            }
          />
        </div>
        <input
          ref={fileInputRef}
          className="visually-hidden-file-input"
          type="file"
          accept=".geojson,.json,application/geo+json,application/json"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void handleImportGeojson(file);
          }}
        />
        <Space size={8} wrap className="spatial-range-actions">
          {spatialFilter && (
            <Tag color="green">
              {english
                ? `${spatialModeName(spatialFilter.mode, true)} drawn`
                : `已绘制${spatialModeName(spatialFilter.mode)}`}
            </Tag>
          )}
          {!spatialFilter && exportClipGeometry && (
            <Tag color="blue">{english ? "Set" : "已设置"}</Tag>
          )}
          <Button
            size="small"
            icon={<CloseOutlined style={{ fontSize: 13 }} />}
            disabled={!currentGeometry}
            onClick={onClearSpatialFilter}
          >
            {english ? "Clear" : "清除"}
          </Button>
          <Button
            size="small"
            icon={<UploadOutlined style={{ fontSize: 13 }} />}
            onClick={() => fileInputRef.current?.click()}
          >
            {english ? "Import spatial area" : "导入空间范围"}
          </Button>
          <Button
            size="small"
            icon={<DownloadOutlined style={{ fontSize: 13 }} />}
            disabled={!currentGeometry}
            onClick={handleExportGeojson}
          >
            {english ? "Export spatial area" : "导出空间范围"}
          </Button>
        </Space>
      </section>
    </div>
  );
}

function BottomPlaceholderPanel({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <section className="bottom-placeholder-panel">
      <Typography.Text strong>{title}</Typography.Text>
      <Typography.Text type="secondary">{description}</Typography.Text>
    </section>
  );
}

function LegendPlaceholderPanel() {
  const english = useEnglish();
  return (
    <section className="bottom-placeholder-panel legend-placeholder-panel">
      <Typography.Text strong>
        {english ? "Current legend" : "当前图例"}
      </Typography.Text>
      <div className="spatial-symbol-list spatial-symbol-list-wide">
        <span>
          <i className="spatial-symbol spatial-symbol-border" />
          {english ? "Query boundary" : "查询范围边框"}
        </span>
        <span>
          <i className="spatial-symbol" />
          {english ? "Poplar forest distribution" : "胡杨林分布"}
        </span>
        <span>
          <i className="spatial-symbol spatial-symbol-water" />
          {english ? "Hydrological monitoring" : "水文监测"}
        </span>
        <span>
          <i className="spatial-symbol spatial-symbol-risk" />
          {english ? "Risk area" : "风险区域"}
        </span>
      </div>
    </section>
  );
}

function MapExportPanel({
  hasRange,
  tileZoomRange,
  onExportMapPng,
}: {
  hasRange: boolean;
  tileZoomRange: TileZoomRange;
  onExportMapPng: (options: MapImageExportOptions) => Promise<void>;
}) {
  const english = useEnglish();
  const [format, setFormat] = useState<MapImageExportFormat>("png");
  const [dpi, setDpi] = useState(150);
  const [tileZoom, setTileZoom] = useState(8);
  const [exporting, setExporting] = useState(false);
  const tileZoomOptions = Array.from(
    { length: tileZoomRange.max - tileZoomRange.min + 1 },
    (_, index) => {
      const zoom = tileZoomRange.min + index;
      return { label: `Z${zoom}`, value: zoom };
    },
  );

  useEffect(() => {
    setTileZoom((currentZoom) =>
      Math.min(tileZoomRange.max, Math.max(tileZoomRange.min, currentZoom)),
    );
  }, [tileZoomRange.max, tileZoomRange.min]);

  async function handleExport() {
    setExporting(true);
    try {
      await onExportMapPng({ dpi, tileZoom, format });
    } finally {
      setExporting(false);
    }
  }

  return (
    <section className="bottom-placeholder-panel map-export-panel">
      <div className="map-export-copy">
        <Typography.Text strong>
          {english ? "Export 2D map image" : "导出 2D 地图图片"}
        </Typography.Text>
        <Typography.Text type="secondary">
          {english
            ? "Use the area tools under Spatial Query, then generate an image at the selected DPI and tile zoom."
            : "使用“空间查询”中的范围工具划定导出范围，按指定 DPI 与瓦片等级生成图片。"}
        </Typography.Text>
      </div>
      <div className="map-export-controls">
        <label className="map-export-field">
          <span>{english ? "Format" : "格式"}</span>
          <Select
            size="small"
            value={format}
            options={[
              { label: "PNG", value: "png" },
              { label: "JPG", value: "jpg" },
            ]}
            onChange={setFormat}
          />
        </label>
        <label className="map-export-field">
          <span>DPI</span>
          <InputNumber
            size="small"
            min={72}
            max={600}
            step={1}
            value={dpi}
            onChange={(nextValue) => {
              if (typeof nextValue === "number") {
                setDpi(nextValue);
              }
            }}
          />
        </label>
        <label className="map-export-field">
          <span>{english ? "Tile zoom" : "瓦片等级"}</span>
          <Select
            size="small"
            value={tileZoom}
            options={tileZoomOptions}
            onChange={setTileZoom}
          />
        </label>
        <Tag color={hasRange ? "green" : "default"}>
          {hasRange
            ? english
              ? "Area defined"
              : "已划定范围"
            : english
              ? "No area defined"
              : "未划定范围"}
        </Tag>
        <Button
          type="primary"
          icon={<DownloadOutlined style={{ fontSize: 13 }} />}
          loading={exporting}
          disabled={!hasRange}
          onClick={() => void handleExport()}
        >
          {english ? "Export" : "导出"} {format.toUpperCase()}
        </Button>
      </div>
    </section>
  );
}

function spatialModeName(mode: SpatialFilter["mode"], english = false) {
  const names = {
    rectangle: english ? "Rectangle" : "矩形",
    circle: english ? "Circle" : "圆",
    ellipse: english ? "Ellipse" : "椭圆",
    polygon: english ? "Polygon" : "多边形",
  };
  return names[mode];
}

function useEnglish() {
  const { i18n } = useTranslation();
  return i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
}

function geometryFromGeojson(value: unknown): GeoJsonGeometry | null {
  if (!isGeojsonObject(value)) return null;
  if (isSupportedGeometry(value)) return value;
  if (value.type === "Feature" && isSupportedGeometry(value.geometry)) {
    return value.geometry;
  }
  if (value.type === "FeatureCollection" && Array.isArray(value.features)) {
    for (const feature of value.features) {
      if (isGeojsonObject(feature) && isSupportedGeometry(feature.geometry)) {
        return feature.geometry;
      }
    }
  }
  return null;
}

function isGeojsonObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isSupportedGeometry(value: unknown): value is GeoJsonGeometry {
  if (!isGeojsonObject(value)) return false;
  return (
    typeof value.type === "string" &&
    ["Polygon", "MultiPolygon"].includes(value.type) &&
    "coordinates" in value
  );
}

function inferSpatialMode(geometry: GeoJsonGeometry): SpatialFilter["mode"] {
  if (geometry.type === "Polygon" && isRectanglePolygon(geometry.coordinates)) {
    return "rectangle";
  }
  return "polygon";
}

function isRectanglePolygon(coordinates: unknown) {
  if (!Array.isArray(coordinates) || !Array.isArray(coordinates[0])) {
    return false;
  }
  return coordinates[0].length === 5;
}
