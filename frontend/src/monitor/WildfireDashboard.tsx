import { ReloadOutlined } from "@ant-design/icons";
import { Button, Empty, Segmented } from "antd";
import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type CSSProperties,
} from "react";
import { useNavigate } from "react-router-dom";
import type {
  ProjectMonitorConfig,
  WildfireObservationCatalog,
  WildfireSeriesPoint,
  ResourceListItem,
} from "../api/generated/types.gen";
import { api, requestJson } from "../api/client";
import { useAppContext } from "../contexts/AppContext";
import { downloadBlob } from "../utils/download";
import MonitorDashboardFrame from "./MonitorDashboardFrame";
import { MonitorPanel } from "./MonitorPanels";
import { MonitorDataStatus } from "./MonitorLayerStatus";
import MonitorProductSelector from "./MonitorProductSelector";
import { useMonitorProductSelection } from "./useMonitorProductSelection";
import { useMonitorTask } from "./useMonitorTask";
import { useMonitoringProducts } from "./useMonitoringProducts";
import { monitorResourceProfile } from "./resourceProfiles";
import WildfireTaskDrawer from "./WildfireTaskDrawer";
import "./wildfire-monitor.css";

const ProductMap = lazy(() => import("./ProductMap"));
const states: Record<string, string> = {
  queued: "等待执行",
  running: "处理中",
  waiting_compute: "观测制图中",
  waiting_approval: "等待处理",
  succeeded: "已完成",
  failed: "未完成",
  paused: "已暂停",
  cancelled: "已停止",
  interrupted: "已中断",
};

function Series({ rows, unit }: { rows: WildfireSeriesPoint[]; unit: string }) {
  const valid = rows.filter((row) => row.value !== null);
  if (!valid.length)
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="生成观测任务后查看区域序列"
      />
    );
  const first = Date.parse(rows[0]!.observedStart),
    last = Date.parse(rows[rows.length - 1]!.observedStart),
    maximum = Math.max(...valid.map((row) => row.value!), 1);
  const x = (row: WildfireSeriesPoint) =>
    18 +
    ((Date.parse(row.observedStart) - first) / Math.max(1, last - first)) * 280;
  const y = (row: WildfireSeriesPoint) => 105 - (row.value! / maximum) * 78;
  const segments: string[] = [];
  let current = "";
  for (const row of rows) {
    if (row.value === null) {
      if (current) segments.push(current);
      current = "";
    } else current += (current ? " L " : "M ") + x(row) + " " + y(row);
  }
  if (current) segments.push(current);
  return (
    <div className="wildfire-series">
      <span>
        {maximum.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} {unit}
      </span>
      <svg viewBox="0 0 320 140" role="img" aria-label="研究区观测序列">
        <path
          d="M 18 30 H 298 M 18 68 H 298 M 18 105 H 298"
          stroke="#244455"
          fill="none"
          strokeDasharray="3 4"
        />
        {segments.map((segment) => (
          <path
            key={segment}
            d={segment}
            stroke="#fba557"
            strokeWidth="2"
            fill="none"
          />
        ))}
        {valid.map((row) => (
          <circle
            key={row.observedStart}
            cx={x(row)}
            cy={y(row)}
            r="2.5"
            fill="#ffe19c"
          >
            <title>{`${row.observedStart} — ${row.observedEnd}：${row.value} ${unit}`}</title>
          </circle>
        ))}
        <text x="18" y="132">
          {rows[0]?.observedStart}
        </text>
        <text x="298" y="132" textAnchor="end">
          {rows[rows.length - 1]?.observedStart}
        </text>
      </svg>
    </div>
  );
}

export default function WildfireDashboard({
  config,
  navigation,
  projectId,
}: {
  config: ProjectMonitorConfig;
  navigation: ReactNode;
  projectId: number;
}) {
  const { user } = useAppContext();
  const navigate = useNavigate();
  const products = useMonitoringProducts("wildfire");
  const { page, loading, failure, setRevision } = products;
  const [catalog, setCatalog] = useState<WildfireObservationCatalog>();
  const [catalogError, setCatalogError] = useState<string>();
  const [drawer, setDrawer] = useState<"new" | "current" | "records">();
  const [mode, setMode] = useState<"styled" | "values">("styled");
  const [busy, setBusy] = useState(false);
  const [downloadError, setDownloadError] = useState<string>();
  const current = useRef<(() => void) | undefined>(undefined);
  const task = useMonitorTask(
    projectId,
    user?.id,
    () => {
      current.current?.();
      setMode("styled");
      setRevision((v) => v + 1);
    },
    page?.businessFlow?.definitionId,
    "wildfire",
  );
  const selection = useMonitorProductSelection({
    items: page?.items ?? [],
    references: page?.referenceResources ?? [],
    currentBatchId: task.flow?.id,
  });
  current.current = selection.showCurrent;
  const selected = selection.selected;
  const reference = selection.reference;
  const observation = selected?.observation;
  const classification = selected?.attachments?.find(
    (row) => row.role === "classification",
  )?.resource;
  const display =
    reference ??
    (mode === "styled" && classification ? classification : selected?.resource);
  const value = (key: string) =>
    selected?.metrics.find((row) => row.key === key)?.value;
  const unit =
    observation?.unit ?? (value("frp_w_m2") != null ? "W m-2" : "ha");
  const metricKey = unit === "ha" ? "burned_area_ha" : "frp_w_m2";
  const number = (amount: number | null | undefined, suffix: string) => {
    const text =
      amount == null
        ? "—"
        : amount.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
    return (
      <strong
        style={
          { "--wildfire-value-width": text.length * 0.62 } as CSSProperties
        }
      >
        <span>{text}</span>
        <small>{suffix}</small>
      </strong>
    );
  };
  const active = Boolean(
    task.flow &&
    [
      "queued",
      "running",
      "waiting_compute",
      "waiting_approval",
      "paused",
    ].includes(task.flow.status),
  );
  useEffect(() => {
    const controller = new AbortController();
    setCatalogError(undefined);
    void requestJson<WildfireObservationCatalog>(
      "/api/ecology/wildfire/catalog/",
      { signal: controller.signal },
    )
      .then((value) => {
        if (!controller.signal.aborted) setCatalog(value);
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setCatalog(undefined);
          setCatalogError(
            error instanceof Error ? error.message : "时间目录暂时不可用",
          );
        }
      });
    return () => controller.abort();
  }, [projectId]);
  const download = async (resource?: ResourceListItem) => {
    if (!resource || busy) return;
    if (resource.dataType === "vector") {
      navigate(`/map?projectTagId=${projectId}&resources=${resource.id}`);
      return;
    }
    setBusy(true);
    setDownloadError(undefined);
    try {
      const info = await monitorResourceProfile(resource);
      if (!info.raster?.id) throw new Error("该成果尚无栅格数据集");
      const result = await api.exportLayers({
        reproject: false,
        clip: false,
        items: [
          {
            layerType: "raster",
            datasetId: info.raster.id,
            resourceId: resource.id,
            name: resource.name,
          },
        ],
      });
      downloadBlob(result.blob, result.filename);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : "下载未完成");
    } finally {
      setBusy(false);
    }
  };
  const exportTable = (series: boolean) => {
    if (!selected) return;
    const rows = series
      ? (observation?.series ?? [])
      : selected.metrics.map((row) => ({
          metric: row.label,
          value: row.value,
          unit: row.unit,
        }));
    if (!rows.length) return;
    const keys = Object.keys(rows[0]!);
    const text = [
      keys.join(","),
      ...rows.map((row) =>
        keys
          .map((key) =>
            JSON.stringify((row as Record<string, unknown>)[key] ?? ""),
          )
          .join(","),
      ),
    ].join("\n");
    downloadBlob(
      new Blob(["\ufeff" + text], { type: "text/csv;charset=utf-8" }),
      series ? "野火观测序列.csv" : "野火观测统计.csv",
    );
  };
  return (
    <MonitorDashboardFrame
      config={config}
      scene="wildfire"
      navigation={navigation}
      updatedAt={selected?.registeredAt}
      sourceLabel="SeasFire · 历史观测"
      status={() => selected?.name ?? reference?.name ?? "野火历史观测"}
      actions={
        <>
          <Button
            type="primary"
            size="small"
            disabled={
              !page?.businessFlow || !catalog?.cube || !catalog.times.length
            }
            onClick={() => setDrawer(active ? "current" : "new")}
          >
            {active ? "查看任务" : "生成观测图"}
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
            title="野火观测资料"
            loading={loading}
            error={failure ?? catalogError ?? downloadError}
          />
          <main className="monitor-layout">
            <section className="monitor-globe-panel" aria-label="野火观测地图">
              <Suspense
                fallback={<MonitorDataStatus title="准备观测图" loading />}
              >
                <ProductMap
                  resource={display}
                  config={config}
                  animated={animated}
                  focusProduct
                  focusKey={display?.id}
                />
              </Suspense>
              {classification && (
                <div className="wildfire-map-toolbar">
                  <Segmented
                    aria-label="观测图显示方式"
                    value={mode}
                    onChange={(value) => setMode(value as typeof mode)}
                    options={[
                      { value: "styled", label: "观测分级" },
                      { value: "values", label: "观测原值" },
                    ]}
                  />
                </div>
              )}
            </section>
            <div className="monitor-information">
              <div className="monitor-summary">
                <div>
                  <span>观测网格</span>
                  <strong>
                    0.25<small>°</small>
                  </strong>
                </div>
                <div>
                  <span>时间索引</span>
                  <strong>
                    {catalog?.times.length ?? "—"}
                    <small>期</small>
                  </strong>
                </div>
                <div>
                  <span>当前成果</span>
                  <strong>
                    {selected?.kind === "model"
                      ? "模型结果"
                      : selected
                        ? "历史观测"
                        : "—"}
                  </strong>
                </div>
              </div>
              <MonitorPanel title="时期与观测源">
                <div className="wildfire-card-body">
                  <MonitorProductSelector
                    selection={selection}
                    presentation="list"
                    labels={{
                      current: selection.hasCurrentTask
                        ? "本次制图"
                        : "最近一次制图",
                      history: "历史制图",
                      uploaded: "已登记资料",
                    }}
                  />
                  {selected && (
                    <p className="wildfire-period">
                      {selected.observedStart ?? "日期待补充"}
                      {selected.observedEnd &&
                      selected.observedEnd !== selected.observedStart
                        ? " — " + selected.observedEnd
                        : ""}
                    </p>
                  )}
                  {page?.nextBeforeId && (
                    <Button
                      type="link"
                      onClick={() => void products.loadMore()}
                    >
                      更多成果
                    </Button>
                  )}
                </div>
              </MonitorPanel>
              <MonitorPanel
                title={unit === "ha" ? "火烧面积概况" : "火辐射功率概况"}
              >
                <div className="wildfire-card-body">
                  <div className="wildfire-value">
                    <span>
                      {unit === "ha" ? "观测火烧面积" : "平均火辐射功率密度"}
                    </span>
                    {number(value(metricKey), unit)}
                  </div>
                  <div className="wildfire-grid-metrics">
                    <div>
                      <span>正观测格网</span>
                      {number(observation?.activeCells, "个")}
                    </div>
                    <div>
                      <span>有效格网占比</span>
                      {number(value("valid_coverage_percent"), "%")}
                    </div>
                  </div>
                  <p className="wildfire-secondary">
                    {selected?.sourceLabel ?? "选择已生成的观测成果"}
                  </p>
                </div>
              </MonitorPanel>
              <MonitorPanel
                title="区域观测序列"
                extra={
                  observation && (
                    <span className="wildfire-secondary">
                      {observation.periodMode === "monthly"
                        ? "月度"
                        : "原始周期"}
                    </span>
                  )
                }
              >
                <div className="wildfire-card-body">
                  <Series rows={observation?.series ?? []} unit={unit} />
                </div>
              </MonitorPanel>
              <MonitorPanel
                title="区域制图任务"
                extra={
                  <Button
                    type="link"
                    size="small"
                    disabled={
                      !page?.businessFlow ||
                      !catalog?.cube ||
                      !catalog.times.length
                    }
                    onClick={() => setDrawer(active ? "current" : "new")}
                  >
                    {active ? "查看任务" : "开始任务"}
                  </Button>
                }
              >
                <div className="wildfire-card-body">
                  {task.flow ? (
                    <>
                      <span className="wildfire-secondary">
                        本次任务 · {task.flow.id.slice(0, 8)}
                      </span>
                      <strong className="wildfire-task-status">
                        {states[task.flow.status] ?? task.flow.status}
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
                      <p>选择观测时期和研究区，生成观测图与区域序列</p>
                      <ol className="wildfire-route">
                        {page?.route.map((label, index) => (
                          <li key={label}>
                            <span>{String(index + 1).padStart(2, "0")}</span>
                            {label}
                          </li>
                        ))}
                      </ol>
                    </>
                  )}
                  {task.error && <p>{task.error}</p>}
                </div>
              </MonitorPanel>
              <MonitorPanel title="数据与模型资料">
                <div className="wildfire-card-body">
                  <strong>SeasFire 全球观测立方体</strong>
                  <p>2001–2021 · 原生 Zarr</p>
                  <span className="wildfire-secondary">
                    GWIS / GFED：原始周期
                    <br />
                    FCCI：月度均值
                    <br />
                    CAMS FRP：W m⁻²
                  </span>
                  <details>
                    <summary>模型接入资料</summary>
                    <p>5组U-Net++权重已归档</p>
                    <p>训练归一化、缺测处理与目标期配置待补充</p>
                  </details>
                  {catalog?.cube && (
                    <Button
                      type="link"
                      size="small"
                      onClick={() =>
                        navigate(
                          `/catalog?projectTagId=${projectId}&resourceId=${catalog.cube!.id}`,
                        )
                      }
                    >
                      查看原始资料
                    </Button>
                  )}
                </div>
              </MonitorPanel>
              <MonitorPanel title="成果说明" className="monitor-assessment">
                <div className="wildfire-card-body monitor-assessment-copy">
                  {selected ? (
                    <>
                      <p>{selected.interpretation}</p>
                      <div className="wildfire-downloads">
                        <Button
                          type="link"
                          size="small"
                          loading={busy}
                          onClick={() => void download(selected.resource)}
                        >
                          {observation ? "下载原值" : "下载成果"}
                        </Button>
                        {classification && (
                          <Button
                            type="link"
                            size="small"
                            onClick={() => void download(classification)}
                          >
                            下载分级图
                          </Button>
                        )}
                        <Button
                          type="link"
                          size="small"
                          onClick={() => exportTable(false)}
                        >
                          下载统计
                        </Button>
                        {observation && (
                          <Button
                            type="link"
                            size="small"
                            onClick={() => exportTable(true)}
                          >
                            下载序列
                          </Button>
                        )}
                      </div>
                      <details>
                        <summary>来源与统计口径</summary>
                        <p>{selected.statisticsMethod}</p>
                      </details>
                    </>
                  ) : reference ? (
                    <p>{reference.name}</p>
                  ) : (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="暂无观测成果"
                    />
                  )}
                </div>
              </MonitorPanel>
            </div>
          </main>
          {drawer && (
            <WildfireTaskDrawer
              catalog={catalog}
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
