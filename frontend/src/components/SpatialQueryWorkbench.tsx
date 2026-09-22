import {
  AimOutlined,
  CloseOutlined,
  DatabaseOutlined,
  DownloadOutlined,
  FileSearchOutlined,
  FolderOpenOutlined,
  LoadingOutlined,
  PushpinOutlined,
  TableOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import {
  App,
  Button,
  Empty,
  Segmented,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type React from "react";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import i18n from "../i18n";
import type { MapImageExportOptions, TileZoomRange } from "../map/mapExport";
import type { DrawMode } from "../map/spatialDraw";
import type {
  DataResourceProfile,
  GeoJsonGeometry,
  LoadedLayer,
  ResourceListItem,
  SpatialFilter,
} from "../types";
import { downloadBlob } from "../utils/download";
import { extractCoordinates, rectangleGeometry } from "../utils/geometry";
import { resourceSpatialExtent } from "../utils/resources";
import {
  isQueryableLoadedLayer,
  loadedQueryResources,
} from "../utils/spatialQueryTargets";

export type SpatialQueryTarget = "selectedResource" | "selectedLayer";

export interface SpatialQueryWorkbenchResult {
  id: string;
  target: SpatialQueryTarget;
  targetName: string;
  resourceName: string;
  rangeMode: SpatialFilter["mode"] | null;
  totalCount: number;
  returnedCount: number;
  limit: number;
  limitExceeded: boolean;
  bounds: number[];
  elapsedMs: number;
  warningCount: number;
  loadedLayerName?: string | null;
}

type DrawPurpose = "query";

interface Props {
  layers: LoadedLayer[];
  selectedResource: ResourceListItem | null;
  selectedResourceProfile: DataResourceProfile | null;
  selectedLayer: LoadedLayer | null;
  spatialFilter: SpatialFilter | null;
  exportClipGeometry: GeoJsonGeometry | null;
  activeDraw: { purpose: DrawPurpose; mode: NonNullable<DrawMode> } | null;
  spatialQuerying: boolean;
  spatialQueryResult: SpatialQueryWorkbenchResult | null;
  canExportData: boolean;
  exportTileZoomRange: TileZoomRange;
  canUseCurrentViewRange: boolean;
  canUseSelectedLayerRange: boolean;
  loadingResourceProfile: boolean;
  onSelectTargetResource: (resourceId: number | null) => Promise<void> | void;
  onSelectTargetLayer: (layerId: string | null) => void;
  onStartQueryDraw: (mode: DrawMode | null) => void;
  onClearSpatialFilter: () => void;
  onImportSpatialFilter: (filter: SpatialFilter) => void;
  onUseCurrentViewRange: () => void;
  onUseSelectedLayerRange: () => void;
  onRunSpatialQuery: (target: SpatialQueryTarget) => Promise<void> | void;
  onLoadSpatialResult: () => void;
  onLocateSpatialResult: () => void;
  onOpenSpatialResultTable: () => void;
  onExportSpatialResult: () => void;
  onClearSpatialResult: () => void;
  onExportMapPng: (options: MapImageExportOptions) => Promise<void>;
}

export default function SpatialQueryWorkbench({
  layers,
  selectedResource,
  selectedResourceProfile,
  selectedLayer,
  spatialFilter,
  exportClipGeometry,
  activeDraw,
  spatialQuerying,
  spatialQueryResult,
  canExportData,
  exportTileZoomRange,
  canUseCurrentViewRange,
  canUseSelectedLayerRange,
  loadingResourceProfile,
  onSelectTargetResource,
  onSelectTargetLayer,
  onStartQueryDraw,
  onClearSpatialFilter,
  onImportSpatialFilter,
  onUseCurrentViewRange,
  onUseSelectedLayerRange,
  onRunSpatialQuery,
  onLoadSpatialResult,
  onLocateSpatialResult,
  onOpenSpatialResultTable,
  onExportSpatialResult,
  onClearSpatialResult,
  onExportMapPng,
}: Props) {
  const { t } = useTranslation();
  const [target, setTarget] = useState<SpatialQueryTarget>("selectedResource");
  const currentGeometry = spatialFilter?.geometry ?? exportClipGeometry;
  const resources = useMemo(() => loadedQueryResources(layers), [layers]);
  const loadedResource =
    resources.find((resource) => resource.id === selectedResource?.id) ?? null;
  const loadedLayer =
    layers.find(
      (layer) =>
        layer.id === selectedLayer?.id && isQueryableLoadedLayer(layer),
    ) ?? null;
  const targetStates = useMemo(
    () =>
      spatialTargetStates(loadedResource, selectedResourceProfile, loadedLayer),
    [loadedLayer, loadedResource, selectedResourceProfile],
  );
  const activeTarget = targetStates[target];

  return (
    <section className="spatial-workbench" aria-label={t("spatial.workbench")}>
      <div className="spatial-workbench-heading">
        <span>
          <AimOutlined style={{ fontSize: 15 }} />
          <Typography.Text strong>{t("spatial.workbench")}</Typography.Text>
        </span>
        <Typography.Text type="secondary">
          {t("spatial.workbenchDescription")}
        </Typography.Text>
      </div>
      <div className="spatial-workbench-grid">
        <RangeSection
          spatialFilter={spatialFilter}
          exportClipGeometry={exportClipGeometry}
          activeDraw={activeDraw}
          canExportData={canExportData}
          exportTileZoomRange={exportTileZoomRange}
          canUseCurrentViewRange={canUseCurrentViewRange}
          canUseSelectedLayerRange={canUseSelectedLayerRange}
          onStartQueryDraw={onStartQueryDraw}
          onClearSpatialFilter={onClearSpatialFilter}
          onImportSpatialFilter={onImportSpatialFilter}
          onUseCurrentViewRange={onUseCurrentViewRange}
          onUseSelectedLayerRange={onUseSelectedLayerRange}
          onExportMapPng={onExportMapPng}
        />
        <TargetSection
          target={target}
          resources={resources}
          layers={layers}
          selectedResource={loadedResource}
          selectedLayer={loadedLayer}
          loadingResourceProfile={loadingResourceProfile}
          targetStates={targetStates}
          onTargetChange={setTarget}
          onSelectTargetResource={onSelectTargetResource}
          onSelectTargetLayer={onSelectTargetLayer}
        />
        <ResultSection
          target={target}
          targetReady={activeTarget.ready}
          hasRange={Boolean(currentGeometry)}
          result={spatialQueryResult}
          querying={spatialQuerying}
          canExportData={canExportData}
          onRunSpatialQuery={onRunSpatialQuery}
          onLoadSpatialResult={onLoadSpatialResult}
          onLocateSpatialResult={onLocateSpatialResult}
          onOpenSpatialResultTable={onOpenSpatialResultTable}
          onExportSpatialResult={onExportSpatialResult}
          onClearSpatialResult={onClearSpatialResult}
        />
      </div>
    </section>
  );
}

function RangeSection({
  spatialFilter,
  exportClipGeometry,
  activeDraw,
  canExportData,
  exportTileZoomRange,
  canUseCurrentViewRange,
  canUseSelectedLayerRange,
  onStartQueryDraw,
  onClearSpatialFilter,
  onImportSpatialFilter,
  onUseCurrentViewRange,
  onUseSelectedLayerRange,
  onExportMapPng,
}: Pick<
  Props,
  | "spatialFilter"
  | "exportClipGeometry"
  | "activeDraw"
  | "canExportData"
  | "exportTileZoomRange"
  | "canUseCurrentViewRange"
  | "canUseSelectedLayerRange"
  | "onStartQueryDraw"
  | "onClearSpatialFilter"
  | "onImportSpatialFilter"
  | "onUseCurrentViewRange"
  | "onUseSelectedLayerRange"
  | "onExportMapPng"
>) {
  const geometry = spatialFilter?.geometry ?? exportClipGeometry;
  const rangeLabel = spatialFilter
    ? i18n.t("spatial.modeSet", {
        mode: spatialModeName(spatialFilter.mode),
      })
    : geometry
      ? i18n.t("spatial.rangeSet")
      : i18n.t("spatial.rangeUnset");
  const metrics = geometryMetrics(geometry);

  return (
    <section className="spatial-workbench-section">
      <SectionHeading
        icon={<AimOutlined style={{ fontSize: 15 }} />}
        title={i18n.t("spatial.spatialRange")}
        tag={<Tag color={geometry ? "green" : "default"}>{rangeLabel}</Tag>}
      />
      <DrawingPanel
        spatialFilter={spatialFilter}
        exportClipGeometry={exportClipGeometry}
        activeDraw={activeDraw}
        canExportData={canExportData}
        exportTileZoomRange={exportTileZoomRange}
        canUseCurrentViewRange={canUseCurrentViewRange}
        canUseSelectedLayerRange={canUseSelectedLayerRange}
        onStartQueryDraw={onStartQueryDraw}
        onClearSpatialFilter={onClearSpatialFilter}
        onImportSpatialFilter={onImportSpatialFilter}
        onUseCurrentViewRange={onUseCurrentViewRange}
        onUseSelectedLayerRange={onUseSelectedLayerRange}
        onExportMapPng={onExportMapPng}
      />
      <div className="spatial-workbench-meta">
        <Metric
          label={i18n.t("spatial.rangeCoordinates")}
          value={metrics.boundsLabel}
        />
        <Metric
          label={i18n.t("spatial.estimatedArea")}
          value={metrics.areaLabel}
        />
      </div>
    </section>
  );
}

function TargetSection({
  target,
  resources,
  layers,
  selectedResource,
  selectedLayer,
  loadingResourceProfile,
  targetStates,
  onTargetChange,
  onSelectTargetResource,
  onSelectTargetLayer,
}: {
  target: SpatialQueryTarget;
  resources: ResourceListItem[];
  layers: LoadedLayer[];
  selectedResource: ResourceListItem | null;
  selectedLayer: LoadedLayer | null;
  loadingResourceProfile: boolean;
  targetStates: Record<SpatialQueryTarget, SpatialTargetState>;
  onTargetChange: (target: SpatialQueryTarget) => void;
  onSelectTargetResource: (resourceId: number | null) => Promise<void> | void;
  onSelectTargetLayer: (layerId: string | null) => void;
}) {
  const active = targetStates[target];
  const resourceOptions = useMemo(
    () =>
      resources
        .filter(
          (resource) => resource.dataType === "vector" && resource.isQueryable,
        )
        .map((resource) => ({
          value: resource.id,
          label: resource.name,
          title: resourceSpatialExtent(resource),
        })),
    [resources],
  );
  const layerOptions = useMemo(
    () =>
      layers.filter(isQueryableLoadedLayer).map((layer) => ({
        value: layer.id,
        label: layer.name,
        title: resourceSpatialExtent(layer.sourceResource),
      })),
    [layers],
  );

  return (
    <section className="spatial-workbench-section">
      <SectionHeading
        icon={<DatabaseOutlined style={{ fontSize: 15 }} />}
        title={i18n.t("spatial.queryTarget")}
        tag={<Tag color={active.ready ? "green" : "default"}>{active.tag}</Tag>}
      />
      <Segmented
        block
        className="spatial-target-selector"
        value={target}
        options={[
          {
            label: i18n.t("spatial.resource"),
            value: "selectedResource",
            disabled: resourceOptions.length === 0 && !selectedResource,
          },
          {
            label: i18n.t("spatial.layer"),
            value: "selectedLayer",
            disabled: layerOptions.length === 0 && !selectedLayer,
          },
        ]}
        onChange={(nextValue) =>
          onTargetChange(nextValue as SpatialQueryTarget)
        }
      />
      {target === "selectedResource" ? (
        <div className="spatial-target-picker-row">
          <Select
            allowClear
            showSearch
            className="spatial-target-select"
            aria-label={i18n.t("spatial.selectVectorResource")}
            size="small"
            loading={loadingResourceProfile}
            value={selectedResource?.id}
            placeholder={i18n.t("spatial.selectVectorResource")}
            optionFilterProp="label"
            options={resourceOptions}
            notFoundContent={i18n.t("spatial.noQueryableResource")}
            onChange={(value) => void onSelectTargetResource(value ?? null)}
          />
          <Button
            size="small"
            icon={<CloseOutlined style={{ fontSize: 13 }} />}
            disabled={!selectedResource}
            onClick={() => void onSelectTargetResource(null)}
          >
            {i18n.t("common.clear")}
          </Button>
        </div>
      ) : (
        <div className="spatial-target-picker-row">
          <Select
            allowClear
            showSearch
            className="spatial-target-select"
            aria-label={i18n.t("spatial.selectVectorLayer")}
            size="small"
            value={selectedLayer?.id}
            placeholder={i18n.t("spatial.selectVectorLayer")}
            optionFilterProp="label"
            options={layerOptions}
            notFoundContent={i18n.t("spatial.noAvailableLayer")}
            onChange={(value) => onSelectTargetLayer(value ?? null)}
          />
          <Button
            size="small"
            icon={<CloseOutlined style={{ fontSize: 13 }} />}
            disabled={!selectedLayer}
            onClick={() => onSelectTargetLayer(null)}
          >
            {i18n.t("common.clear")}
          </Button>
        </div>
      )}
      <div className="spatial-target-card">
        <Typography.Text className="spatial-target-name" strong>
          {active.name}
        </Typography.Text>
        <Typography.Text
          className="spatial-target-description"
          type="secondary"
        >
          {active.description}
        </Typography.Text>
        <Space className="spatial-target-tags" size={6} wrap>
          <Tag color={active.ready ? "green" : "default"}>
            {active.typeLabel}
          </Tag>
          {active.extent ? <Tag>{active.extent}</Tag> : null}
        </Space>
      </div>
    </section>
  );
}

function ResultSection({
  target,
  targetReady,
  hasRange,
  result,
  querying,
  canExportData,
  onRunSpatialQuery,
  onLoadSpatialResult,
  onLocateSpatialResult,
  onOpenSpatialResultTable,
  onExportSpatialResult,
  onClearSpatialResult,
}: {
  target: SpatialQueryTarget;
  targetReady: boolean;
  hasRange: boolean;
  result: SpatialQueryWorkbenchResult | null;
  querying: boolean;
  canExportData: boolean;
  onRunSpatialQuery: (target: SpatialQueryTarget) => Promise<void> | void;
  onLoadSpatialResult: () => void;
  onLocateSpatialResult: () => void;
  onOpenSpatialResultTable: () => void;
  onExportSpatialResult: () => void;
  onClearSpatialResult: () => void;
}) {
  const status = spatialResultStatus(result, querying, hasRange, targetReady);
  const hasResultRows = Boolean(result && result.returnedCount > 0);
  const resultLoaded = Boolean(result?.loadedLayerName);
  const canRun = hasRange && targetReady && !querying;

  return (
    <section className="spatial-workbench-section spatial-workbench-result">
      <SectionHeading
        icon={
          querying ? (
            <LoadingOutlined style={{ fontSize: 15 }} />
          ) : (
            <FileSearchOutlined style={{ fontSize: 15 }} />
          )
        }
        title={i18n.t("spatial.resultsAndActions")}
        tag={<Tag color={status.color}>{status.label}</Tag>}
      />
      {result ? (
        <div className="spatial-result-summary">
          <div className="spatial-result-title">
            <Typography.Text strong>{result.targetName}</Typography.Text>
            <Typography.Text type="secondary">
              {result.loadedLayerName
                ? i18n.t("spatial.loadedAsLayer", {
                    name: result.loadedLayerName,
                  })
                : i18n.t("spatial.temporaryResult")}
            </Typography.Text>
          </div>
          <div className="spatial-result-metrics">
            <Metric
              label={i18n.t("spatial.hits")}
              value={i18n.t("common.records", { count: result.totalCount })}
            />
            <Metric
              label={i18n.t("spatial.returned")}
              value={i18n.t("common.records", { count: result.returnedCount })}
            />
            <Metric
              label={i18n.t("spatial.truncated")}
              value={
                result.limitExceeded
                  ? i18n.t("spatial.overLimit", { limit: result.limit })
                  : i18n.t("common.no")
              }
            />
            <Metric
              label={i18n.t("spatial.elapsed")}
              value={`${result.elapsedMs} ms`}
            />
            <Metric
              label={i18n.t("spatial.boundary")}
              value={
                formatBounds(result.bounds) || i18n.t("spatial.noValidExtent")
              }
            />
            <Metric
              label={i18n.t("spatial.warning")}
              value={
                result.warningCount
                  ? i18n.t("spatial.warningCount", {
                      count: result.warningCount,
                    })
                  : i18n.t("spatial.none")
              }
            />
          </div>
        </div>
      ) : (
        <Empty
          className="spatial-result-empty"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={status.description}
        />
      )}
      <div className="spatial-result-actions">
        <Button
          type="primary"
          icon={<FileSearchOutlined style={{ fontSize: 14 }} />}
          loading={querying}
          disabled={!canRun}
          onClick={() => void onRunSpatialQuery(target)}
        >
          {i18n.t("spatial.runQuery")}
        </Button>
        <Button
          icon={<FolderOpenOutlined style={{ fontSize: 14 }} />}
          disabled={!hasResultRows || resultLoaded}
          onClick={onLoadSpatialResult}
        >
          {i18n.t("spatial.loadAsLayer")}
        </Button>
        <Button
          icon={<PushpinOutlined style={{ fontSize: 14 }} />}
          disabled={!hasResultRows}
          onClick={onLocateSpatialResult}
        >
          {i18n.t("spatial.locate")}
        </Button>
        <Button
          icon={<TableOutlined style={{ fontSize: 14 }} />}
          disabled={!hasResultRows}
          onClick={onOpenSpatialResultTable}
        >
          {i18n.t("spatial.attributeTable")}
        </Button>
        <Tooltip
          title={
            canExportData ? undefined : i18n.t("spatial.noExportPermission")
          }
        >
          <Button
            icon={<DownloadOutlined style={{ fontSize: 14 }} />}
            disabled={!hasResultRows || !canExportData}
            onClick={onExportSpatialResult}
          >
            {i18n.t("spatial.export")}
          </Button>
        </Tooltip>
        <Button
          icon={<CloseOutlined style={{ fontSize: 14 }} />}
          disabled={!result}
          onClick={onClearSpatialResult}
        >
          {i18n.t("common.clear")}
        </Button>
      </div>
    </section>
  );
}

function DrawingPanel({
  spatialFilter,
  exportClipGeometry,
  activeDraw,
  canExportData,
  exportTileZoomRange,
  canUseCurrentViewRange,
  canUseSelectedLayerRange,
  onStartQueryDraw,
  onClearSpatialFilter,
  onImportSpatialFilter,
  onUseCurrentViewRange,
  onUseSelectedLayerRange,
  onExportMapPng,
}: Pick<
  Props,
  | "spatialFilter"
  | "exportClipGeometry"
  | "activeDraw"
  | "canExportData"
  | "exportTileZoomRange"
  | "canUseCurrentViewRange"
  | "canUseSelectedLayerRange"
  | "onStartQueryDraw"
  | "onClearSpatialFilter"
  | "onImportSpatialFilter"
  | "onUseCurrentViewRange"
  | "onUseSelectedLayerRange"
  | "onExportMapPng"
>) {
  const { message } = App.useApp();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const currentGeometry = spatialFilter?.geometry ?? exportClipGeometry;

  async function handleImportGeojson(file: File) {
    try {
      const geometry = geometryFromGeojson(JSON.parse(await file.text()));
      if (!geometry) {
        message.warning(i18n.t("spatial.geoJsonNoBounds"));
        return;
      }
      void onImportSpatialFilter({
        mode: inferSpatialMode(geometry),
        geometry,
      });
      message.success(i18n.t("spatial.boundsImported"));
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : i18n.t("spatial.geoJsonReadFailed"),
      );
    } finally {
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  function handleExportGeojson() {
    if (!currentGeometry) {
      message.warning(i18n.t("spatial.drawOrImportFirst"));
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

  function handleExportMapImage() {
    const tileZoom = Math.min(
      exportTileZoomRange.max,
      Math.max(exportTileZoomRange.min, 8),
    );
    void onExportMapPng({ format: "png", dpi: 150, tileZoom });
  }

  return (
    <div className="spatial-range-tools">
      <Segmented
        block
        className="spatial-range-mode-selector"
        value={activeDraw?.purpose === "query" ? activeDraw.mode : "none"}
        options={[
          { label: i18n.t("spatial.drawNone"), value: "none" },
          { label: i18n.t("spatial.rectangle"), value: "rectangle" },
          { label: i18n.t("spatial.circle"), value: "circle" },
          { label: i18n.t("spatial.ellipse"), value: "ellipse" },
          { label: i18n.t("spatial.polygon"), value: "polygon" },
        ]}
        onChange={(nextValue) =>
          onStartQueryDraw(
            nextValue === "none" ? null : (nextValue as DrawMode),
          )
        }
      />
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
      <div className="spatial-range-action-grid">
        <Button
          size="small"
          disabled={!canUseCurrentViewRange}
          onClick={onUseCurrentViewRange}
        >
          {i18n.t("spatial.currentView")}
        </Button>
        <Button
          size="small"
          disabled={!canUseSelectedLayerRange}
          onClick={onUseSelectedLayerRange}
        >
          {i18n.t("spatial.layerExtent")}
        </Button>
        <Button
          size="small"
          icon={<UploadOutlined style={{ fontSize: 13 }} />}
          onClick={() => fileInputRef.current?.click()}
        >
          {i18n.t("spatial.import")}
        </Button>
        <Button
          size="small"
          icon={<DownloadOutlined style={{ fontSize: 13 }} />}
          disabled={!currentGeometry}
          onClick={handleExportGeojson}
        >
          {i18n.t("spatial.exportRange")}
        </Button>
        <Button
          size="small"
          icon={<DownloadOutlined style={{ fontSize: 13 }} />}
          disabled={!currentGeometry || !canExportData}
          onClick={handleExportMapImage}
        >
          {i18n.t("spatial.mapImage")}
        </Button>
        <Button
          size="small"
          icon={<CloseOutlined style={{ fontSize: 13 }} />}
          disabled={!currentGeometry}
          onClick={onClearSpatialFilter}
        >
          {i18n.t("common.clear")}
        </Button>
      </div>
    </div>
  );
}

function SectionHeading({
  icon,
  title,
  tag,
}: {
  icon: React.ReactNode;
  title: string;
  tag?: React.ReactNode;
}) {
  return (
    <div className="spatial-section-heading">
      <span>
        {icon}
        <Typography.Text strong>{title}</Typography.Text>
      </span>
      {tag}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <span className="spatial-metric">
      <Typography.Text type="secondary">{label}</Typography.Text>
      <Typography.Text>{value || "-"}</Typography.Text>
    </span>
  );
}

interface SpatialTargetState {
  ready: boolean;
  tag: string;
  name: string;
  description: string;
  typeLabel: string;
  extent: string;
}

function spatialTargetStates(
  selectedResource: ResourceListItem | null,
  selectedResourceProfile: DataResourceProfile | null,
  selectedLayer: LoadedLayer | null,
): Record<SpatialQueryTarget, SpatialTargetState> {
  const resourceReady =
    selectedResource?.dataType === "vector" &&
    selectedResource.isQueryable &&
    Boolean(selectedResourceProfile);
  const layerReady =
    selectedLayer?.layerType === "vector" &&
    selectedLayer.sourceResource.isQueryable &&
    selectedLayer.sourceResource.id > 0;

  return {
    selectedResource: {
      ready: resourceReady,
      tag: resourceReady ? i18n.t("spatial.ready") : i18n.t("spatial.notReady"),
      name: selectedResource?.name ?? i18n.t("spatial.noResourceSelected"),
      description: selectedResource
        ? resourceReady
          ? i18n.t("spatial.selectedResourceReady")
          : i18n.t("spatial.selectedResourceNotReady")
        : i18n.t("spatial.selectResourceHint"),
      typeLabel:
        selectedResource?.dataType === "vector"
          ? i18n.t("spatial.vectorResource")
          : i18n.t("spatial.resource"),
      extent: selectedResource ? resourceSpatialExtent(selectedResource) : "",
    },
    selectedLayer: {
      ready: layerReady,
      tag: layerReady ? i18n.t("spatial.ready") : i18n.t("spatial.notReady"),
      name: selectedLayer?.name ?? i18n.t("spatial.noLayerSelected"),
      description: selectedLayer
        ? layerReady
          ? i18n.t("spatial.selectedLayerReady")
          : i18n.t("spatial.selectedLayerNotReady")
        : i18n.t("spatial.selectLayerHint"),
      typeLabel:
        selectedLayer?.layerType === "vector"
          ? i18n.t("spatial.vectorLayer")
          : i18n.t("spatial.layer"),
      extent: selectedLayer
        ? String(
            selectedLayer.metadata.空间范围 ??
              resourceSpatialExtent(selectedLayer.sourceResource) ??
              "",
          )
        : "",
    },
  };
}

function spatialResultStatus(
  result: SpatialQueryWorkbenchResult | null,
  querying: boolean,
  hasRange: boolean,
  targetReady: boolean,
) {
  if (querying) {
    return {
      label: i18n.t("spatial.querying"),
      color: "processing",
      description: i18n.t("spatial.queryingDescription"),
    };
  }
  if (result?.returnedCount === 0) {
    return {
      label: i18n.t("spatial.noHits"),
      color: "default",
      description: i18n.t("spatial.noHitsDescription"),
    };
  }
  if (result?.loadedLayerName) {
    return {
      label: i18n.t("spatial.resultLoaded"),
      color: "green",
      description: i18n.t("spatial.resultLoadedDescription"),
    };
  }
  if (result) {
    return {
      label: result.limitExceeded
        ? i18n.t("spatial.resultOverLimit")
        : i18n.t("spatial.querySucceeded"),
      color: result.limitExceeded ? "warning" : "green",
      description: i18n.t("spatial.querySucceededDescription"),
    };
  }
  if (hasRange && targetReady) {
    return {
      label: i18n.t("spatial.pending"),
      color: "blue",
      description: i18n.t("spatial.pendingDescription"),
    };
  }
  return {
    label: i18n.t("spatial.notQueried"),
    color: "default",
    description: i18n.t("spatial.notQueriedDescription"),
  };
}

function spatialModeName(mode: SpatialFilter["mode"]) {
  const names: Record<SpatialFilter["mode"], string> = {
    rectangle: i18n.t("spatial.rectangleRange"),
    circle: i18n.t("spatial.circleRange"),
    ellipse: i18n.t("spatial.ellipseRange"),
    polygon: i18n.t("spatial.polygonRange"),
  };
  return names[mode];
}

function geometryFromGeojson(value: unknown): GeoJsonGeometry | null {
  if (!isGeojsonObject(value)) return null;
  return firstSupportedGeometry(value) ?? boundaryGeometryFromGeojson(value);
}

function firstSupportedGeometry(value: unknown): GeoJsonGeometry | null {
  if (!isGeojsonObject(value)) return null;
  if (isSupportedGeometry(value)) return value;
  if (value.type === "Feature") {
    return firstSupportedGeometry(value.geometry);
  }
  if (value.type === "FeatureCollection" && Array.isArray(value.features)) {
    for (const feature of value.features) {
      const geometry = firstSupportedGeometry(feature);
      if (geometry) return geometry;
    }
  }
  if (value.type === "GeometryCollection" && Array.isArray(value.geometries)) {
    for (const geometryValue of value.geometries) {
      const geometry = firstSupportedGeometry(geometryValue);
      if (geometry) return geometry;
    }
  }
  return null;
}

function boundaryGeometryFromGeojson(value: unknown): GeoJsonGeometry | null {
  const points: Array<[number, number]> = [];
  collectGeojsonCoordinates(value, points);
  const finitePoints = points.filter(
    ([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat),
  );
  if (finitePoints.length === 0) return null;
  const lngs = finitePoints.map((point) => point[0]);
  const lats = finitePoints.map((point) => point[1]);
  const bounds = expandFlatBounds([
    Math.min(...lngs),
    Math.min(...lats),
    Math.max(...lngs),
    Math.max(...lats),
  ]);
  return rectangleGeometry([bounds[0], bounds[1]], [bounds[2], bounds[3]]);
}

function expandFlatBounds(bounds: [number, number, number, number]) {
  const [minLng, minLat, maxLng, maxLat] = bounds;
  const lngSpan = maxLng - minLng;
  const latSpan = maxLat - minLat;
  const fallbackPadding = 0.0001;
  const lngPadding =
    lngSpan === 0 ? Math.max(Math.abs(latSpan) * 0.02, fallbackPadding) : 0;
  const latPadding =
    latSpan === 0 ? Math.max(Math.abs(lngSpan) * 0.02, fallbackPadding) : 0;
  return [
    minLng - lngPadding,
    minLat - latPadding,
    maxLng + lngPadding,
    maxLat + latPadding,
  ] as [number, number, number, number];
}

function collectGeojsonCoordinates(
  value: unknown,
  points: Array<[number, number]>,
) {
  if (!isGeojsonObject(value)) return;
  if (value.type === "Feature") {
    collectGeojsonCoordinates(value.geometry, points);
    return;
  }
  if (value.type === "FeatureCollection" && Array.isArray(value.features)) {
    for (const feature of value.features) {
      collectGeojsonCoordinates(feature, points);
    }
    return;
  }
  if (value.type === "GeometryCollection" && Array.isArray(value.geometries)) {
    for (const geometryValue of value.geometries) {
      collectGeojsonCoordinates(geometryValue, points);
    }
    return;
  }
  if ("coordinates" in value) {
    extractCoordinates(value.coordinates, points);
  }
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

function geometryMetrics(geometry: GeoJsonGeometry | null | undefined) {
  if (!geometry) {
    return {
      boundsLabel: i18n.t("spatial.notSet"),
      areaLabel: i18n.t("spatial.notSet"),
    };
  }
  return {
    boundsLabel:
      formatBounds(boundsForGeometry(geometry)) ||
      i18n.t("spatial.noValidCoordinates"),
    areaLabel: formatArea(estimateAreaSqKm(geometry)),
  };
}

function boundsForGeometry(geometry: GeoJsonGeometry): number[] {
  const points: Array<[number, number]> = [];
  extractCoordinates(
    (geometry as { coordinates?: unknown }).coordinates,
    points,
  );
  if (points.length === 0) return [];
  const lngs = points.map((point) => point[0]);
  const lats = points.map((point) => point[1]);
  return [
    Math.min(...lngs),
    Math.min(...lats),
    Math.max(...lngs),
    Math.max(...lats),
  ].map((value) => Number(value.toFixed(6)));
}

function formatBounds(bounds: number[]) {
  if (bounds.length < 4) return "";
  return `${bounds[0]?.toFixed(4)}, ${bounds[1]?.toFixed(4)} - ${bounds[2]?.toFixed(4)}, ${bounds[3]?.toFixed(4)}`;
}

function estimateAreaSqKm(geometry: GeoJsonGeometry): number | null {
  const coordinates = geometry.coordinates;
  if (geometry.type === "Polygon" && Array.isArray(coordinates)) {
    return Math.abs(ringAreaSqKm(coordinates[0]));
  }
  if (geometry.type === "MultiPolygon" && Array.isArray(coordinates)) {
    return coordinates.reduce(
      (total, polygon) =>
        total +
        (Array.isArray(polygon) ? Math.abs(ringAreaSqKm(polygon[0])) : 0),
      0,
    );
  }
  return null;
}

function ringAreaSqKm(ring: unknown): number {
  if (!Array.isArray(ring) || ring.length < 4) return 0;
  const points = ring.filter(isCoordinatePair);
  if (points.length < 4) return 0;
  const avgLat =
    points.reduce((total, point) => total + point[1], 0) / points.length;
  const lngScale = 111.32 * Math.cos((avgLat * Math.PI) / 180);
  const latScale = 110.574;
  let area = 0;
  for (let index = 0; index < points.length; index += 1) {
    const current = points[index];
    const next = points[(index + 1) % points.length];
    if (!current || !next) continue;
    area += current[0] * lngScale * (next[1] * latScale);
    area -= next[0] * lngScale * (current[1] * latScale);
  }
  return area / 2;
}

function isCoordinatePair(value: unknown): value is [number, number] {
  return (
    Array.isArray(value) &&
    typeof value[0] === "number" &&
    typeof value[1] === "number" &&
    Number.isFinite(value[0]) &&
    Number.isFinite(value[1])
  );
}

function formatArea(value: number | null) {
  if (value === null) return i18n.t("spatial.notCalculated");
  if (!Number.isFinite(value) || value <= 0) {
    return i18n.t("spatial.lessThanArea");
  }
  if (value < 1) return `${value.toFixed(2)} km²`;
  return `${Math.round(value).toLocaleString("zh-CN")} km²`;
}
