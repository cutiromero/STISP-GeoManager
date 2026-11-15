import { useMonitoringWorkspace } from "./useMonitoringWorkspace";
import MonitoringSourceControls from "./MonitoringSourceControls";
import MonitorRegionControls from "./MonitorRegionControls";
import MonitorRawLayer from "./MonitorRawLayer";
import MonitorTimeline from "./MonitorTimeline";
import type { Map as MapboxMap } from "mapbox-gl";
import { ReloadOutlined } from "@ant-design/icons";
import { Button, Checkbox, Empty, Segmented } from "antd";
import {
  lazy,
  Suspense,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import type {
  ProjectMonitorConfig,
  ResourceListItem,
} from "../api/generated/types.gen";
import { api } from "../api/client";
import { useAppContext } from "../contexts/AppContext";
import { downloadBlob } from "../utils/download";
import MonitorDashboardFrame from "./MonitorDashboardFrame";
import { MonitorPanel } from "./MonitorPanels";
import { MonitorDataStatus } from "./MonitorLayerStatus";
import MonitorProductSelector from "./MonitorProductSelector";
import { monitorResourceProfile } from "./resourceProfiles";
import { useMonitorProductSelection } from "./useMonitorProductSelection";
import { useMonitoringProducts } from "./useMonitoringProducts";
import { useMonitorTask } from "./useMonitorTask";
import SpartinaTaskDrawer from "./SpartinaTaskDrawer";
import type { MonitorComparisonView } from "./MonitorComparisonMap";
import "./spartina-monitor.css";

const ComparisonMap = lazy(() => import("./MonitorComparisonMap"));
const statusNames: Record<string, string> = {
  queued: "等待执行",
  running: "处理中",
  waiting_compute: "模型计算中",
  waiting_approval: "等待处理",
  paused: "已暂停",
  succeeded: "已完成",
  failed: "未完成",
  cancelled: "已停止",
  interrupted: "已中断",
};

export default function SpartinaDashboard({
  config,
  navigation,
  projectId,
}: {
  config: ProjectMonitorConfig;
  navigation: ReactNode;
  projectId: number;
}) {
  const navigate = useNavigate();
  const { user } = useAppContext();
  const products = useMonitoringProducts("spartina");
  const { page, loading, failure, setRevision } = products;
  const showCurrent = useRef<(() => void) | undefined>(undefined);
  const [mode, setMode] = useState<MonitorComparisonView | "probability">(
    "classification",
  );
  const [hidden, setHidden] = useState(false);
  const workspace = useMonitoringWorkspace("spartina", projectId);
  const [map, setMap] = useState<MapboxMap>();
  const [drawer, setDrawer] = useState<"new" | "current" | "records">();
  const [downloadError, setDownloadError] = useState<string>();
  const [downloading, setDownloading] = useState(false);
  const task = useMonitorTask(
    projectId,
    user?.id,
    () => {
      showCurrent.current?.();
      setMode("classification");
      setRevision((v) => v + 1);
    },
    page?.businessFlow?.definitionId,
    "spartina",
  );
  const selection = useMonitorProductSelection({
    items: page?.items ?? [],
    references: page?.referenceResources ?? [],
    currentBatchId: task.flow?.id,
  });
  showCurrent.current = selection.showCurrent;
  const selected = selection.selected;
  const mapConfig = useMemo(() => {
    const bounds = selected?.extraction?.bounds;
    return bounds
      ? {
          ...config,
          initialView: {
            ...config.initialView,
            center: [
              (bounds[0]! + bounds[2]!) / 2,
              (bounds[1]! + bounds[3]!) / 2,
            ] as [number, number],
          },
        }
      : config;
  }, [config, selected?.extraction?.bounds]);
  const reference = selection.reference;
  const original = workspace.source?.resource;
  const probability = selected?.attachments?.find(
    (row) => row.role === "probability",
  )?.resource;
  const ready = Boolean(selected || reference);
  const displayMode =
    mode === "probability"
      ? probability
        ? "classification"
        : "original"
      : ready
        ? mode
        : "original";
  const running = Boolean(
    task.flow &&
    [
      "queued",
      "running",
      "waiting_compute",
      "waiting_approval",
      "paused",
    ].includes(task.flow.status),
  );
  const metric = (key: string) =>
    selected?.metrics.find((row) => row.key === key)?.value;
  const format = (key: string, precision = 2) => {
    const value = metric(key);
    return value == null
      ? "—"
      : value.toLocaleString("zh-CN", { maximumFractionDigits: precision });
  };
  const number = (key: string, unit: string, precision = 2) => {
    const value = format(key, precision);
    return (
      <strong
        style={
          { "--spartina-value-width": value.length * 0.62 } as CSSProperties
        }
      >
        <span>{value}</span>
        <small>{unit}</small>
      </strong>
    );
  };
  const download = async (resource?: ResourceListItem) => {
    if (!resource || downloading) return;
    if (resource.dataType === "vector") {
      navigate(`/map?projectTagId=${projectId}&resources=${resource.id}`);
      return;
    }
    setDownloading(true);
    setDownloadError(undefined);
    try {
      const profile = await monitorResourceProfile(resource);
      if (!profile.raster?.id) throw new Error("该成果尚无栅格数据集");
      const result = await api.exportLayers({
        reproject: false,
        clip: false,
        items: [
          {
            layerType: "raster",
            datasetId: profile.raster.id,
            resourceId: resource.id,
            name: resource.name,
          },
        ],
      });
      downloadBlob(result.blob, result.filename);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : "下载未完成");
    } finally {
      setDownloading(false);
    }
  };
  const downloadStatistics = () => {
    if (!selected) return;
    const rows = [
      ["指标", "数值", "单位"],
      ...selected.metrics.map((row) => [row.label, row.value ?? "", row.unit]),
    ];
    downloadBlob(
      new Blob(
        [
          "\ufeff" +
            rows
              .map((row) => row.map((v) => JSON.stringify(v)).join(","))
              .join("\n"),
        ],
        { type: "text/csv;charset=utf-8" },
      ),
      "互花米草分布统计.csv",
    );
  };
  return (
    <MonitorDashboardFrame
      config={config}
      scene="spartina"
      navigation={navigation}
      updatedAt={selected?.registeredAt}
      sourceLabel={
        selection.view === "registered"
          ? "登记成果"
          : selected?.kind === "model"
            ? "RF · 互花米草分布解译"
            : "互花米草历史分布"
      }
      status={() => selected?.name ?? reference?.name ?? "原始监测资料"}
      actions={
        <>
          <Button
            type="primary"
            size="small"
            disabled={!page?.businessFlow}
            onClick={() => setDrawer(running ? "current" : "new")}
          >
            {running ? "查看任务" : "开始解译"}
          </Button>
          <Button
            size="small"
            disabled={!page?.businessFlow}
            onClick={() => setDrawer("records")}
          >
            处理记录
          </Button>
          <Button
            size="small"
            aria-label="刷新成果"
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={() => setRevision((v) => v + 1)}
          >
            刷新成果
          </Button>
        </>
      }
    >
      {({ animated }) => (
        <>
          <MonitorDataStatus
            title="互花米草成果"
            loading={loading}
            error={failure ?? downloadError}
          />
          <main className="monitor-layout">
            <section
              className="monitor-globe-panel"
              aria-label="互花米草分布地图"
            >
              <Suspense
                fallback={<MonitorDataStatus title="准备地图" loading />}
              >
                <ComparisonMap
                  onMapReady={setMap}
                  refreshKey={products.revision}
                  resultVisible={workspace.resultVisible}
                  product={mode === "probability" ? undefined : selected}
                  displayResource={
                    mode === "probability" ? probability : reference
                  }
                  original={original}
                  config={mapConfig}
                  animated={animated}
                  mode={displayMode}
                  visibleCodes={hidden ? [] : [1]}
                  focusKey={
                    selected?.resourceId ?? reference?.id ?? original?.id
                  }
                />
              </Suspense>
              <MonitorRawLayer map={map} workspace={workspace} />
              <MonitorRegionControls map={map} workspace={workspace} />
              <MonitorTimeline
                workspace={workspace}
                items={page?.items ?? []}
                selected={selected}
                onSelect={selection.selectProduct}
                onMore={
                  page?.nextBeforeId
                    ? () => void products.loadMore()
                    : undefined
                }
              />
              <div className="landcover-map-toolbar">
                <Segmented
                  aria-label="影像对比方式"
                  value={
                    workspace.timeTarget === "source"
                      ? "original"
                      : mode === "probability" && probability
                        ? "probability"
                        : displayMode
                  }
                  onChange={(value) => {
                    workspace.selectTimeTarget(
                      value === "original" ? "source" : "result",
                    );
                    setMode(
                      value === "original"
                        ? "classification"
                        : (value as typeof mode),
                    );
                  }}
                  options={[
                    {
                      label: "分类",
                      value: "classification",
                      disabled: !ready,
                    },
                    { label: "原图", value: "original", disabled: !original },
                    {
                      label: "叠加",
                      value: "overlay",
                      disabled: !ready || !original,
                    },
                    {
                      label: "卷帘",
                      value: "swipe",
                      disabled: !ready || !original,
                    },
                    {
                      label: "概率",
                      value: "probability",
                      disabled: !probability,
                    },
                  ]}
                />
              </div>
            </section>
            <div className="monitor-information">
              <div className="monitor-summary">
                <div>
                  <span>输入组合</span>
                  <strong>
                    {workspace.inputSet?.resources.length ?? "—"}
                    <small>时相</small>
                  </strong>
                </div>
                <div>
                  <span>成果数量</span>
                  <strong>
                    {page?.items.length ?? 0}
                    <small>份</small>
                  </strong>
                </div>
                <div>
                  <span>当前方法</span>
                  <strong>
                    {selected?.model ? "RF" : selected ? "历史成果" : "RF"}
                  </strong>
                </div>
              </div>
              <MonitorPanel title="研究区与成果">
                <div className="spartina-card-body">
                  <MonitorProductSelector
                    selection={selection}
                    presentation="list"
                    labels={{
                      current: selection.hasCurrentTask
                        ? "本次解译"
                        : "最近解译",
                    }}
                  />
                  {page?.nextBeforeId && (
                    <Button
                      type="link"
                      onClick={() => void products.loadMore()}
                    >
                      更多成果
                    </Button>
                  )}
                  {selected?.extraction && (
                    <p className="spartina-secondary">
                      研究区{" "}
                      {selected.extraction.bounds
                        .map((value) => value.toFixed(3))
                        .join(" / ")}
                    </p>
                  )}
                </div>
              </MonitorPanel>
              <MonitorPanel
                title="解译任务"
                extra={
                  <Button
                    type="link"
                    size="small"
                    disabled={!page?.businessFlow}
                    onClick={() => setDrawer(running ? "current" : "new")}
                  >
                    {running ? "查看任务" : "开始任务"}
                  </Button>
                }
              >
                <div className="spartina-card-body">
                  {task.flow ? (
                    <>
                      <span className="spartina-secondary">
                        本次任务 · {task.flow.id.slice(0, 8)}
                      </span>
                      <strong className="spartina-task-status">
                        {statusNames[task.flow.status] ?? task.flow.status}
                      </strong>
                      <p>
                        {task.flow.definitionSnapshot.nodes.find(
                          (row) => row.id === task.flow?.currentNode,
                        )?.title ??
                          `${task.flow.nodes.filter((row) => row.status === "succeeded").length}/${task.flow.nodes.length} 个目标完成`}
                      </p>
                      <Button
                        type="link"
                        size="small"
                        onClick={() => setDrawer("current")}
                      >
                        打开任务
                      </Button>
                    </>
                  ) : (
                    <>
                      <strong>三季节联合识别</strong>
                      <p>默认全域解译，也可框选局部范围</p>
                      <ol className="spartina-route">
                        {page?.route.map((title, index) => (
                          <li key={title}>
                            <span>{String(index + 1).padStart(2, "0")}</span>
                            {title}
                          </li>
                        ))}
                      </ol>
                    </>
                  )}
                  {task.error && <p>{task.error}</p>}
                </div>
              </MonitorPanel>
              <MonitorPanel title="分布统计">
                <div className="spartina-card-body">
                  <div className="spartina-metrics monitor-metrics">
                    <div className="monitor-metric">
                      <span>分布面积</span>
                      {number("area_ha", "ha")}
                    </div>
                    <div className="monitor-metric">
                      <span>斑块数量</span>
                      {number("patch_count", "个", 0)}
                    </div>
                    <div className="monitor-metric">
                      <span>有效统计面积</span>
                      {number("valid_area_km2", "km²")}
                    </div>
                    <div className="monitor-metric">
                      <span>有效区内占比</span>
                      {number("coverage_percent", "%")}
                    </div>
                  </div>
                  {selected && (
                    <details>
                      <summary>统计口径</summary>
                      <p>{selected.statisticsMethod}</p>
                    </details>
                  )}
                </div>
              </MonitorPanel>
              <MonitorPanel title="分布与显示">
                <div className="spartina-card-body">
                  <Checkbox
                    checked={!hidden}
                    onChange={(event) => setHidden(!event.target.checked)}
                    disabled={
                      !ready ||
                      mode === "probability" ||
                      selected?.resource.dataType !== "raster"
                    }
                  >
                    <i className="spartina-color" />
                    互花米草
                  </Checkbox>
                  <MonitoringSourceControls workspace={workspace} compact />
                </div>
              </MonitorPanel>
              <MonitorPanel title="方法与输入">
                <div className="spartina-card-body">
                  <strong>
                    {selected?.model?.name ??
                      (selected ? "登记分布" : "随机森林 RF")}
                  </strong>
                  <p>
                    {reference
                      ? reference.name
                      : (selected?.model?.variant ??
                        (selected
                          ? "历史分布成果"
                          : `${workspace.catalog?.method?.inputs.length ?? 3}时相 · 16波段`))}
                  </p>
                  <span className="spartina-secondary">
                    B1–B9、B8A、B11、B12 · NDVI / NDWI / NBR / EVI
                  </span>
                  {selected?.model && <p>模型版本 {selected.model.version}</p>}
                  <details>
                    <summary>输入资料</summary>
                    {page?.inputResources?.map((row) => (
                      <p key={row.id}>{row.name}</p>
                    ))}
                  </details>
                </div>
              </MonitorPanel>
              <MonitorPanel title="成果说明" className="monitor-assessment">
                <div className="spartina-card-body monitor-assessment-copy">
                  {selected ? (
                    <>
                      <p>{selected.interpretation}</p>
                      <time
                        className="spartina-secondary"
                        dateTime={selected.registeredAt}
                      >
                        {selected.kind === "model" ? "生成时间" : "登记时间"}{" "}
                        {new Date(selected.registeredAt).toLocaleString()}
                      </time>
                      {selected.observedStart && (
                        <p className="spartina-secondary">
                          {selected.observedStart}
                        </p>
                      )}
                      <Button
                        type="link"
                        size="small"
                        loading={downloading}
                        onClick={() =>
                          void download(reference ?? selected.resource)
                        }
                      >
                        {selected.resource.dataType === "vector"
                          ? "工作台导出"
                          : "下载成果"}
                      </Button>
                      <Button
                        type="link"
                        size="small"
                        onClick={downloadStatistics}
                      >
                        下载统计
                      </Button>
                      {probability && (
                        <Button
                          type="link"
                          size="small"
                          onClick={() => void download(probability)}
                        >
                          下载概率
                        </Button>
                      )}
                    </>
                  ) : reference ? (
                    <>
                      <p>{reference.name}</p>
                      <Button
                        type="link"
                        size="small"
                        onClick={() => void download(reference)}
                      >
                        查看与导出
                      </Button>
                    </>
                  ) : (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="暂无监测成果"
                    />
                  )}
                </div>
              </MonitorPanel>
            </div>
          </main>
          {drawer && (
            <SpartinaTaskDrawer
              workspace={workspace}
              page={page}
              flow={task.flow}
              onChanged={task.accept}
              onClose={() => setDrawer(undefined)}
              records={drawer === "records"}
              startNew={drawer === "new"}
            />
          )}
        </>
      )}
    </MonitorDashboardFrame>
  );
}
