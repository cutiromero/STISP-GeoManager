import {
  AimOutlined,
  BarChartOutlined,
  ClusterOutlined,
  CloudUploadOutlined,
  DatabaseOutlined,
  EnvironmentOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
  HeatMapOutlined,
  HddOutlined,
  VideoCameraOutlined,
  PieChartOutlined,
} from "@ant-design/icons";
import { ProCard } from "@ant-design/pro-components";
import {
  App,
  BorderBeam,
  Button,
  Card,
  Col,
  Empty,
  Progress,
  Row,
  Segmented,
  Skeleton,
  Space,
  Statistic,
  Tag,
  Tabs,
  Typography,
} from "antd";
import type { TabsProps } from "antd";
import mapboxgl, {
  type AnyLayer,
  type ExpressionSpecification,
  type GeoJSONSource,
  LngLatBounds,
  type Map as MapboxMap,
  type MapboxOptions,
} from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import type { CSSProperties, ReactNode } from "react";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { api } from "../api/client";
import { oceanBorderBeam } from "../components/oceanBorderBeam";
import { useAppContext } from "../contexts/AppContext";
import {
  applyBasemapExpressionSafety,
  applyChineseBasemapLanguage,
  applySatelliteBasemapColorCorrection,
  createBasemapStyle,
  isOsmRasterTileError,
  mapLabelLanguage,
  shouldUseMapboxBasemap,
} from "../map/basemapStyle";
import { fitBoundsOptions } from "../map/mapViewport";
import type { AdminDashboard, AdminDashboardServer } from "../types";
import { startSequentialPolling } from "../utils/sequentialPolling";
import { useTranslation } from "react-i18next";
import { useEnglishLanguage } from "../i18n/useEnglishLanguage";
import { UserSummaryCards } from "./UserSummaryCards";

const serverRefreshMs = 5000;
type ActivePeriod = "day" | "week" | "month";

const periodLabels: Record<ActivePeriod, string> = {
  day: "今日",
  week: "本周",
  month: "本月",
};

type DataOverviewCard = NonNullable<AdminDashboard["cards"]["dataOverview"]>;
type DataOverviewScope = DataOverviewCard["ownUploads"];
type DataOverviewSpatialSummary = DataOverviewScope["spatialSummary"];
type SpatialViewMode = "extent" | "heatmap";
type HeatmapMetric = "resourceCount" | "itemCount";

const dataTypeLabels: Record<string, string> = {
  vector: "矢量",
  raster: "栅格",
  gene: "基因",
  table: "表格",
  document: "文档",
  image: "图片",
};

const dataTypeColors: Record<string, string> = {
  vector: "#2f9c76",
  raster: "#3f8fd2",
  gene: "#8b6dd7",
  table: "#d58a2a",
  document: "#6f8c87",
  image: "#d45f7a",
};

const categoryColors: Record<string, string> = {
  base_geo: "#397fb8",
  habitat: "#2f9c76",
  distribution: "#d58a2a",
  thematic: "#8b6dd7",
};

type OverviewPolygonFeature = {
  type: "Feature";
  properties: Record<string, number | string>;
  geometry: {
    type: "Polygon";
    coordinates: number[][][];
  };
};

type OverviewPointFeature = {
  type: "Feature";
  properties: Record<string, number | string>;
  geometry: {
    type: "Point";
    coordinates: number[];
  };
};

type OverviewFeatureCollection = {
  type: "FeatureCollection";
  features: Array<OverviewPointFeature | OverviewPolygonFeature>;
};

interface AdminDashboardPageProps {
  scope?: "all" | "data" | "operations";
}

export default function AdminDashboardPage({
  scope = "all",
}: AdminDashboardPageProps) {
  const { message } = App.useApp();
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const { user } = useAppContext();
  const [period, setPeriod] = useState<ActivePeriod>("day");
  const [dashboard, setDashboard] = useState<AdminDashboard | null>(null);
  const [server, setServer] = useState<AdminDashboardServer | null>(null);
  const [dashboardLoading, setDashboardLoading] = useState(true);
  const [serverLoading, setServerLoading] = useState(true);
  const showDataCards = scope === "all" || scope === "data";
  const showOperationCards = scope === "all" || scope === "operations";
  const canViewServerCards = Boolean(
    showOperationCards && user?.permissions.canViewDashboardSystemCard,
  );

  const loadDashboard = useCallback(
    async (signal?: AbortSignal) => {
      setDashboardLoading(true);
      try {
        const nextDashboard = await api.adminDashboard(period, { signal });
        if (!signal?.aborted) {
          setDashboard(nextDashboard);
        }
      } catch (error) {
        if (signal?.aborted) return;
        message.error(
          error instanceof Error
            ? error.message
            : english
              ? "Failed to load overview"
              : "概览加载失败",
        );
      } finally {
        if (!signal?.aborted) {
          setDashboardLoading(false);
        }
      }
    },
    [english, message, period],
  );

  const loadServer = useCallback(
    async (signal: AbortSignal) => {
      if (!canViewServerCards) {
        setServer(null);
        setServerLoading(false);
        return false;
      }
      try {
        const nextServer = await api.adminDashboardServer({ signal });
        if (!signal.aborted) {
          setServer(nextServer);
        }
      } catch (error) {
        if (signal.aborted) return false;
        message.error(
          error instanceof Error
            ? error.message
            : english
              ? "Failed to load server monitoring"
              : "服务器监控加载失败",
        );
      } finally {
        if (!signal.aborted) {
          setServerLoading(false);
        }
      }
      return !signal.aborted;
    },
    [canViewServerCards, english, message],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadDashboard(controller.signal);
    return () => controller.abort();
  }, [loadDashboard]);

  useEffect(() => {
    if (!canViewServerCards) {
      setServer(null);
      setServerLoading(false);
      return;
    }
    setServerLoading(true);
    return startSequentialPolling(loadServer, {
      intervalMs: serverRefreshMs,
      runImmediately: true,
    });
  }, [canViewServerCards, loadServer]);

  const activeChartData = useMemo(() => {
    return (dashboard?.cards.activeUsers?.series ?? []).map((item) => ({
      label: item.label,
      count: item.count,
    }));
  }, [dashboard]);
  const dataOverview = dashboard?.cards.dataOverview;
  const canViewVisibleDataOverview = Boolean(
    user?.permissions.canViewDataOverview && dataOverview?.visibleResources,
  );
  const hasMetricCards = Boolean(
    showDataCards &&
    (scope === "data"
      ? dataOverview
      : dashboard?.cards.resources ||
        dashboard?.cards.layers ||
        dashboard?.cards.rasters ||
        dataOverview),
  );
  const hasServerCards = Boolean(
    server?.cards.cpu ||
    server?.cards.memory ||
    server?.cards.disks ||
    server?.cards.gpu,
  );
  const hasDashboardCards =
    hasMetricCards ||
    Boolean(
      showOperationCards &&
      (dashboard?.cards.users || dashboard?.cards.activeUsers),
    );
  const hasAnyAuthorizedCard = hasDashboardCards || canViewServerCards;

  if (dashboardLoading || !dashboard) {
    return (
      <div className="admin-page-stack">
        <ProCard className="admin-section-card">
          <Skeleton active paragraph={{ rows: 8 }} />
        </ProCard>
      </div>
    );
  }

  return (
    <div className="admin-dashboard admin-page-stack">
      {!hasAnyAuthorizedCard && (
        <ProCard className="admin-section-card">
          <Empty
            description={
              scope === "data"
                ? english
                  ? "This account has no data-overview cards to view"
                  : "当前账号暂无可查看的数据概览卡片"
                : english
                  ? "This account has no overview cards to view"
                  : "当前账号暂无可查看的概览卡片"
            }
          />
        </ProCard>
      )}

      {scope === "data" && dataOverview && (
        <DataOverviewTabs
          overview={dataOverview}
          canViewVisible={canViewVisibleDataOverview}
        />
      )}

      {scope !== "data" && hasMetricCards && (
        <section className="admin-dashboard-section">
          <div className="admin-dashboard-section-heading">
            <Typography.Title level={4}>
              {english ? "Data overview" : "数据概览"}
            </Typography.Title>
          </div>
          <Row gutter={[16, 16]}>
            {dashboard.cards.resources && (
              <MetricCard
                title={english ? "Data resources" : "数据资源"}
                value={dashboard.cards.resources.total}
                suffix={english ? "" : "项"}
                icon={<DatabaseOutlined />}
                description={
                  english
                    ? `${dashboard.cards.resources.active} active`
                    : `启用 ${dashboard.cards.resources.active} 项`
                }
              />
            )}
            {dashboard.cards.layers && (
              <MetricCard
                title={english ? "Layers" : "图层数"}
                value={dashboard.cards.layers.total}
                suffix={english ? "" : "个"}
                icon={<ClusterOutlined />}
                description={
                  english
                    ? `${dashboard.cards.layers.active} active`
                    : `启用 ${dashboard.cards.layers.active} 个`
                }
              />
            )}
            {dashboard.cards.rasters && (
              <MetricCard
                title={english ? "Rasters" : "栅格数量"}
                value={dashboard.cards.rasters.resources}
                suffix={english ? "" : "项"}
                icon={<HddOutlined />}
                description={
                  english
                    ? `${dashboard.cards.rasters.datasets} raster datasets; ${dashboard.cards.rasters.layers} raster layers`
                    : `栅格数据集 ${dashboard.cards.rasters.datasets} 个，栅格图层 ${dashboard.cards.rasters.layers} 个`
                }
              />
            )}
            {dataOverview && (
              <>
                <MetricCard
                  title={english ? "Size of my uploads" : "我上传的数据大小"}
                  value={formatBytes(dataOverview.ownUploads.totalSizeBytes)}
                  suffix=""
                  icon={<CloudUploadOutlined />}
                  description={
                    english
                      ? `${dataOverview.ownUploads.activeResources} / ${dataOverview.ownUploads.totalResources} active`
                      : `启用 ${dataOverview.ownUploads.activeResources} / ${dataOverview.ownUploads.totalResources} 项`
                  }
                />
                <MetricCard
                  title={english ? "Items in my uploads" : "我上传的数据条目"}
                  value={dataOverview.ownUploads.totalItemCount}
                  suffix={english ? "" : "条"}
                  icon={<DatabaseOutlined />}
                  description={
                    english
                      ? "Counted from imported rows, raster datasets, and scanned files"
                      : "按导入行数、栅格数据集和扫描文件统计"
                  }
                />
                {canViewVisibleDataOverview &&
                  dataOverview.visibleResources && (
                    <>
                      <MetricCard
                        title={
                          english ? "Size of visible data" : "我可见的数据大小"
                        }
                        value={formatBytes(
                          dataOverview.visibleResources.totalSizeBytes,
                        )}
                        suffix=""
                        icon={<HddOutlined />}
                        description={
                          english
                            ? `${dataOverview.visibleResources.activeResources} / ${dataOverview.visibleResources.totalResources} active`
                            : `启用 ${dataOverview.visibleResources.activeResources} / ${dataOverview.visibleResources.totalResources} 项`
                        }
                      />
                      <MetricCard
                        title={
                          english ? "Visible data items" : "我可见的数据条目"
                        }
                        value={dataOverview.visibleResources.totalItemCount}
                        suffix={english ? "" : "条"}
                        icon={<DatabaseOutlined />}
                        description={
                          english
                            ? "Based on data accessible to this account"
                            : "按当前账号可访问数据统计"
                        }
                      />
                    </>
                  )}
              </>
            )}
          </Row>
        </section>
      )}

      {showOperationCards && dashboard.cards.users && (
        <section className="admin-dashboard-section">
          <div className="admin-dashboard-section-heading">
            <Typography.Title level={4}>
              {english ? "User information" : "用户信息"}
            </Typography.Title>
            <Typography.Text type="secondary">
              {english
                ? `${dashboard.cards.users.total} accounts in the system`
                : `当前系统共 ${dashboard.cards.users.total} 个账号`}
            </Typography.Text>
          </div>
          <UserSummaryCards
            metrics={{
              active: dashboard.cards.users.active,
              disabled: dashboard.cards.users.disabled,
              groups: dashboard.cards.users.groups,
            }}
          />
        </section>
      )}

      {showOperationCards && dashboard.cards.activeUsers && (
        <section className="admin-dashboard-section">
          <BorderBeam color={oceanBorderBeam}>
            <Card
              className="admin-active-card admin-dashboard-card"
              variant="borderless"
              styles={{ body: { padding: 0 } }}
            >
              <div className="admin-active-tabs">
                <div className="admin-active-tab-current">
                  {english ? "Account activity and sign-ins" : "账号活跃与登录"}
                </div>
                <div className="admin-active-actions">
                  {(["day", "week", "month"] as ActivePeriod[]).map((item) => (
                    <Button
                      type="text"
                      className={period === item ? "active" : ""}
                      key={item}
                      onClick={() => setPeriod(item)}
                    >
                      {periodLabels[item]}
                    </Button>
                  ))}
                  <Tag color="green">
                    {dashboard.cards.activeUsers.rangeStart}{" "}
                    {english ? "to" : "至"}{" "}
                    {dashboard.cards.activeUsers.rangeEnd}
                  </Tag>
                </div>
              </div>
              <Row
                className="admin-active-body"
                gutter={[24, 16]}
                align="stretch"
              >
                <Col xs={24} xl={16}>
                  <div className="admin-active-chart-heading">
                    <Space size={18} wrap>
                      <Statistic
                        title={
                          english
                            ? `${{ day: "Today", week: "This week", month: "This month" }[period]} active accounts`
                            : `${periodLabels[period]}活跃账号`
                        }
                        value={dashboard.cards.activeUsers.count}
                        suffix={english ? "" : "个"}
                      />
                      <Statistic
                        title={english ? "Successful sign-ins" : "成功登录次数"}
                        value={dashboard.cards.activeUsers.loginCount}
                        suffix={english ? "" : "次"}
                      />
                    </Space>
                    <Typography.Text type="secondary">
                      {english
                        ? "Active accounts are deduplicated from authenticated access. Sign-ins include password, guest, and post-registration sessions."
                        : "活跃账号按已认证访问去重；登录次数包含账号密码、游客及注册自动登录"}
                    </Typography.Text>
                  </div>
                  <div className="admin-active-chart">
                    <ActiveUsersChart data={activeChartData} />
                  </div>
                </Col>
                <Col xs={24} xl={8}>
                  <div className="admin-active-rank">
                    <Typography.Title level={4}>
                      {english ? "Sign-in ranking" : "登录次数排名"}
                    </Typography.Title>
                    <ul>
                      {dashboard.cards.activeUsers.ranking.map(
                        (item, index) => (
                          <li key={item.userId}>
                            <span
                              className={
                                index < 3
                                  ? "admin-rank-number active"
                                  : "admin-rank-number"
                              }
                            >
                              {index + 1}
                            </span>
                            <span
                              className="admin-rank-title"
                              title={item.username}
                            >
                              {item.displayName}
                            </span>
                            <span>
                              {english
                                ? `${item.loginCount} sign-ins`
                                : `${item.loginCount} 次`}
                            </span>
                          </li>
                        ),
                      )}
                    </ul>
                    {dashboard.cards.activeUsers.ranking.length === 0 && (
                      <Typography.Text type="secondary">
                        {english
                          ? "No sign-ins in the current period"
                          : "当前周期暂无登录记录"}
                      </Typography.Text>
                    )}
                  </div>
                </Col>
              </Row>
            </Card>
          </BorderBeam>
        </section>
      )}

      {canViewServerCards && (serverLoading || !server || hasServerCards) && (
        <section className="admin-dashboard-section">
          <div className="admin-dashboard-section-heading">
            <Typography.Title level={4}>
              {english ? "Server information" : "服务器信息"}
            </Typography.Title>
            <Typography.Text type="secondary">
              {english ? "Refreshes every 5 seconds" : "每 5 秒自动刷新"}
              {server ? ` / ${formatDateTime(server.generatedAt)}` : ""}
            </Typography.Text>
          </div>
          {serverLoading || !server ? (
            <ProCard className="admin-section-card">
              <Skeleton active paragraph={{ rows: 5 }} />
            </ProCard>
          ) : (
            <Row gutter={[16, 16]}>
              {server.cards.cpu && (
                <ServerCard
                  title="CPU"
                  model={server.cards.cpu.model}
                  usage={server.cards.cpu.usagePercent}
                  lines={[
                    english
                      ? `${server.cards.cpu.physicalCount} physical cores; ${server.cards.cpu.logicalCount} logical cores`
                      : `物理核心 ${server.cards.cpu.physicalCount}，逻辑核心 ${server.cards.cpu.logicalCount}`,
                    english
                      ? `Load ${server.cards.cpu.loadAverage.join(" / ")}`
                      : `负载 ${server.cards.cpu.loadAverage.join(" / ")}`,
                  ]}
                  icon={<BarChartOutlined />}
                />
              )}
              {server.cards.memory && (
                <ServerCard
                  title={english ? "Memory" : "内存"}
                  model={server.cards.memory.model}
                  usage={server.cards.memory.usagePercent}
                  lines={[
                    english
                      ? `${server.cards.memory.slotCount} slots`
                      : `数量 ${server.cards.memory.slotCount}`,
                    `${formatBytes(server.cards.memory.usedBytes)} / ${formatBytes(
                      server.cards.memory.totalBytes,
                    )}`,
                  ]}
                  icon={<DatabaseOutlined />}
                />
              )}
              {server.cards.disks && (
                <ServerCard
                  title={english ? "Platform storage partition" : "平台存储分区"}
                  model={diskModelText(server)}
                  usage={server.cards.disks.usagePercent}
                  lines={[
                    english
                      ? `${server.cards.disks.count} physical disks detected; capacities shown above`
                      : `检测到 ${server.cards.disks.count} 块物理硬盘，容量见型号旁`,
                    `${english ? "Partition used / total" : "所在分区已用 / 总容量"}：${formatBytes(server.cards.disks.usedBytes, true)} / ${formatBytes(
                      server.cards.disks.totalBytes,
                      true,
                    )}`,
                    `${english ? "Available to the platform" : "平台当前可用"}：${formatBytes(server.cards.disks.freeBytes, true)}`,
                  ]}
                  icon={<HddOutlined />}
                />
              )}
              {server.cards.gpu && (
                <ServerCard
                  title={english ? "GPU" : "GPU"}
                  model={gpuModelText(server)}
                  usage={server.cards.gpu.usagePercent}
                  lines={[
                    english
                      ? `${server.cards.gpu.count} device${server.cards.gpu.count === 1 ? "" : "s"}`
                      : `数量 ${server.cards.gpu.count}`,
                    `${formatBytes(server.cards.gpu.usedMemoryBytes)} / ${formatBytes(server.cards.gpu.totalMemoryBytes)}`,
                    ...server.cards.gpu.devices.map((device) =>
                      english
                        ? `GPU ${device.index}: ${device.usagePercent}% / ${formatBytes(device.memoryUsedBytes)} / ${formatBytes(device.memoryTotalBytes)}`
                        : `GPU ${device.index}：${device.usagePercent}% / ${formatBytes(device.memoryUsedBytes)} / ${formatBytes(device.memoryTotalBytes)}`,
                    ),
                  ]}
                  icon={<VideoCameraOutlined />}
                />
              )}
            </Row>
          )}
        </section>
      )}
    </div>
  );
}

function ActiveUsersChart({
  data,
}: {
  data: { label: string; count: number }[];
}) {
  const english = useEnglishLanguage();
  const maxCount = Math.max(...data.map((item) => item.count), 0);
  if (data.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={english ? "No data" : "暂无数据"}
      />
    );
  }
  return (
    <div
      className="admin-active-lite-chart"
      role="list"
      aria-label={english ? "Active-account bar chart" : "活跃账号柱状图"}
    >
      {data.map((item) => {
        const ratio = maxCount > 0 ? item.count / maxCount : 0;
        return (
          <div
            className="admin-active-lite-bar"
            role="listitem"
            key={item.label}
            title={
              english
                ? `${item.label}: ${item.count} active accounts`
                : `${item.label}：${item.count} 个活跃账号`
            }
          >
            <div className="admin-active-lite-bar-track">
              <div
                className="admin-active-lite-bar-fill"
                style={{
                  height: `${Math.max(ratio * 100, item.count ? 6 : 0)}%`,
                }}
              />
            </div>
            <div className="admin-active-lite-bar-value">{item.count}</div>
            <div className="admin-active-lite-bar-label">{item.label}</div>
          </div>
        );
      })}
    </div>
  );
}

function MetricCard({
  title,
  value,
  suffix = "",
  icon,
  description,
  accent,
}: {
  title: string;
  value: ReactNode;
  suffix?: string;
  icon: ReactNode;
  description: string;
  accent?: string;
}) {
  const isStatisticValue =
    typeof value === "number" || typeof value === "string";

  return (
    <Col xs={24} sm={12} xl={8}>
      <BorderBeam color={oceanBorderBeam}>
        <Card
          className="admin-dashboard-metric"
          variant="borderless"
          style={
            accent
              ? ({ "--metric-accent": accent } as CSSProperties)
              : undefined
          }
        >
          <div className="admin-dashboard-metric-icon">{icon}</div>
          {isStatisticValue ? (
            <Statistic title={title} value={value} suffix={suffix} />
          ) : (
            <div className="admin-dashboard-metric-custom">
              <Typography.Text type="secondary">{title}</Typography.Text>
              {value}
            </div>
          )}
          <Typography.Text type="secondary">{description}</Typography.Text>
        </Card>
      </BorderBeam>
    </Col>
  );
}

function CompactBoundsMetric({
  bounds,
}: {
  bounds: [number, number, number, number];
}) {
  const english = useEnglishLanguage();
  return (
    <div className="admin-dashboard-bounds-value">
      <span>
        <small>{english ? "Longitude" : "经度"}</small>
        <strong>
          {formatCoordinateLabel(bounds[0], "lng")} -{" "}
          {formatCoordinateLabel(bounds[2], "lng")}
        </strong>
      </span>
      <span>
        <small>{english ? "Latitude" : "纬度"}</small>
        <strong>
          {formatCoordinateLabel(bounds[1], "lat")} -{" "}
          {formatCoordinateLabel(bounds[3], "lat")}
        </strong>
      </span>
    </div>
  );
}

function DataOverviewTabs({
  overview,
  canViewVisible,
}: {
  overview: DataOverviewCard;
  canViewVisible: boolean;
}) {
  const english = useEnglishLanguage();
  const items: TabsProps["items"] = [];
  if (canViewVisible && overview.visibleResources) {
    items.push({
      key: "visibleResources",
      label: english ? "Visible to me" : "我可见的",
      children: (
        <DataOverviewScopePanel
          title={english ? "Visible-data overview" : "我可见的数据概览"}
          scope={overview.visibleResources}
          itemDescription={
            english
              ? "Calculated from data accessible to the current account"
              : "按当前账号可访问数据统计"
          }
          footer={
            overview.uploaders && overview.uploaders.length > 0 ? (
              <DataOverviewUploaders uploaders={overview.uploaders} />
            ) : undefined
          }
        />
      ),
    });
  }
  items.push({
    key: "ownUploads",
    label: english ? "My uploads" : "我上传的",
    children: (
      <DataOverviewScopePanel
        title={english ? "My-upload overview" : "我上传的数据概览"}
        scope={overview.ownUploads}
        itemDescription={
          english
            ? "Calculated from data uploaded by the current account"
            : "按当前账号上传的数据统计"
        }
      />
    ),
  });
  return <Tabs className="admin-dashboard-tabs" items={items} />;
}

function DataOverviewScopePanel({
  title,
  scope,
  itemDescription,
  footer,
}: {
  title: string;
  scope: DataOverviewScope;
  itemDescription: string;
  footer?: ReactNode;
}) {
  const english = useEnglishLanguage();
  const spatialSummary = scope.spatialSummary;
  return (
    <div className="admin-page-stack">
      <section className="admin-dashboard-section">
        <div className="admin-dashboard-section-heading">
          <Typography.Title level={4}>{title}</Typography.Title>
        </div>
        <Row gutter={[16, 16]}>
          <MetricCard
            title={english ? "Data resources" : "数据资源"}
            value={scope.totalResources}
            suffix={english ? "" : "项"}
            icon={<DatabaseOutlined />}
            description={
              english
                ? `${scope.activeResources} enabled`
                : `启用 ${scope.activeResources} 项`
            }
            accent="#2f9c76"
          />
          <MetricCard
            title={english ? "Data size" : "数据大小"}
            value={formatBytes(scope.totalSizeBytes)}
            icon={<HddOutlined />}
            description={
              english
                ? "Calculated from registered data-file sizes"
                : "按已登记数据文件大小统计"
            }
            accent="#3f8fd2"
          />
          <MetricCard
            title={english ? "Data items" : "数据条目"}
            value={scope.totalItemCount}
            suffix={english ? "" : "条"}
            icon={<DatabaseOutlined />}
            description={itemDescription}
            accent="#d58a2a"
          />
          <MetricCard
            title={english ? "Spatial data" : "空间数据"}
            value={spatialSummary.spatialResourceCount}
            suffix={english ? "" : "项"}
            icon={<AimOutlined />}
            description={
              spatialSummary.missingSpatialResourceCount > 0
                ? english
                  ? `${spatialSummary.missingSpatialResourceCount} resources have no spatial extent`
                  : `${spatialSummary.missingSpatialResourceCount} 项暂无空间范围`
                : english
                  ? "Longitude/latitude extents are available"
                  : "具备可解析经纬度范围"
            }
            accent="#8b6dd7"
          />
          <MetricCard
            title={english ? "Spatial coverage" : "空间覆盖"}
            value={
              hasBounds(spatialSummary.totalBounds) ? (
                <CompactBoundsMetric bounds={spatialSummary.totalBounds} />
              ) : english ? (
                "No extent"
              ) : (
                "暂无范围"
              )
            }
            icon={<EnvironmentOutlined />}
            description={
              hasBounds(spatialSummary.totalBounds)
                ? english
                  ? "Merged from visible data in the current scope"
                  : "按当前范围内可见数据合并"
                : english
                  ? "Shown automatically after spatial extents are imported"
                  : "导入空间范围后自动展示"
            }
            accent="#d45f7a"
          />
        </Row>
        <DataOverviewSpatialPanel scope={scope} />
        <div className="admin-overview-analytics-grid">
          <DataTypeDistributionCard scope={scope} />
          <BusinessCategoryDistributionCard scope={scope} />
        </div>
        {footer}
      </section>
    </div>
  );
}

function DataOverviewUploaders({
  uploaders,
}: {
  uploaders: NonNullable<DataOverviewCard["uploaders"]>;
}) {
  const english = useEnglishLanguage();
  const maxResources = Math.max(
    ...uploaders.map((item) => item.resourceCount),
    0,
  );
  return (
    <BorderBeam color={oceanBorderBeam}>
      <Card className="admin-dashboard-card admin-overview-panel-card">
        <PanelTitle
          icon={<CloudUploadOutlined />}
          title={english ? "Uploader contribution ranking" : "上传者贡献排行"}
        />
        <div className="admin-uploader-rank-list">
          {uploaders.map((item, index) => {
            const ratio =
              maxResources > 0 ? item.resourceCount / maxResources : 0;
            return (
              <div
                key={`${item.user.id}-${item.user.username}`}
                className="admin-uploader-rank-row"
              >
                <div className="admin-uploader-avatar">
                  {displayInitial(item.user.displayName || item.user.username)}
                </div>
                <div className="admin-uploader-main">
                  <div className="admin-uploader-title-line">
                    <Typography.Text strong title={item.user.displayName}>
                      {item.user.displayName ||
                        (english ? "Not recorded" : "未记录")}
                    </Typography.Text>
                  </div>
                  <Typography.Text type="secondary">
                    {item.user.username ||
                      (english ? "Account not recorded" : "未记录账号")}
                  </Typography.Text>
                  <div className="admin-uploader-rank-track">
                    <span style={{ width: `${Math.max(ratio * 100, 8)}%` }} />
                  </div>
                </div>
                <div className="admin-uploader-rank-badge">
                  <Tag color={index < 3 ? "gold" : "default"}>
                    TOP {index + 1}
                  </Tag>
                </div>
                <div className="admin-uploader-metrics">
                  <span>
                    <strong>{item.resourceCount}</strong>
                    <small>{english ? "resources" : "项资源"}</small>
                  </span>
                  <span>
                    <strong>{formatBytes(item.sizeBytes)}</strong>
                    <small>{english ? "data size" : "数据量"}</small>
                  </span>
                  <span>
                    <strong>{formatNumber(item.itemCount)}</strong>
                    <small>{english ? "items" : "条目"}</small>
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </BorderBeam>
  );
}

function DataOverviewSpatialPanel({ scope }: { scope: DataOverviewScope }) {
  const english = useEnglishLanguage();
  const [viewMode, setViewMode] = useState<SpatialViewMode>("extent");
  const [heatmapMetric, setHeatmapMetric] =
    useState<HeatmapMetric>("resourceCount");
  const [showHeatmapRanges, setShowHeatmapRanges] = useState(true);
  const summary = scope.spatialSummary;
  const canShowHeatmap = summary.heatmapCells.length > 0;
  const activeViewMode =
    viewMode === "heatmap" && canShowHeatmap ? "heatmap" : "extent";
  const showRangeOverlays = activeViewMode !== "heatmap" || showHeatmapRanges;
  const spatialTotal =
    summary.spatialResourceCount + summary.missingSpatialResourceCount;
  const spatialCoverageRatio =
    spatialTotal > 0
      ? Math.round((summary.spatialResourceCount / spatialTotal) * 100)
      : 0;

  return (
    <BorderBeam color={oceanBorderBeam}>
      <Card className="admin-dashboard-card admin-spatial-overview-card">
        <div className="admin-spatial-overview-heading">
          <PanelTitle
            icon={<HeatMapOutlined />}
            title={english ? "Spatial coverage overview" : "空间覆盖概览"}
          />
          <Space className="admin-spatial-mode-controls" wrap>
            <Segmented
              size="large"
              value={activeViewMode}
              options={[
                {
                  label: (
                    <span className="admin-spatial-segment-label">
                      <AimOutlined />
                      {english ? "Extents" : "范围框"}
                    </span>
                  ),
                  value: "extent",
                },
                {
                  label: (
                    <span className="admin-spatial-segment-label">
                      <HeatMapOutlined />
                      {english ? "Heatmap" : "热力图"}
                    </span>
                  ),
                  value: "heatmap",
                  disabled: !canShowHeatmap,
                },
              ]}
              onChange={(value) => setViewMode(value as SpatialViewMode)}
            />
            <Segmented
              size="large"
              value={heatmapMetric}
              disabled={activeViewMode !== "heatmap"}
              options={[
                {
                  label: (
                    <span className="admin-spatial-segment-label">
                      <ClusterOutlined />
                      {english ? "By dataset" : "按数据集"}
                    </span>
                  ),
                  value: "resourceCount",
                },
                {
                  label: (
                    <span className="admin-spatial-segment-label">
                      <DatabaseOutlined />
                      {english ? "By items" : "按条目"}
                    </span>
                  ),
                  value: "itemCount",
                },
              ]}
              onChange={(value) => setHeatmapMetric(value as HeatmapMetric)}
            />
            {activeViewMode === "heatmap" && (
              <Button
                className="admin-spatial-overlay-toggle"
                icon={
                  showHeatmapRanges ? <EyeInvisibleOutlined /> : <EyeOutlined />
                }
                onClick={() => setShowHeatmapRanges((value) => !value)}
              >
                {showHeatmapRanges
                  ? english
                    ? "Hide extents"
                    : "隐藏范围框"
                  : english
                    ? "Show extents"
                    : "显示范围框"}
              </Button>
            )}
          </Space>
        </div>
        <div className="admin-spatial-overview-body">
          <DataOverviewMap
            summary={summary}
            viewMode={activeViewMode}
            heatmapMetric={heatmapMetric}
            showRangeOverlays={showRangeOverlays}
          />
          <div className="admin-spatial-side-panel">
            <div className="admin-spatial-side-stats">
              <OverviewMiniStat
                label={english ? "Spatial data" : "空间数据"}
                value={
                  english
                    ? `${summary.spatialResourceCount}`
                    : `${summary.spatialResourceCount} 项`
                }
              />
              <OverviewMiniStat
                label={english ? "Extent parsing rate" : "范围解析率"}
                value={`${spatialCoverageRatio}%`}
              />
              <OverviewMiniStat
                label={english ? "Heatmap cells" : "热力网格"}
                value={
                  english
                    ? `${summary.heatmapCells.length}`
                    : `${summary.heatmapCells.length} 个`
                }
              />
            </div>
            <div className="admin-spatial-bounds-block">
              <Typography.Text strong>
                {english ? "Merged coverage extent" : "合并覆盖范围"}
              </Typography.Text>
              <Typography.Text type="secondary">
                {hasBounds(summary.totalBounds)
                  ? english
                    ? `Longitude ${formatCoordinateLabel(
                        summary.totalBounds[0],
                        "lng",
                      )} - ${formatCoordinateLabel(
                        summary.totalBounds[2],
                        "lng",
                      )}, latitude ${formatCoordinateLabel(
                        summary.totalBounds[1],
                        "lat",
                      )} - ${formatCoordinateLabel(summary.totalBounds[3], "lat")}`
                    : `经度 ${formatCoordinateLabel(
                        summary.totalBounds[0],
                        "lng",
                      )} - ${formatCoordinateLabel(
                        summary.totalBounds[2],
                        "lng",
                      )}，纬度 ${formatCoordinateLabel(
                        summary.totalBounds[1],
                        "lat",
                      )} - ${formatCoordinateLabel(summary.totalBounds[3], "lat")}`
                  : english
                    ? "No parseable spatial extent"
                    : "暂无可解析空间范围"}
              </Typography.Text>
              <div className="admin-spatial-bounds-meta">
                <Tag
                  color={
                    summary.missingSpatialResourceCount > 0
                      ? "warning"
                      : "success"
                  }
                >
                  {english
                    ? `${summary.missingSpatialResourceCount} missing`
                    : `缺失 ${summary.missingSpatialResourceCount} 项`}
                </Tag>
                <Tag>
                  {hasBounds(summary.totalBounds)
                    ? english
                      ? `Estimated ${formatArea(boundsAreaKm2(summary.totalBounds))}`
                      : `估算 ${formatArea(boundsAreaKm2(summary.totalBounds))}`
                    : english
                      ? "No area"
                      : "暂无面积"}
                </Tag>
              </div>
            </div>
            <div className="admin-spatial-legend">
              {Object.entries(dataTypeLabels).map(([type, label]) => (
                <span key={type}>
                  <i style={{ background: dataTypeColor(type) }} />
                  {english
                    ? ((
                        {
                          vector: "Vector",
                          raster: "Raster",
                          gene: "Gene",
                          table: "Table",
                          document: "Document",
                          image: "Image",
                        } as Record<string, string>
                      )[type] ?? label)
                    : label}
                </span>
              ))}
            </div>
            {summary.resourceExtentsTruncated && (
              <Tag color="warning">
                {english
                  ? "Showing the 80 resources with the largest coverage first"
                  : "已优先展示覆盖面积最大的 80 项"}
              </Tag>
            )}
            <CoverageRankingPanel summary={summary} />
          </div>
        </div>
      </Card>
    </BorderBeam>
  );
}

function DataOverviewMap({
  summary,
  viewMode,
  heatmapMetric,
  showRangeOverlays,
}: {
  summary: DataOverviewSpatialSummary;
  viewMode: SpatialViewMode;
  heatmapMetric: HeatmapMetric;
  showRangeOverlays: boolean;
}) {
  const english = useEnglishLanguage();
  const mapId = useId().replace(/:/g, "");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapboxMap | null>(null);
  const dashTimerRef = useRef<number | null>(null);
  const { bootstrap } = useAppContext();
  const mapConfig = bootstrap.map;
  const totalBounds = summary.totalBounds;
  const mapboxToken = mapConfig.mapboxAccessToken;
  const shouldUseMapboxStyle = shouldUseMapboxBasemap(mapConfig);
  const layerIds = useMemo(() => overviewMapLayerIds(mapId), [mapId]);
  const totalBoundsKey = hasBounds(totalBounds) ? totalBounds.join(",") : "";

  useEffect(() => {
    const container = containerRef.current;
    if (!container || mapRef.current || !hasBounds(totalBounds)) {
      return;
    }
    disableOverviewMapboxEventRequests();
    const mapOptions: MapboxOptions = {
      attributionControl: false,
      bearing: 0,
      center: boundsCenter(totalBounds),
      container,
      language: mapLabelLanguage(),
      localIdeographFontFamily: '"Microsoft YaHei", "PingFang SC", sans-serif',
      minZoom: 1.1,
      performanceMetricsCollection: false,
      pitch: 0,
      projection: "mercator",
      renderWorldCopies: false,
      style: createBasemapStyle(mapConfig),
      zoom: 2.5,
    };
    if (mapboxToken) {
      mapOptions.accessToken = mapboxToken;
    }
    const map = new mapboxgl.Map(mapOptions);
    mapRef.current = map;
    map.addControl(
      new mapboxgl.NavigationControl({
        showCompass: true,
        showZoom: true,
        visualizePitch: false,
      }),
      "top-left",
    );
    map.addControl(
      new mapboxgl.ScaleControl({ unit: "metric" }),
      "bottom-left",
    );
    const resizeObserver = new ResizeObserver(() => map.resize());
    resizeObserver.observe(container);

    const syncBasemap = () => {
      applyBasemapExpressionSafety(map);
      if (shouldUseMapboxStyle) {
        applySatelliteBasemapColorCorrection(map);
        applyChineseBasemapLanguage(map);
      }
    };
    const fitToOverviewBounds = () => {
      map.fitBounds(lngLatBoundsFor(totalBounds), fitBoundsOptions(54));
    };
    const handleLoad = () => {
      syncBasemap();
      map.resize();
      fitToOverviewBounds();
    };
    const handleStyleLoad = () => {
      syncBasemap();
    };
    const handleMapError = (event: { error?: unknown }) => {
      if (!isOsmRasterTileError(event)) {
        console.warn("Overview map error", event.error);
      }
    };
    map.on("load", handleLoad);
    map.on("style.load", handleStyleLoad);
    map.on("error", handleMapError);
    dashTimerRef.current = window.setInterval(() => {
      animateOverviewBoundsLines(map, layerIds);
    }, 760);

    return () => {
      map.off("load", handleLoad);
      map.off("style.load", handleStyleLoad);
      map.off("error", handleMapError);
      if (dashTimerRef.current !== null) {
        window.clearInterval(dashTimerRef.current);
        dashTimerRef.current = null;
      }
      resizeObserver.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, [layerIds, mapConfig, mapboxToken, shouldUseMapboxStyle, totalBoundsKey]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !hasBounds(totalBounds)) return;
    const sync = () =>
      syncOverviewMapLayers(
        map,
        layerIds,
        summary,
        viewMode,
        heatmapMetric,
        showRangeOverlays,
      );
    if (map.isStyleLoaded()) {
      sync();
      return;
    }
    map.once("load", sync);
    return () => {
      map.off("load", sync);
    };
  }, [
    heatmapMetric,
    layerIds,
    showRangeOverlays,
    summary,
    totalBounds,
    viewMode,
  ]);

  if (!hasBounds(totalBounds)) {
    return (
      <div className="admin-spatial-map admin-spatial-map-empty">
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={english ? "No spatial extent" : "暂无空间范围"}
        />
      </div>
    );
  }

  return (
    <div className="admin-spatial-map">
      <div ref={containerRef} className="admin-spatial-map-canvas" />
      {showRangeOverlays && (
        <div className="admin-spatial-map-caption">
          <strong>{english ? "Platform-wide extent" : "平台总体范围"}</strong>
          <span>{formatCompactBounds(totalBounds)}</span>
        </div>
      )}
      <div className="admin-spatial-map-legend">
        {showRangeOverlays && (
          <span className="total">
            {english ? "Platform extent" : "平台总体范围"}
          </span>
        )}
        {showRangeOverlays && (
          <span className="dataset">
            {english ? "Dataset extent" : "数据集范围"}
          </span>
        )}
        {viewMode === "heatmap" && (
          <span className="heat">
            {english ? "Heatmap coverage" : "热力覆盖"}
          </span>
        )}
      </div>
    </div>
  );
}

function DataTypeDistributionCard({ scope }: { scope: DataOverviewScope }) {
  const english = useEnglishLanguage();
  const typeTotal = scope.typeBreakdown.reduce(
    (sum, item) => sum + item.count,
    0,
  );
  const gradient = buildDonutGradient(scope.typeBreakdown, typeTotal);

  return (
    <div className="admin-overview-grid-format">
      <BorderBeam color={oceanBorderBeam}>
        <Card className="admin-dashboard-card admin-overview-panel-card">
          <PanelTitle
            icon={<PieChartOutlined />}
            title={english ? "Data format types" : "数据格式类型"}
          />
          <Typography.Text type="secondary" className="admin-panel-subtitle">
            {english
              ? "Resource counts, sizes, and items by physical storage format"
              : "按资源的物理存储格式统计数量、体量与数据条目"}
          </Typography.Text>
          {scope.typeBreakdown.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={english ? "No data" : "暂无数据"}
            />
          ) : (
            <div className="admin-type-distribution">
              <div
                className="admin-type-donut"
                style={{ background: gradient }}
              >
                <div>
                  <strong>{scope.totalResources}</strong>
                  <span>{english ? "resources" : "项资源"}</span>
                </div>
              </div>
              <div className="admin-type-breakdown-list">
                {scope.typeBreakdown.map((item) => {
                  const percent =
                    typeTotal > 0 ? (item.count / typeTotal) * 100 : 0;
                  const color = dataTypeColor(item.dataType);
                  return (
                    <div
                      key={item.dataType}
                      className="admin-type-breakdown-row"
                    >
                      <div className="admin-type-breakdown-heading">
                        <span
                          className="admin-type-swatch"
                          style={{ background: color }}
                        />
                        <Typography.Text strong>
                          {english
                            ? dashboardDataTypeName(item.dataType)
                            : (dataTypeLabels[item.dataType] ?? item.dataType)}
                        </Typography.Text>
                        <Tag>{percent.toFixed(0)}%</Tag>
                      </div>
                      <div className="admin-type-breakdown-bar">
                        <span
                          style={{
                            width:
                              item.count > 0
                                ? `${Math.max(percent, 4)}%`
                                : "0%",
                            background: color,
                          }}
                        />
                      </div>
                      <div className="admin-type-breakdown-meta">
                        <span>
                          {english
                            ? `${item.count} resources`
                            : `${item.count} 项`}
                        </span>
                        <span>{formatBytes(item.sizeBytes)}</span>
                        <span>
                          {english
                            ? `${formatNumber(item.itemCount)} items`
                            : `${formatNumber(item.itemCount)} 条`}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </Card>
      </BorderBeam>
    </div>
  );
}

function BusinessCategoryDistributionCard({
  scope,
}: {
  scope: DataOverviewScope;
}) {
  const english = useEnglishLanguage();
  const categoryTotal = scope.categoryBreakdown.reduce(
    (sum, category) => sum + category.count,
    0,
  );
  const gradient = buildCategoryDonutGradient(
    scope.categoryBreakdown,
    categoryTotal,
  );

  return (
    <div className="admin-overview-grid-category">
      <BorderBeam color={oceanBorderBeam}>
        <Card className="admin-dashboard-card admin-overview-panel-card">
          <div className="admin-category-panel-heading">
            <div>
              <PanelTitle
                icon={<ClusterOutlined />}
                title={
                  english ? "Business-category distribution" : "业务分类分布"
                }
              />
              <Typography.Text
                type="secondary"
                className="admin-panel-subtitle"
              >
                {english
                  ? "Four domains and fifteen categories in the authoritative platform taxonomy"
                  : "按平台权威分类体系统计四个大类及其十五个小类"}
              </Typography.Text>
            </div>
            {scope.unclassifiedCount > 0 && (
              <Tag color="warning">
                {english
                  ? `${scope.unclassifiedCount} pending classification`
                  : `待分类 ${scope.unclassifiedCount} 项`}
              </Tag>
            )}
          </div>
          <div className="admin-category-summary">
            <div
              className="admin-type-donut admin-category-donut"
              style={{ background: gradient }}
            >
              <div>
                <strong>{categoryTotal}</strong>
                <span>{english ? "classified resources" : "已分类资源"}</span>
              </div>
            </div>
            <div className="admin-category-major-list">
              {scope.categoryBreakdown.map((category) => {
                const percent =
                  categoryTotal > 0
                    ? (category.count / categoryTotal) * 100
                    : 0;
                const color = categoryColor(category.categoryCode);
                return (
                  <div
                    key={category.categoryCode}
                    className="admin-category-major-row"
                  >
                    <span
                      className="admin-type-swatch"
                      style={{ background: color }}
                    />
                    <Typography.Text
                      strong
                      title={dashboardCategoryName(
                        category.categoryCode,
                        category.categoryName,
                        english,
                      )}
                    >
                      {dashboardCategoryName(
                        category.categoryCode,
                        category.categoryName,
                        english,
                      )}
                    </Typography.Text>
                    <strong>{category.count}</strong>
                    <span>{percent.toFixed(0)}%</span>
                  </div>
                );
              })}
            </div>
          </div>
          <div className="admin-category-group-grid">
            {scope.categoryBreakdown.map((category) => {
              const color = categoryColor(category.categoryCode);
              const maxChildCount = Math.max(
                ...category.children.map((child) => child.count),
                0,
              );
              return (
                <section
                  key={category.categoryCode}
                  className="admin-category-group"
                  style={{ "--category-color": color } as CSSProperties}
                >
                  <div className="admin-category-group-heading">
                    <span>
                      <i style={{ background: color }} />
                      <Typography.Text strong>
                        {dashboardCategoryName(
                          category.categoryCode,
                          category.categoryName,
                          english,
                        )}
                      </Typography.Text>
                    </span>
                    <Tag>
                      {english
                        ? `${category.count} resources`
                        : `${category.count} 项`}
                    </Tag>
                  </div>
                  <div className="admin-category-leaf-list">
                    {category.children.map((child) => {
                      const width =
                        maxChildCount > 0
                          ? (child.count / maxChildCount) * 100
                          : 0;
                      return (
                        <div
                          key={child.categoryCode}
                          className="admin-category-leaf-row"
                        >
                          <span className="admin-category-leaf-name">
                            {dashboardCategoryName(
                              child.categoryCode,
                              child.categoryName,
                              english,
                            )}
                          </span>
                          <span className="admin-category-leaf-track">
                            <i style={{ width: `${width}%` }} />
                          </span>
                          <strong>{child.count}</strong>
                        </div>
                      );
                    })}
                  </div>
                </section>
              );
            })}
          </div>
        </Card>
      </BorderBeam>
    </div>
  );
}

function CoverageRankingPanel({
  summary,
}: {
  summary: DataOverviewSpatialSummary;
}) {
  const english = useEnglishLanguage();
  const maxArea = Math.max(
    ...summary.coverageRanking.map((item) => item.coverageAreaKm2),
    0,
  );

  return (
    <section className="admin-spatial-ranking-panel">
      <div className="admin-spatial-ranking-heading">
        <PanelTitle
          icon={<BarChartOutlined />}
          title={english ? "Spatial coverage ranking" : "空间覆盖排行"}
        />
        <Typography.Text type="secondary">
          TOP {Math.min(summary.coverageRanking.length, 8)}
        </Typography.Text>
      </div>
      {summary.coverageRanking.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={english ? "No spatial extent" : "暂无空间范围"}
        />
      ) : (
        <div className="admin-coverage-rank-list">
          {summary.coverageRanking.slice(0, 8).map((item, index) => {
            const ratio = maxArea > 0 ? item.coverageAreaKm2 / maxArea : 0;
            const visualRatio = Math.sqrt(ratio);
            const color = dataTypeColor(item.dataType);
            return (
              <div key={item.resourceId} className="admin-coverage-rank-row">
                <span className="admin-coverage-rank-index">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div className="admin-coverage-rank-main">
                  <div className="admin-coverage-rank-title">
                    <Typography.Text strong title={item.name}>
                      {item.name}
                    </Typography.Text>
                  </div>
                  <div className="admin-coverage-rank-meta">
                    <span>
                      {english
                        ? `${formatNumber(item.itemCount)} items`
                        : `${formatNumber(item.itemCount)} 条`}
                    </span>
                    <span>{formatBytes(item.sizeBytes)}</span>
                    <span>{item.uploaderName}</span>
                  </div>
                </div>
                <div className="admin-coverage-rank-side">
                  <Tag style={{ color, borderColor: color }}>
                    {english
                      ? dashboardDataTypeName(item.dataType)
                      : (dataTypeLabels[item.dataType] ?? item.dataType)}
                  </Tag>
                  <Typography.Text className="admin-coverage-rank-value">
                    {formatArea(item.coverageAreaKm2)}
                  </Typography.Text>
                </div>
                <div className="admin-coverage-rank-track">
                  <span
                    style={{
                      width: `${Math.max(visualRatio * 100, 6)}%`,
                      background: color,
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function PanelTitle({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="admin-overview-panel-title">
      <span className="admin-dashboard-metric-icon">{icon}</span>
      <Typography.Title level={5}>{title}</Typography.Title>
    </div>
  );
}

function OverviewMiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="admin-spatial-mini-stat">
      <Typography.Text type="secondary">{label}</Typography.Text>
      <Typography.Text strong>{value}</Typography.Text>
    </div>
  );
}

function ServerCard({
  title,
  model,
  usage,
  lines,
  icon,
}: {
  title: string;
  model: string;
  usage: number;
  lines: string[];
  icon: ReactNode;
}) {
  return (
    <Col xs={24} lg={8}>
      <BorderBeam color={oceanBorderBeam}>
        <Card className="admin-dashboard-card" variant="borderless">
          <div className="admin-server-card-heading">
            <Space>
              <span className="admin-dashboard-metric-icon">{icon}</span>
              <Typography.Text strong>{title}</Typography.Text>
            </Space>
            <Tag
              color={usage >= 90 ? "error" : usage >= 75 ? "warning" : "green"}
            >
              {usage}%
            </Tag>
          </div>
          <Typography.Paragraph className="admin-server-model">
            {model || "未识别型号"}
          </Typography.Paragraph>
          <Progress
            percent={usage}
            status={usage >= 90 ? "exception" : "normal"}
            strokeColor={usage >= 75 ? "#d48806" : "#2f7d62"}
          />
          <div className="admin-server-lines">
            {lines.map((line) => (
              <Typography.Text type="secondary" key={line}>
                {line}
              </Typography.Text>
            ))}
          </div>
        </Card>
      </BorderBeam>
    </Col>
  );
}

function dataTypeColor(dataType: string) {
  return dataTypeColors[dataType] ?? "#6f8c87";
}

function categoryColor(categoryCode: string) {
  return categoryColors[categoryCode] ?? "#6f8c87";
}

function overviewMapLayerIds(prefix: string) {
  return {
    centers: `${prefix}-centers`,
    centersHalo: `${prefix}-centers-halo`,
    centersSource: `${prefix}-centers-source`,
    extentsFill: `${prefix}-extents-fill`,
    extentsHalo: `${prefix}-extents-halo`,
    extentsLine: `${prefix}-extents-line`,
    extentsSource: `${prefix}-extents-source`,
    heatCenter: `${prefix}-heat-center`,
    heatFill: `${prefix}-heat-fill`,
    heatGlow: `${prefix}-heat-glow`,
    heatLabel: `${prefix}-heat-label`,
    heatLine: `${prefix}-heat-line`,
    heatPointsSource: `${prefix}-heat-points-source`,
    heatSource: `${prefix}-heat-source`,
    totalFill: `${prefix}-total-fill`,
    totalGlow: `${prefix}-total-glow`,
    totalLine: `${prefix}-total-line`,
    totalPulse: `${prefix}-total-pulse`,
    totalSource: `${prefix}-total-source`,
  };
}

function syncOverviewMapLayers(
  map: MapboxMap,
  ids: ReturnType<typeof overviewMapLayerIds>,
  summary: DataOverviewSpatialSummary,
  viewMode: SpatialViewMode,
  heatmapMetric: HeatmapMetric,
  showRangeOverlays: boolean,
) {
  if (!map.isStyleLoaded() || !hasBounds(summary.totalBounds)) {
    return;
  }

  const maxHeatmapValue = Math.max(
    ...summary.heatmapCells.map((cell) => cell[heatmapMetric]),
    1,
  );
  const rangesVisible = showRangeOverlays ? 1 : 0;
  const extentFillOpacity =
    rangesVisible * (viewMode === "heatmap" ? 0.04 : 0.2);
  const extentHaloOpacity =
    rangesVisible * (viewMode === "heatmap" ? 0.12 : 0.34);
  const extentLineOpacity =
    rangesVisible * (viewMode === "heatmap" ? 0.34 : 0.96);
  const centerHaloOpacity =
    rangesVisible * (viewMode === "heatmap" ? 0.14 : 0.18);
  const centerOpacity = rangesVisible * (viewMode === "heatmap" ? 0.44 : 0.96);
  const totalFillOpacity =
    rangesVisible * (viewMode === "heatmap" ? 0.04 : 0.07);
  const totalPulseOpacity = rangesVisible * 0.3;
  const totalGlowOpacity = rangesVisible * 0.82;
  const totalLineOpacity = rangesVisible * 0.98;
  const heatCellColor: ExpressionSpecification = [
    "interpolate",
    ["linear"],
    ["get", "normalized"],
    0,
    "rgba(63, 166, 135, 0.16)",
    0.32,
    "rgba(75, 185, 148, 0.34)",
    0.58,
    "rgba(244, 203, 104, 0.52)",
    0.82,
    "rgba(231, 133, 76, 0.66)",
    1,
    "rgba(204, 74, 86, 0.78)",
  ];
  const heatCellOpacity: ExpressionSpecification = [
    "interpolate",
    ["linear"],
    ["get", "normalized"],
    0,
    0.16,
    1,
    0.72,
  ];
  const heatCellLineWidth: ExpressionSpecification = [
    "interpolate",
    ["linear"],
    ["get", "normalized"],
    0,
    1.4,
    1,
    3.6,
  ];
  upsertOverviewSource(map, ids.totalSource, {
    features: [
      {
        geometry: boundsPolygon(summary.totalBounds),
        properties: {
          label: "平台总体范围",
          value: boundsAreaKm2(summary.totalBounds),
        },
        type: "Feature",
      },
    ],
    type: "FeatureCollection",
  });
  upsertOverviewSource(map, ids.extentsSource, {
    features: summary.resourceExtents.map((item) => ({
      geometry: boundsPolygon(item.bounds),
      properties: {
        area: item.coverageAreaKm2,
        color: dataTypeColor(item.dataType),
        dataType: dataTypeLabels[item.dataType] ?? item.dataType,
        itemCount: item.itemCount,
        label: item.name,
      },
      type: "Feature",
    })),
    type: "FeatureCollection",
  });
  upsertOverviewSource(map, ids.centersSource, {
    features: summary.resourceExtents.map((item) => ({
      geometry: {
        coordinates: item.center,
        type: "Point",
      },
      properties: {
        area: item.coverageAreaKm2,
        color: dataTypeColor(item.dataType),
        dataType: dataTypeLabels[item.dataType] ?? item.dataType,
        itemCount: item.itemCount,
        label: item.name,
      },
      type: "Feature",
    })),
    type: "FeatureCollection",
  });
  upsertOverviewSource(map, ids.heatSource, {
    features: summary.heatmapCells.map((cell) => ({
      geometry: boundsPolygon(cell.bounds),
      properties: {
        itemCount: cell.itemCount,
        label: `资源 ${cell.resourceCount} 项，条目 ${cell.itemCount} 条`,
        normalized: cell[heatmapMetric] / maxHeatmapValue,
        resourceCount: cell.resourceCount,
        text: formatHeatmapCellLabel(cell[heatmapMetric], heatmapMetric),
        value: cell[heatmapMetric],
      },
      type: "Feature",
    })),
    type: "FeatureCollection",
  });
  upsertOverviewSource(map, ids.heatPointsSource, {
    features: summary.heatmapCells.map((cell) => ({
      geometry: {
        coordinates: boundsCenter(cell.bounds),
        type: "Point",
      },
      properties: {
        itemCount: cell.itemCount,
        label: `资源 ${cell.resourceCount} 项，条目 ${cell.itemCount} 条`,
        normalized: cell[heatmapMetric] / maxHeatmapValue,
        resourceCount: cell.resourceCount,
        text: formatHeatmapCellLabel(cell[heatmapMetric], heatmapMetric),
        value: cell[heatmapMetric],
      },
      type: "Feature",
    })),
    type: "FeatureCollection",
  });
  ensureOverviewLayer(map, {
    id: ids.heatFill,
    paint: {
      "fill-color": heatCellColor,
      "fill-opacity": viewMode === "heatmap" ? heatCellOpacity : 0,
    },
    source: ids.heatSource,
    type: "fill",
  });
  ensureOverviewLayer(map, {
    id: ids.heatGlow,
    paint: {
      "line-blur": 2.4,
      "line-color": heatCellColor,
      "line-opacity": viewMode === "heatmap" ? 0.42 : 0,
      "line-width": heatCellLineWidth,
    },
    source: ids.heatSource,
    type: "line",
  });
  ensureOverviewLayer(map, {
    id: ids.heatLine,
    paint: {
      "line-color": "rgba(255,255,255,0.78)",
      "line-opacity": viewMode === "heatmap" ? 0.58 : 0,
      "line-width": 1.1,
    },
    source: ids.heatSource,
    type: "line",
  });
  ensureOverviewLayer(map, {
    id: ids.heatCenter,
    paint: {
      "circle-color": heatCellColor,
      "circle-opacity": viewMode === "heatmap" ? 0.9 : 0,
      "circle-radius": [
        "interpolate",
        ["linear"],
        ["get", "normalized"],
        0,
        3.5,
        1,
        10,
      ],
      "circle-stroke-color": "rgba(255,255,255,0.86)",
      "circle-stroke-opacity": viewMode === "heatmap" ? 0.9 : 0,
      "circle-stroke-width": 1,
    },
    source: ids.heatPointsSource,
    type: "circle",
  });
  ensureOverviewLayer(map, {
    id: ids.heatLabel,
    layout: {
      "text-allow-overlap": false,
      "text-field": ["get", "text"],
      "text-font": ["Open Sans Semibold", "Arial Unicode MS Bold"],
      "text-ignore-placement": false,
      "text-size": ["interpolate", ["linear"], ["zoom"], 2, 10, 6, 13],
    },
    paint: {
      "text-color": "#5f3d0d",
      "text-halo-color": "rgba(255,255,255,0.86)",
      "text-halo-width": 1.2,
      "text-opacity": viewMode === "heatmap" ? 0.86 : 0,
    },
    source: ids.heatPointsSource,
    type: "symbol",
  });
  ensureOverviewLayer(map, {
    id: ids.extentsFill,
    paint: {
      "fill-color": ["get", "color"],
      "fill-opacity": extentFillOpacity,
    },
    source: ids.extentsSource,
    type: "fill",
  });
  ensureOverviewLayer(map, {
    id: ids.extentsHalo,
    paint: {
      "line-blur": 1.6,
      "line-color": ["get", "color"],
      "line-opacity": extentHaloOpacity,
      "line-width": ["interpolate", ["linear"], ["zoom"], 2, 4.4, 7, 7.2],
    },
    source: ids.extentsSource,
    type: "line",
  });
  ensureOverviewLayer(map, {
    id: ids.extentsLine,
    paint: {
      "line-blur": 0.25,
      "line-color": ["get", "color"],
      "line-dasharray": [1.4, 0.9],
      "line-opacity": extentLineOpacity,
      "line-width": ["interpolate", ["linear"], ["zoom"], 2, 1.8, 7, 3.2],
    },
    source: ids.extentsSource,
    type: "line",
  });
  ensureOverviewLayer(map, {
    id: ids.totalFill,
    paint: {
      "fill-color": "#f2b84b",
      "fill-opacity": totalFillOpacity,
    },
    source: ids.totalSource,
    type: "fill",
  });
  ensureOverviewLayer(map, {
    id: ids.totalPulse,
    paint: {
      "line-blur": 8,
      "line-color": "#fff4bf",
      "line-opacity": totalPulseOpacity,
      "line-width": ["interpolate", ["linear"], ["zoom"], 2, 10, 7, 18],
    },
    source: ids.totalSource,
    type: "line",
  });
  ensureOverviewLayer(map, {
    id: ids.totalGlow,
    paint: {
      "line-blur": 3.4,
      "line-color": "#ffe39a",
      "line-opacity": totalGlowOpacity,
      "line-width": ["interpolate", ["linear"], ["zoom"], 2, 7.8, 7, 13.5],
    },
    source: ids.totalSource,
    type: "line",
  });
  ensureOverviewLayer(map, {
    id: ids.totalLine,
    paint: {
      "line-color": "#f2b84b",
      "line-dasharray": [3, 0.85, 0.4, 0.85],
      "line-opacity": totalLineOpacity,
      "line-width": ["interpolate", ["linear"], ["zoom"], 2, 3.2, 7, 5.4],
    },
    source: ids.totalSource,
    type: "line",
  });
  ensureOverviewLayer(map, {
    id: ids.centersHalo,
    paint: {
      "circle-color": ["get", "color"],
      "circle-opacity": centerHaloOpacity,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 7, 7, 15],
    },
    source: ids.centersSource,
    type: "circle",
  });
  ensureOverviewLayer(map, {
    id: ids.centers,
    paint: {
      "circle-color": ["get", "color"],
      "circle-opacity": centerOpacity,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 3.8, 7, 7],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1.2,
    },
    source: ids.centersSource,
    type: "circle",
  });

  map.setPaintProperty(ids.heatFill, "fill-color", heatCellColor);
  map.setPaintProperty(
    ids.heatFill,
    "fill-opacity",
    viewMode === "heatmap" ? heatCellOpacity : 0,
  );
  map.setPaintProperty(ids.heatGlow, "line-color", heatCellColor);
  map.setPaintProperty(
    ids.heatGlow,
    "line-opacity",
    viewMode === "heatmap" ? 0.42 : 0,
  );
  map.setPaintProperty(
    ids.heatLine,
    "line-opacity",
    viewMode === "heatmap" ? 0.58 : 0,
  );
  map.setPaintProperty(ids.heatCenter, "circle-color", heatCellColor);
  map.setPaintProperty(
    ids.heatCenter,
    "circle-opacity",
    viewMode === "heatmap" ? 0.9 : 0,
  );
  map.setPaintProperty(
    ids.heatCenter,
    "circle-stroke-opacity",
    viewMode === "heatmap" ? 0.9 : 0,
  );
  map.setPaintProperty(
    ids.heatLabel,
    "text-opacity",
    viewMode === "heatmap" ? 0.86 : 0,
  );
  map.setPaintProperty(ids.extentsFill, "fill-opacity", extentFillOpacity);
  map.setPaintProperty(ids.extentsHalo, "line-opacity", extentHaloOpacity);
  map.setPaintProperty(ids.extentsLine, "line-opacity", extentLineOpacity);
  map.setPaintProperty(ids.centersHalo, "circle-opacity", centerHaloOpacity);
  map.setPaintProperty(ids.centers, "circle-opacity", centerOpacity);
  map.setPaintProperty(ids.totalFill, "fill-opacity", totalFillOpacity);
  map.setPaintProperty(ids.totalPulse, "line-opacity", totalPulseOpacity);
  map.setPaintProperty(ids.totalGlow, "line-opacity", totalGlowOpacity);
  map.setPaintProperty(ids.totalLine, "line-opacity", totalLineOpacity);
}

function upsertOverviewSource(
  map: MapboxMap,
  sourceId: string,
  data: OverviewFeatureCollection,
) {
  const source = map.getSource(sourceId) as GeoJSONSource | undefined;
  if (source) {
    source.setData(data as Parameters<GeoJSONSource["setData"]>[0]);
    return;
  }
  map.addSource(sourceId, {
    data: data as Parameters<GeoJSONSource["setData"]>[0],
    type: "geojson",
  });
}

function ensureOverviewLayer(map: MapboxMap, layer: AnyLayer) {
  if (!map.getLayer(layer.id)) {
    map.addLayer(layer);
  }
}

function animateOverviewBoundsLines(
  map: MapboxMap,
  ids: ReturnType<typeof overviewMapLayerIds>,
) {
  if (!map.getLayer(ids.totalLine)) return;
  const phase = Math.floor(Date.now() / 620) % 6;
  const totalDashPatterns = [
    [3, 0.85, 0.4, 0.85],
    [2.2, 0.85, 1.2, 0.85],
    [1.35, 0.85, 2.05, 0.85],
    [0.55, 0.85, 2.85, 0.85],
    [1.35, 0.85, 2.05, 0.85],
    [2.2, 0.85, 1.2, 0.85],
  ];
  const datasetDashPatterns = [
    [1.4, 0.9],
    [0.8, 0.9, 1.6, 0.9],
    [1.1, 0.9],
    [0.55, 0.9, 1.9, 0.9],
    [0.8, 0.9, 1.6, 0.9],
    [1.1, 0.9],
  ];
  const totalLineOpacity = numberPaintProperty(
    map,
    ids.totalLine,
    "line-opacity",
  );
  const totalVisible = totalLineOpacity > 0.01;
  const extentsLineOpacity = map.getLayer(ids.extentsLine)
    ? numberPaintProperty(map, ids.extentsLine, "line-opacity")
    : 0;
  const extentsVisible = extentsLineOpacity > 0.01;

  map.setPaintProperty(
    ids.totalLine,
    "line-dasharray",
    totalDashPatterns[phase],
  );
  if (map.getLayer(ids.totalFill)) {
    const totalFillOpacity = totalVisible
      ? [0.04, 0.055, 0.072, 0.088, 0.072, 0.055][phase]
      : 0;
    map.setPaintProperty(ids.totalFill, "fill-opacity", totalFillOpacity);
  }
  if (map.getLayer(ids.totalPulse)) {
    const pulseOpacity = totalVisible
      ? [0.16, 0.26, 0.38, 0.46, 0.34, 0.22][phase]
      : 0;
    const pulseWidth = [9.2, 10.8, 12.8, 14.2, 12.4, 10.2][phase] ?? 10.8;
    map.setPaintProperty(ids.totalPulse, "line-opacity", pulseOpacity);
    map.setPaintProperty(ids.totalPulse, "line-blur", 7.2 + phase * 0.22);
    map.setPaintProperty(ids.totalPulse, "line-width", [
      "interpolate",
      ["linear"],
      ["zoom"],
      2,
      pulseWidth,
      7,
      pulseWidth + 7.2,
    ]);
  }
  if (map.getLayer(ids.totalGlow)) {
    const totalGlowOpacity = totalVisible
      ? [0.68, 0.82, 0.96, 0.9, 0.78, 0.72][phase]
      : 0;
    const totalGlowBlur = [3.2, 3.8, 4.8, 5.4, 4.4, 3.6][phase];
    const totalGlowColor = [
      "#ffe39a",
      "#fff0b8",
      "#ffffff",
      "#fff1c5",
      "#ffd35a",
      "#ffe39a",
    ][phase];
    map.setPaintProperty(ids.totalGlow, "line-color", totalGlowColor);
    map.setPaintProperty(ids.totalGlow, "line-opacity", totalGlowOpacity);
    map.setPaintProperty(ids.totalGlow, "line-blur", totalGlowBlur);
  }
  if (map.getLayer(ids.extentsHalo)) {
    const extentsHaloOpacity = extentsVisible
      ? extentsLineOpacity > 0.5
        ? [0.28, 0.34, 0.42, 0.38, 0.32, 0.3][phase]
        : [0.08, 0.11, 0.14, 0.12, 0.1, 0.09][phase]
      : 0;
    map.setPaintProperty(ids.extentsHalo, "line-opacity", extentsHaloOpacity);
  }
  if (map.getLayer(ids.extentsLine)) {
    map.setPaintProperty(
      ids.extentsLine,
      "line-dasharray",
      datasetDashPatterns[phase],
    );
  }
}

function numberPaintProperty(
  map: MapboxMap,
  layerId: string,
  property: Parameters<MapboxMap["getPaintProperty"]>[1],
) {
  const value = map.getPaintProperty(layerId, property);
  return typeof value === "number" ? value : 0;
}

function displayInitial(value?: string) {
  const normalized = (value ?? "").trim();
  const initial = Array.from(normalized)[0];
  return initial ? initial.toUpperCase() : "?";
}

function hasBounds(
  bounds: number[],
): bounds is [number, number, number, number] {
  return bounds.length === 4 && bounds.every((value) => Number.isFinite(value));
}

function buildDonutGradient(
  items: DataOverviewScope["typeBreakdown"],
  total: number,
) {
  if (items.length === 0 || total <= 0) {
    return "conic-gradient(#dfe7e1 0deg 360deg)";
  }
  let cursor = 0;
  const segments = items.map((item) => {
    const start = cursor;
    const span = (item.count / total) * 360;
    const end = start + span;
    cursor = end;
    const color = dataTypeColor(item.dataType);
    return `${color} ${start.toFixed(2)}deg ${end.toFixed(2)}deg`;
  });
  return `conic-gradient(${segments.join(", ")})`;
}

function buildCategoryDonutGradient(
  items: DataOverviewScope["categoryBreakdown"],
  total: number,
) {
  if (items.length === 0 || total <= 0) {
    return "conic-gradient(#dfe7e1 0deg 360deg)";
  }
  let cursor = 0;
  const segments = items.map((item) => {
    const start = cursor;
    const span = (item.count / total) * 360;
    const end = start + span;
    cursor = end;
    return `${categoryColor(item.categoryCode)} ${start.toFixed(2)}deg ${end.toFixed(2)}deg`;
  });
  return `conic-gradient(${segments.join(", ")})`;
}

function boundsPolygon(
  bounds: [number, number, number, number],
): OverviewPolygonFeature["geometry"] {
  const [minLng, minLat, maxLng, maxLat] = normalizeMapBounds(bounds);
  return {
    coordinates: [
      [
        [minLng, minLat],
        [maxLng, minLat],
        [maxLng, maxLat],
        [minLng, maxLat],
        [minLng, minLat],
      ],
    ],
    type: "Polygon",
  };
}

function lngLatBoundsFor(bounds: [number, number, number, number]) {
  const [minLng, minLat, maxLng, maxLat] = normalizeMapBounds(bounds);
  return new LngLatBounds([minLng, minLat], [maxLng, maxLat]);
}

function boundsCenter(
  bounds: [number, number, number, number],
): [number, number] {
  const [minLng, minLat, maxLng, maxLat] = normalizeMapBounds(bounds);
  return [(minLng + maxLng) / 2, (minLat + maxLat) / 2];
}

function normalizeMapBounds(
  bounds: [number, number, number, number],
): [number, number, number, number] {
  const [minLng, minLat, maxLng, maxLat] = bounds;
  return [
    Math.max(-180, Math.min(180, minLng)),
    clampMercatorLatitude(minLat),
    Math.max(-180, Math.min(180, maxLng)),
    clampMercatorLatitude(maxLat),
  ];
}

function clampMercatorLatitude(value: number) {
  return Math.max(-85.051129, Math.min(85.051129, value));
}

function disableOverviewMapboxEventRequests() {
  const descriptor = Object.getOwnPropertyDescriptor(
    mapboxgl.config,
    "EVENTS_URL",
  );
  if (descriptor?.value === null) return;
  Object.defineProperty(mapboxgl.config, "EVENTS_URL", {
    configurable: true,
    enumerable: descriptor?.enumerable ?? true,
    value: null,
  });
}

function formatNumber(value: number) {
  return value.toLocaleString("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 0,
  });
}

function formatCoordinateLabel(value: number, axis: "lng" | "lat") {
  const suffix =
    axis === "lng" ? (value < 0 ? "W" : "E") : value < 0 ? "S" : "N";
  return `${formatNumber(Math.abs(value))}°${suffix}`;
}

function formatHeatmapCellLabel(value: number, metric: HeatmapMetric) {
  const suffix = metric === "resourceCount" ? "项" : "条";
  if (value >= 10000) {
    return `${formatNumber(value / 10000)}万${suffix}`;
  }
  return `${formatNumber(value)}${suffix}`;
}

function formatCompactBounds(bounds: number[]) {
  if (!hasBounds(bounds)) {
    return "暂无范围";
  }
  return `经 ${formatCoordinateLabel(bounds[0], "lng")}-${formatCoordinateLabel(
    bounds[2],
    "lng",
  )} / 纬 ${formatCoordinateLabel(bounds[1], "lat")}-${formatCoordinateLabel(
    bounds[3],
    "lat",
  )}`;
}

function boundsAreaKm2(bounds: number[]) {
  if (!hasBounds(bounds)) {
    return 0;
  }
  const [minLng, minLat, maxLng, maxLat] = bounds;
  const centerLat = ((minLat + maxLat) / 2) * (Math.PI / 180);
  const lngKm = 111.32 * Math.max(Math.cos(centerLat), 0.01);
  const latKm = 110.57;
  return Math.abs(maxLng - minLng) * lngKm * Math.abs(maxLat - minLat) * latKm;
}

function formatArea(value: number) {
  if (value >= 10000) {
    return `${formatNumber(value / 10000)} 万 km²`;
  }
  if (value >= 1) {
    return `${formatNumber(value)} km²`;
  }
  return `${value.toFixed(3)} km²`;
}

function formatBytes(value: number, binaryUnits = false) {
  if (!value) return "0 B";
  const units = binaryUnits
    ? ["B", "KiB", "MiB", "GiB", "TiB"]
    : ["B", "KB", "MB", "GB", "TB"];
  let current = value;
  let unitIndex = 0;
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024;
    unitIndex += 1;
  }
  return `${current.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function diskModelText(server: AdminDashboardServer) {
  const disks = server.cards.disks;
  if (!disks) {
    return "";
  }
  const models = disks.devices
    .map((device) =>
      [device.model || device.name, device.size ? `(${device.size})` : ""]
        .filter(Boolean)
        .join(" "),
    )
    .filter(Boolean);
  return models.length > 0 ? models.join("、") : disks.mount;
}

function gpuModelText(server: AdminDashboardServer) {
  const gpu = server.cards.gpu;
  if (!gpu) return "";
  const counts = new Map<string, number>();
  for (const device of gpu.devices) {
    const name = device.name.trim();
    if (name) counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  if (!counts.size) return "GPU";
  return [...counts.entries()]
    .map(([name, count]) => (count > 1 ? `${count} × ${name}` : name))
    .join("\n");
}

function dashboardDataTypeName(dataType: string) {
  return (
    (
      {
        vector: "Vector",
        raster: "Raster",
        gene: "Gene",
        table: "Table",
        document: "Document",
        image: "Image",
      } as Record<string, string>
    )[dataType] ?? dataType
  );
}

function dashboardCategoryName(
  code: string,
  fallback: string,
  english: boolean,
) {
  if (!english) return fallback;
  return (
    (
      {
        base_geo: "Base geographic information",
        base_geo_admin: "Administrative boundaries",
        base_geo_elements: "Base geographic features",
        base_geo_lucc: "LUCC",
        habitat: "Poplar habitat data",
        habitat_water: "Water",
        habitat_soil: "Soil",
        habitat_climate: "Climate",
        habitat_biotic: "Biotic environment",
        distribution: "Poplar spatial distribution",
        distribution_vector: "Distribution vectors",
        distribution_survey_image: "Survey-site images",
        thematic: "Poplar thematic data",
        thematic_gene_germplasm: "Genes and germplasm",
        thematic_individual: "Individuals",
        thematic_population: "Populations",
        thematic_community: "Communities",
        thematic_ecosystem: "Ecosystems",
        thematic_landscape_rs: "Landscape and remote sensing",
      } as Record<string, string>
    )[code] ?? fallback
  );
}
