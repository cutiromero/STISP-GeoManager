import { ReloadOutlined } from "@ant-design/icons";
import { Button, Checkbox, Empty, Segmented, Select } from "antd";
import {
  lazy,
  Suspense,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { ProjectMonitorConfig } from "../api/generated/types.gen";
import { useAppContext } from "../contexts/AppContext";
import { useComputeText } from "../compute/ui";
import { api } from "../api/client";
import { downloadBlob } from "../utils/download";
import MonitorDashboardFrame from "./MonitorDashboardFrame";
import { MonitorPanel } from "./MonitorPanels";
import MonitorProductSelector from "./MonitorProductSelector";
import { useMonitorProductSelection } from "./useMonitorProductSelection";
import { MonitorDataStatus } from "./MonitorLayerStatus";
import { useMonitoringProducts } from "./useMonitoringProducts";
import { useMonitorTask } from "./useMonitorTask";
import LandcoverTaskDrawer from "./LandcoverTaskDrawer";
import type { LandcoverView } from "./LandcoverComparisonMap";
import "./landcover-monitor.css";

const ComparisonMap = lazy(() => import("./LandcoverComparisonMap"));
const codes = [1, 2, 4, 5, 6, 8];
const statusNames: Record<string, string> = {
  queued: "等待执行",
  running: "处理中",
  waiting_compute: "处理中",
  waiting_approval: "等待处理",
  succeeded: "已完成",
  paused: "已暂停",
  failed: "未完成",
  cancelled: "已停止",
  interrupted: "已中断",
};

export default function LandcoverDashboard({
  config,
  navigation,
  projectId,
}: {
  config: ProjectMonitorConfig;
  navigation: ReactNode;
  projectId: number;
}) {
  const ui = useComputeText();
  const { user } = useAppContext();
  const products = useMonitoringProducts("landcover");
  const { page, loading, failure, setRevision } = products;
  const [sourceId, setSourceId] = useState<number>();
  const selectCurrent = useRef<(() => void) | undefined>(undefined);
  const [mode, setMode] = useState<LandcoverView>("classification");
  const [hidden, setHidden] = useState<number[]>([]);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string>();
  const [drawer, setDrawer] = useState<"new" | "current" | "records">();
  const task = useMonitorTask(
    projectId,
    user?.id,
    () => {
      setSourceId(undefined);
      selectCurrent.current?.();
      setMode("classification");
      setRevision((value) => value + 1);
    },
    page?.businessFlow?.definitionId,
  );
  const resources = page?.inputResources ?? [];
  const preferredBatch =
    task.flow?.id ??
    page?.items.find((item) => item.provenance?.owned)?.provenance?.batchId;
  const preferredProduct = preferredBatch
    ? page?.items.find((item) => item.provenance?.batchId === preferredBatch)
    : page?.items[0];
  const selectedSource =
    sourceId ?? preferredProduct?.sourceResourceIds[0] ?? resources[0]?.id ?? 0;
  const selection = useMonitorProductSelection({
    items: page?.items ?? [],
    references: page?.referenceResources ?? [],
    sourceId: selectedSource,
    currentBatchId: task.flow?.id,
  });
  selectCurrent.current = selection.showCurrent;
  const selected = selection.selected;
  const selectedReference = selection.reference;
  const hasResult = Boolean(selected || selectedReference);
  const displayMode = !hasResult ? "original" : mode;
  const original = resources.find((resource) => resource.id === selectedSource);
  const categories = selected?.classification?.categories ?? [];
  const visibleCodes = useMemo(
    () => codes.filter((code) => !hidden.includes(code)),
    [hidden],
  );
  const running =
    task.flow &&
    [
      "queued",
      "running",
      "waiting_compute",
      "waiting_approval",
      "paused",
    ].includes(task.flow.status);
  const completedSources = new Set(
    page?.items
      .filter(
        (product) =>
          !selection.batch || product.provenance?.batchId === selection.batch,
      )
      .flatMap((product) => product.sourceResourceIds)
      .filter((id) => resources.some((resource) => resource.id === id)),
  );
  const completed =
    task.flow?.nodes.filter((node) => node.status === "succeeded").length ?? 0;
  const download = async () => {
    if ((!selected && !selectedReference) || downloading) return;
    setDownloading(true);
    setDownloadError(undefined);
    try {
      const { blob, filename } = await api.exportLayers({
        reproject: false,
        clip: false,
        items: [
          {
            layerType: "raster",
            resourceId: selected?.resourceId ?? selectedReference!.id,
            name: selected?.name ?? selectedReference!.name,
          },
        ],
      });
      downloadBlob(blob, filename);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : "下载未完成");
    } finally {
      setDownloading(false);
    }
  };
  const downloadStatistics = () => {
    const fields = [
      "code",
      "name",
      "pixelCount",
      "areaKm2",
      "percent",
    ] as const;
    const text = [
      fields.join(","),
      ...categories.map((row) =>
        fields.map((field) => JSON.stringify(row[field])).join(","),
      ),
    ].join("\n");
    downloadBlob(
      new Blob(["\ufeff", text], { type: "text/csv;charset=utf-8" }),
      "地表覆盖分类统计.csv",
    );
  };
  const empty = (
    <Empty
      image={Empty.PRESENTED_IMAGE_SIMPLE}
      description={ui(
        hasResult ? "该成果未登记类别面积" : "该样区暂无分类成果",
        hasResult
          ? "Class areas are not registered"
          : "No classification for this region",
      )}
    />
  );
  return (
    <MonitorDashboardFrame
      config={config}
      scene="landcover"
      navigation={navigation}
      updatedAt={selected?.registeredAt}
      sourceLabel={
        selection.view === "standard"
          ? ui("上传标准成果", "Uploaded reference")
          : ui("RGB影像 · UNet地表解译", "RGB imagery · UNet land cover")
      }
      status={() =>
        selected?.name ??
        selectedReference?.name ??
        ui("环江油田原始影像", "Huanjiang source imagery")
      }
      actions={
        <>
          <Button
            size="small"
            type="primary"
            disabled={!page?.businessFlow}
            onClick={() => setDrawer(running ? "current" : "new")}
          >
            {running
              ? ui("查看任务", "View task")
              : ui("开始解译", "Interpret imagery")}
          </Button>
          <Button size="small" onClick={() => setDrawer("records")}>
            {ui("处理记录", "Task records")}
          </Button>
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={() => setRevision((value) => value + 1)}
          >
            {ui("刷新成果", "Refresh products")}
          </Button>
        </>
      }
    >
      {({ animated }) => (
        <>
          <MonitorDataStatus
            title={ui("成果资料", "Product data")}
            loading={loading}
            error={failure}
          />
          <main className="monitor-layout">
            <section
              className="monitor-globe-panel"
              aria-label={ui("地表覆盖地图", "Land-cover map")}
            >
              <Suspense
                fallback={
                  <MonitorDataStatus
                    title={ui("准备地图", "Preparing map")}
                    loading
                  />
                }
              >
                <ComparisonMap
                  product={selected}
                  displayResource={selectedReference}
                  original={original}
                  overview={page?.inputBoundary}
                  config={config}
                  animated={animated}
                  mode={displayMode}
                  visibleCodes={visibleCodes}
                />
              </Suspense>
              <div className="landcover-map-toolbar">
                <Segmented
                  aria-label={ui("影像对比方式", "Comparison mode")}
                  value={displayMode}
                  onChange={(value) => setMode(value as LandcoverView)}
                  options={[
                    {
                      value: "classification",
                      label: ui("分类", "Classes"),
                      disabled: !hasResult,
                    },
                    { value: "original", label: ui("原图", "RGB") },
                    {
                      value: "overlay",
                      label: ui("叠加", "Overlay"),
                      disabled: !hasResult,
                    },
                    {
                      value: "swipe",
                      label: ui("卷帘", "Swipe"),
                      disabled: !hasResult,
                    },
                  ]}
                />
              </div>
            </section>
            <div className="monitor-information">
              <div className="monitor-summary">
                <div>
                  <span>{ui("可用样区", "Regions")}</span>
                  <strong>
                    {resources.length}
                    <small>{ui("处", "")}</small>
                  </strong>
                </div>
                <div>
                  <span>
                    {task.flow
                      ? ui("本次完成", "This run")
                      : selection.batch
                        ? ui("最近完成", "Latest run")
                        : ui("项目成果", "Project products")}
                  </span>
                  <strong>
                    {completedSources.size}
                    <small>{ui("处", "")}</small>
                  </strong>
                </div>
                <div>
                  <span>{ui("地面分辨率", "Resolution")}</span>
                  <strong>
                    2<small>m</small>
                  </strong>
                </div>
              </div>
              <MonitorPanel title={ui("样区与成果", "Regions and products")}>
                <div className="landcover-card-body">
                  <Select
                    aria-label={ui("选择解译样区", "Select region")}
                    value={selectedSource}
                    onChange={setSourceId}
                    options={[
                      { value: 0, label: ui("样区总览", "Region overview") },
                      ...resources.map((resource) => ({
                        value: resource.id,
                        label: resource.name.replace(
                          /^环江油田_RGB原始影像_/,
                          "",
                        ),
                      })),
                    ]}
                  />
                  <MonitorProductSelector selection={selection} />
                  {page?.nextBeforeId && (
                    <Button
                      type="link"
                      size="small"
                      onClick={() => void products.loadMore()}
                    >
                      {ui("更多成果", "More products")}
                    </Button>
                  )}
                </div>
              </MonitorPanel>
              <MonitorPanel
                title={ui("解译任务", "Interpretation task")}
                extra={
                  <Button
                    type="link"
                    size="small"
                    onClick={() => setDrawer(running ? "current" : "new")}
                  >
                    {running
                      ? ui("查看任务", "View task")
                      : ui("开始任务", "Start task")}
                  </Button>
                }
              >
                <div className="landcover-card-body">
                  {task.flow ? (
                    <>
                      <span
                        className="landcover-secondary"
                        title={task.flow.id}
                      >
                        本次任务 · {task.flow.id.slice(0, 8)}
                      </span>
                      <strong className="landcover-task-status">
                        {statusNames[task.flow.status] ?? task.flow.status}
                      </strong>
                      <p>
                        {task.flow.nodes.find(
                          (node) => node.nodeId === task.flow?.currentNode,
                        )?.executor.status === "running"
                          ? task.flow.definitionSnapshot.nodes.find(
                              (node) => node.id === task.flow?.currentNode,
                            )?.title
                          : `${completed}/${task.flow.nodes.length} ${ui("个目标完成", "goals complete")}`}
                      </p>
                      <Button
                        type="link"
                        size="small"
                        onClick={() => setDrawer("current")}
                      >
                        {ui("打开任务", "Open task")}
                      </Button>
                    </>
                  ) : (
                    <p>
                      {ui(
                        "选择样区和提取类型后开始",
                        "Choose regions and classes to begin",
                      )}
                    </p>
                  )}
                  {task.error && <span>{task.error}</span>}
                </div>
              </MonitorPanel>
              <MonitorPanel title={ui("类型面积", "Class area")}>
                <div className="landcover-card-body landcover-area-list">
                  {categories.length
                    ? categories.map((row) => (
                        <div key={row.code}>
                          <span>
                            <i style={{ background: row.color }} />
                            {row.name}
                          </span>
                          <strong>
                            {row.areaKm2.toFixed(3)} <small>km²</small>
                          </strong>
                        </div>
                      ))
                    : empty}
                </div>
              </MonitorPanel>
              <MonitorPanel title={ui("类别构成", "Class composition")}>
                <div className="landcover-card-body">
                  {categories.length
                    ? categories.map((row) => (
                        <div className="landcover-composition" key={row.code}>
                          <Checkbox
                            checked={!hidden.includes(row.code)}
                            onChange={(event) =>
                              setHidden((previous) =>
                                event.target.checked
                                  ? previous.filter((code) => code !== row.code)
                                  : [...previous, row.code],
                              )
                            }
                          >
                            {row.name}
                          </Checkbox>
                          <div className="landcover-bar">
                            <span
                              style={{
                                width: `${row.percent}%`,
                                background: row.color,
                              }}
                            />
                          </div>
                          <span>{row.percent.toFixed(1)}%</span>
                        </div>
                      ))
                    : empty}
                </div>
              </MonitorPanel>
              <MonitorPanel title={ui("模型与规则", "Models and rules")}>
                <div className="landcover-card-body">
                  {selection.view === "standard" ? (
                    <>
                      <strong>
                        {ui("上传标准成果", "Uploaded reference")}
                      </strong>
                      <p>{selectedReference?.name ?? selected?.name}</p>
                      <span>
                        {ui(
                          "用于与系统解译成果对照",
                          "Reference for comparison with interpretation results",
                        )}
                      </span>
                    </>
                  ) : (
                    <>
                      {" "}
                      <strong>UNet</strong>
                      <p>
                        {selected?.model?.variant ??
                          ui(
                            "五类模型 · 完整地表覆盖",
                            "Five models · complete land cover",
                          )}
                      </p>
                      <div className="landcover-priority">
                        {ui(
                          "建筑 › 水体 › 耕地 › 林地 › 道路",
                          "Buildings › water › farmland › forest › roads",
                        )}
                      </div>
                      <span className="landcover-secondary">
                        {ui(
                          "16m²小斑块处理 · 保留边界目标",
                          "16m² filtering · preserve border objects",
                        )}
                      </span>
                    </>
                  )}
                </div>
              </MonitorPanel>
              <MonitorPanel title={ui("成果说明", "Product details")}>
                <div className="landcover-card-body">
                  <p>
                    {selected
                      ? `${ui("有效统计面积", "Valid area")} ${selected.metrics.find((metric) => metric.key === "valid_area_km2")?.value?.toFixed(3) ?? "—"} km²`
                      : ui(
                          "按选中样区分别统计",
                          "Statistics are region-specific",
                        )}
                  </p>
                  {hasResult && (
                    <>
                      <span className="landcover-secondary">
                        {selected
                          ? new Date(selected.registeredAt).toLocaleString()
                          : ui("上传标准成果", "Uploaded reference")}
                      </span>
                      <Button
                        type="link"
                        loading={downloading}
                        onClick={() => void download()}
                      >
                        {ui("下载成果", "Download result")}
                      </Button>
                      <Button
                        type="link"
                        disabled={!categories.length}
                        onClick={downloadStatistics}
                      >
                        {ui("下载统计", "Download statistics")}
                      </Button>
                      {downloadError && <span>{downloadError}</span>}
                    </>
                  )}
                  <details>
                    <summary>{ui("来源与口径", "Sources and method")}</summary>
                    {selection.view === "standard" ? (
                      <>
                        <p>
                          {ui(
                            "按上传资料的登记内容展示",
                            "Displayed from the uploaded data record",
                          )}
                        </p>
                        {selectedReference?.source && (
                          <p>{selectedReference.source}</p>
                        )}
                      </>
                    ) : (
                      <>
                        <p>
                          {selected?.statisticsMethod ??
                            ui(
                              "原始RGB影像、固定模型权重与原始网格",
                              "Original RGB, fixed weights and native grid",
                            )}
                        </p>
                        <p>
                          {ui(
                            "裸地表示五类之外的有效剩余区。",
                            "Bare land denotes valid pixels not covered by the five models.",
                          )}
                        </p>
                      </>
                    )}
                  </details>
                </div>
              </MonitorPanel>
            </div>
          </main>
          {drawer && (
            <LandcoverTaskDrawer
              page={page}
              flow={task.flow}
              onChanged={task.accept}
              onClose={() => setDrawer(undefined)}
              records={drawer === "records"}
              startNew={drawer === "new"}
              defaultSourceId={selectedSource || undefined}
            />
          )}
        </>
      )}
    </MonitorDashboardFrame>
  );
}
