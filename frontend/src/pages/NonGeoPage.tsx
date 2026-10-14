import {
  AppstoreOutlined,
  BarChartOutlined,
  BranchesOutlined,
  DatabaseOutlined,
  DotChartOutlined,
  FileSearchOutlined,
  LineChartOutlined,
  NumberOutlined,
  RadarChartOutlined,
  ReloadOutlined,
  TableOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Collapse,
  Badge,
  Button,
  Empty,
  Layout,
  Progress,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import type { TableProps } from "antd";
import type { TFunction } from "i18next";
import type { ReactNode } from "react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import WorkspaceHeader from "../components/WorkspaceHeader";
import { platformBrand } from "../config/platformBrand";
import { useAppContext } from "../contexts/AppContext";
import { useProjectContext } from "../projects/ProjectContext";
import i18n, { currentLocale } from "../i18n";
import type {
  NonGeoAnalytics,
  NonGeoFieldProfile,
  NonGeoTableQueryResult,
  NonGeoTableRow,
  ResourceListItem,
} from "../types";
import { resourceCategoryName, resourceFormatLabel } from "../utils/resources";
import { createNonGeoDemo, NON_GEO_DEMO_RESOURCE_ID } from "./nonGeoDemoData";
import NonGeoScatter, { isMeasurement } from "./NonGeoScatter";
import { useComputeText } from "../compute/ui";
import "../styles/nongeo-simple.css";

type CategoricalDistribution =
  NonGeoAnalytics["categoricalDistributions"][number];
type NumericDistribution = NonGeoAnalytics["numericDistributions"][number];
type FieldProfile = NonGeoFieldProfile;
type TableRow = NonGeoTableRow;

const analyticsPalette = [
  "#357487",
  "#7495ad",
  "#a8c1ca",
  "#bc9c6a",
  "#7b8f86",
  "#99a4b5",
  "#c4bfb6",
  "#6c7985",
];
// These stable codes identify the three projects selected for the poplar showcase.
const poplarShowcaseProjectCodes = new Set([
  "default",
  "demo-arid-ecology",
  "05",
]);

export default function NonGeoPage() {
  const { user } = useAppContext();
  const projectContext = useProjectContext();
  const ui = useComputeText();
  const { t, i18n: translationI18n } = useTranslation();
  const canBrowseData = Boolean(user?.permissions?.canBrowseData);
  const currentProject = projectContext?.projects.find(
    (project) => String(project.id) === projectContext.current,
  );
  const showPoplarDemo = Boolean(
    canBrowseData &&
    currentProject?.isActive &&
    poplarShowcaseProjectCodes.has(currentProject.code),
  );
  const demoBundle = useMemo(
    () => (showPoplarDemo ? createNonGeoDemo(currentLocale()) : null),
    [showPoplarDemo, translationI18n.resolvedLanguage],
  );
  const analytics = demoBundle?.analytics ?? null;
  const selectedResource = demoBundle?.resource ?? null;
  const tableData = demoBundle?.table ?? null;
  const [analysisTab, setAnalysisTab] = useState("overview");
  const [selectedMetricField, setSelectedMetricField] = useState<string>();
  const queryingTable = false;
  const queryTable = useCallback(() => setAnalysisTab("table"), []);
  const [categoryField, setCategoryField] = useState<string>();
  const categories = analytics?.categoricalDistributions ?? [];
  const primaryCategory =
    categories.find((item) => item.field === categoryField) ??
    categories[0] ??
    null;
  const secondaryCategory =
    categories.find((item) => item.field !== primaryCategory?.field) ?? null;
  const compositionCategory = primaryCategory;
  const numericDistributions = (analytics?.numericDistributions ?? []).filter(
    (item) => {
      const profile = analytics?.fields.find(
        (field) => field.name === item.field,
      );
      return profile ? isMeasurement(profile) : true;
    },
  );
  const primaryNumeric =
    numericDistributions.find((item) => item.field === selectedMetricField) ??
    numericDistributions[0] ??
    null;
  const tableColumns = useMemo<TableProps<TableRow>["columns"]>(() => {
    const fields = tableData?.fields.slice(0, 8) ?? [];
    return fields.map((field) => ({
      title: (
        <span className="nongeo-table-heading">
          <span>{field.description || field.name}</span>
        </span>
      ),
      dataIndex: field.name,
      key: field.name,
      ellipsis: true,
      render: (value: TableRow[string]) => valueLabel(value),
    }));
  }, [tableData]);

  const tabs = useMemo(
    () => [
      {
        key: "overview",
        label: (
          <span>
            <BarChartOutlined /> {t("nonGeo.overviewTab")}
          </span>
        ),
        children: (
          <OverviewContent
            analytics={analytics}
            primaryCategory={primaryCategory}
            secondaryCategory={secondaryCategory}
            primaryNumeric={primaryNumeric}
            compositionCategory={compositionCategory}
            categories={categories}
            onCategory={setCategoryField}
            metrics={numericDistributions}
            onMetric={setSelectedMetricField}
          />
        ),
      },
      {
        key: "species",
        label: (
          <span>
            <BranchesOutlined /> {t("nonGeo.compositionTab")}
          </span>
        ),
        children: (
          <CompositionContent
            analytics={analytics}
            selected={primaryCategory}
          />
        ),
      },
      {
        key: "traits",
        label: (
          <span>
            <RadarChartOutlined /> {t("nonGeo.traitsTab")}
          </span>
        ),
        children: <TraitsContent analytics={analytics} tableData={tableData} />,
      },
      {
        key: "table",
        label: (
          <span>
            <TableOutlined /> {t("nonGeo.detailsTab")}
          </span>
        ),
        children: (
          <TableContent
            data={tableData}
            columns={tableColumns}
            querying={queryingTable}
            onQuery={queryTable}
          />
        ),
      },
    ],
    [
      analytics,
      compositionCategory,
      primaryCategory,
      primaryNumeric,
      queryTable,
      queryingTable,
      secondaryCategory,
      numericDistributions,
      categories,
      tableColumns,
      tableData,
      t,
    ],
  );

  const leftPanelContent = (
    <>
      <PanelTitle
        icon={<DatabaseOutlined />}
        title={t("nonGeo.dataResources")}
      />
      <div className="nongeo-resource-count">
        <span>
          {t("nonGeo.resourceCount", { count: selectedResource ? 1 : 0 })}
        </span>
        {showPoplarDemo && <Tag color="cyan">{ui("展示数据", "Showcase")}</Tag>}
      </div>
      <div className="nongeo-resource-list">
        {selectedResource && (
          <ResourceRow
            resource={selectedResource}
            active
            onSelect={() => setAnalysisTab("overview")}
          />
        )}
      </div>
    </>
  );

  return (
    <Layout className="workspace">
      <WorkspaceHeader activeTab="nongeo" canBrowseData={canBrowseData} />
      <div className="workspace-body workspace-body-nongeo nongeo-simple">
        <main className="nongeo-stage" aria-label={t("nonGeo.workbenchLabel")}>
          <aside className="nongeo-panel nongeo-resource-panel">
            <div className="nongeo-left-content">{leftPanelContent}</div>
          </aside>

          <section className="nongeo-panel nongeo-analysis-panel">
            <div className="nongeo-analysis-head">
              <div>
                <Typography.Text className="nongeo-kicker">
                  {t("nonGeo.pageKicker", { brand: platformBrand.shortName })}
                </Typography.Text>
                <div className="nongeo-analysis-title-row">
                  <Typography.Title level={2}>
                    {analytics?.resource.name ??
                      selectedResource?.name ??
                      ui("非地理数据", "Non-spatial data")}
                  </Typography.Title>
                  {showPoplarDemo ? (
                    <Tag color="gold">{t("nonGeo.demoBadge")}</Tag>
                  ) : null}
                </div>
              </div>
              {showPoplarDemo && (
                <Space className="nongeo-analysis-tools">
                  <Button
                    aria-label={t("nonGeo.queryDetails")}
                    icon={<FileSearchOutlined />}
                    loading={queryingTable}
                    onClick={() => void queryTable()}
                  >
                    {t("nonGeo.queryDetails")}
                  </Button>
                </Space>
              )}
            </div>

            {showPoplarDemo && (
              <p className="nongeo-demo-note">
                {ui(
                  "内置示例，用于体验图表和明细查询。",
                  "Built-in example for exploring charts and table queries.",
                )}
              </p>
            )}
            {!canBrowseData ? (
              <PermissionEmpty />
            ) : analytics ? (
              <Tabs
                className="nongeo-tabs"
                activeKey={analysisTab}
                onChange={setAnalysisTab}
                items={tabs}
              />
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={ui(
                  "当前项目暂无演示数据",
                  "No showcase data in this project",
                )}
              />
            )}
            {analytics && canBrowseData && (
              <Collapse
                className="nongeo-details"
                ghost
                items={[
                  {
                    key: "details",
                    label: ui("数据说明与字段", "Data and field details"),
                    children: (
                      <>
                        <p>{analytics.resource.description}</p>
                        <FieldSummary fields={analytics.fields} />
                        <FieldCompleteness fields={analytics.fields} />
                      </>
                    ),
                  },
                ]}
              />
            )}
          </section>
        </main>
      </div>
    </Layout>
  );
}

function OverviewContent({
  analytics,
  primaryCategory,
  secondaryCategory,
  primaryNumeric,
  compositionCategory,
  metrics,
  onMetric,
  categories,
  onCategory,
}: {
  analytics: NonGeoAnalytics | null;
  primaryCategory: CategoricalDistribution | null;
  secondaryCategory: CategoricalDistribution | null;
  primaryNumeric: NumericDistribution | null;
  compositionCategory: CategoricalDistribution | null;
  categories: CategoricalDistribution[];
  onCategory: (field: string) => void;
  metrics: NumericDistribution[];
  onMetric: (field: string) => void;
}) {
  const { t } = useTranslation();
  if (!analytics) {
    return null;
  }
  return (
    <div className="nongeo-tab-grid">
      <div className="nongeo-metric-grid">
        <MetricCard
          icon={<DatabaseOutlined />}
          label={t("nonGeo.totalRecords")}
          value={formatCompact(analytics.summary.rowCount)}
          detail={t("nonGeo.fieldsSuffix", {
            count: analytics.summary.fieldCount,
          })}
        />
        <MetricCard
          icon={<NumberOutlined />}
          label={t("nonGeo.numericMetrics")}
          value={analytics.summary.numericFieldCount}
          detail={t("nonGeo.numericMetricsNote")}
        />
        <MetricCard
          icon={<TagsOutlined />}
          label={t("nonGeo.categoryDimensions")}
          value={analytics.summary.categoricalFieldCount}
          detail={t("nonGeo.categoryDimensionsNote")}
        />
        <MetricCard
          icon={<AppstoreOutlined />}
          label={t("nonGeo.completeness")}
          value={formatPercent(analytics.summary.completeness)}
          detail={t("nonGeo.completenessNote")}
        />
      </div>
      <div className="nongeo-chart-grid nongeo-chart-grid-2">
        <ChartBox
          title={primaryCategory?.label ?? t("nonGeo.categoryDistribution")}
          extra={
            <Select
              aria-label={t("nonGeo.categoryDimensions")}
              style={{ minWidth: 130 }}
              value={primaryCategory?.field}
              onChange={onCategory}
              options={categories.map((item) => ({
                value: item.field,
                label: item.label,
              }))}
            />
          }
          icon={<BarChartOutlined />}
        >
          {primaryCategory ? (
            <HorizontalBarChart data={primaryCategory} />
          ) : (
            <ChartEmpty />
          )}
        </ChartBox>
        <ChartBox
          title={`${t("nonGeo.structureShare")}${compositionCategory ? ` · ${compositionCategory.label}` : ""}`}
          icon={<DotChartOutlined />}
        >
          {compositionCategory ? (
            <DonutChart data={compositionCategory} />
          ) : (
            <ChartEmpty />
          )}
        </ChartBox>
        <ChartBox
          title={`${t("nonGeo.numericDistribution")}${primaryNumeric ? ` · ${primaryNumeric.label}` : ""}`}
          extra={
            <Select
              aria-label={t("nonGeo.metricField")}
              value={primaryNumeric?.field}
              onChange={onMetric}
              style={{ minWidth: 130 }}
              options={metrics.map((item) => ({
                value: item.field,
                label: item.label,
              }))}
            />
          }
          icon={<LineChartOutlined />}
        >
          {primaryNumeric ? (
            <HistogramChart data={primaryNumeric} />
          ) : (
            <ChartEmpty />
          )}
        </ChartBox>
        <ChartBox
          title={secondaryCategory?.label ?? t("nonGeo.categoryRanking")}
          icon={<BranchesOutlined />}
        >
          {secondaryCategory ? (
            <RankingList data={secondaryCategory} />
          ) : (
            <ChartEmpty />
          )}
        </ChartBox>
      </div>
    </div>
  );
}

function CompositionContent({
  analytics,
  selected,
}: {
  analytics: NonGeoAnalytics | null;
  selected: CategoricalDistribution | null;
}) {
  const { t } = useTranslation();
  if (!analytics) {
    return null;
  }
  return (
    <div className="nongeo-chart-grid nongeo-chart-grid-3">
      {analytics.categoricalDistributions.slice(0, 6).map((distribution) => (
        <ChartBox
          key={distribution.field}
          title={distribution.label}
          icon={<BarChartOutlined />}
        >
          <HorizontalBarChart data={distribution} compact />
        </ChartBox>
      ))}
      {selected && (
        <ChartBox
          title={t("nonGeo.structureShare")}
          icon={<DotChartOutlined />}
        >
          <DonutChart data={selected} />
        </ChartBox>
      )}
    </div>
  );
}

function TraitsContent({
  analytics,
  tableData,
}: {
  analytics: NonGeoAnalytics | null;
  tableData: NonGeoTableQueryResult | null;
}) {
  const { t } = useTranslation();
  if (!analytics) {
    return null;
  }
  return (
    <div className="nongeo-chart-grid nongeo-chart-grid-2">
      <ChartBox
        title={t("nonGeo.traitRelationship")}
        icon={<DotChartOutlined />}
      >
        <NonGeoScatter
          key={analytics.resource.id}
          tableData={tableData}
          fields={analytics.fields}
        />
      </ChartBox>
      <ChartBox
        title={t("nonGeo.ecologicalCorrelation")}
        icon={<RadarChartOutlined />}
      >
        {analytics.correlation ? (
          <CorrelationHeatmap data={analytics.correlation} />
        ) : (
          <ChartEmpty />
        )}
      </ChartBox>
    </div>
  );
}

function TableContent({
  data,
  columns,
  querying,
  onQuery,
}: {
  data: NonGeoTableQueryResult | null;
  columns: TableProps<TableRow>["columns"];
  querying: boolean;
  onQuery: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="nongeo-table-panel">
      <div className="nongeo-table-toolbar">
        <Typography.Text>
          {data
            ? t("nonGeo.tableStatus", {
                returned: data.returnedCount,
                total: data.totalCount,
              })
            : t("nonGeo.noTablePreview")}
        </Typography.Text>
        <Button icon={<ReloadOutlined />} loading={querying} onClick={onQuery}>
          {t("nonGeo.refreshDetails")}
        </Button>
      </div>
      <Table<TableRow>
        size="small"
        className="nongeo-data-table"
        columns={columns}
        dataSource={data?.rows ?? []}
        rowKey={stableRowKey}
        pagination={{ pageSize: 8, showSizeChanger: false }}
        scroll={{ x: 920 }}
      />
    </div>
  );
}

function ResourceRow({
  resource,
  active,
  onSelect,
}: {
  resource: ResourceListItem;
  active: boolean;
  onSelect: () => void;
}) {
  const { t } = useTranslation();
  const typeLabel = nonGeoResourceTypeLabel(resource.dataType, t);
  const count = resource.itemCount;
  const isDemo = resource.id === NON_GEO_DEMO_RESOURCE_ID;
  return (
    <button
      type="button"
      className={
        active
          ? "nongeo-resource-row nongeo-resource-row-active"
          : "nongeo-resource-row"
      }
      onClick={onSelect}
    >
      <span className="nongeo-resource-row-top">
        <Typography.Text strong>{resource.name}</Typography.Text>
        <Badge
          color={isDemo ? "#f3b54a" : active ? "#28e0c2" : "#6c8790"}
          text={isDemo ? t("nonGeo.demoBadge") : typeLabel}
        />
      </span>
      <span className="nongeo-resource-row-meta">
        {resourceCategoryName(resource) ?? t("nonGeo.uncategorized")} ·{" "}
        {resourceFormatLabel(resource)}
      </span>
      <span className="nongeo-resource-row-foot">
        <span>
          {t("nonGeo.recordsSuffix", { count: formatCompact(count ?? 0) })}
        </span>
        <span>{resource.source || t("nonGeo.notRecordedSource")}</span>
      </span>
    </button>
  );
}

function nonGeoResourceTypeLabel(
  dataType: ResourceListItem["dataType"],
  t: TFunction,
) {
  switch (dataType) {
    case "vector":
      return i18n.language.startsWith("en") ? "Vector" : "矢量";
    case "raster":
      return i18n.language.startsWith("en") ? "Raster" : "栅格";
    case "table":
      return t("nonGeo.tableType");
    case "gene":
      return t("nonGeo.geneType");
    case "document":
      return t("nonGeo.documentType");
    case "image":
      return t("nonGeo.imageType");
    default:
      return dataType;
  }
}

function PanelTitle({
  icon,
  title,
  extra,
}: {
  icon: ReactNode;
  title: string;
  extra?: ReactNode;
}) {
  return (
    <div className="nongeo-panel-title">
      <span>
        {icon}
        <Typography.Text strong>{title}</Typography.Text>
      </span>
      {extra}
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: string | number;
  detail: string;
}) {
  return (
    <section className="nongeo-metric-card">
      <span className="nongeo-metric-icon">{icon}</span>
      <div>
        <Typography.Text>{label}</Typography.Text>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </section>
  );
}

function ChartBox({
  title,
  icon,
  children,
  extra,
}: {
  extra?: ReactNode;
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="nongeo-chart-box">
      <div className="nongeo-chart-title">
        <span>
          {icon}
          <Typography.Text strong>{title}</Typography.Text>
        </span>
        {extra}
      </div>
      {children}
    </section>
  );
}

function HorizontalBarChart({
  data,
  compact = false,
}: {
  data: CategoricalDistribution;
  compact?: boolean;
}) {
  const max = Math.max(...data.items.map((item) => item.count), 1);
  return (
    <div
      className={compact ? "nongeo-bars nongeo-bars-compact" : "nongeo-bars"}
    >
      {data.items.slice(0, compact ? 6 : 8).map((item) => (
        <div
          key={`${data.field}-${valueLabel(item.value)}`}
          className="nongeo-bar-row"
        >
          <span>{valueLabel(item.value)}</span>
          <div>
            <i style={{ width: `${(item.count / max) * 100}%` }} />
          </div>
          <em>{formatCompact(item.count)}</em>
        </div>
      ))}
    </div>
  );
}

function RankingList({ data }: { data: CategoricalDistribution }) {
  return (
    <div className="nongeo-ranking-list">
      {data.items.slice(0, 6).map((item) => (
        <div key={`${data.field}-${valueLabel(item.value)}`}>
          <span>{valueLabel(item.value)}</span>
          <Progress
            percent={Math.round(item.ratio * 100)}
            showInfo={false}
            strokeColor="#16b8a9"
            railColor="rgba(32,91,84,0.12)"
          />
          <em>{formatPercent(item.ratio)}</em>
        </div>
      ))}
    </div>
  );
}

function DonutChart({ data }: { data: CategoricalDistribution }) {
  const { t } = useTranslation();
  const total = Math.max(data.total, 1);
  let cursor = 0;
  const radius = 44;
  const circumference = 2 * Math.PI * radius;
  return (
    <div className="nongeo-donut-wrap">
      <svg viewBox="0 0 120 120" aria-label={data.label}>
        <circle cx="60" cy="60" r={radius} className="nongeo-donut-track" />
        {data.items.slice(0, 6).map((item, itemIndex) => {
          const length = Math.max(item.count / total, 0.008) * circumference;
          const offset = -cursor * circumference;
          cursor += item.count / total;
          return (
            <circle
              key={`${data.field}-${valueLabel(item.value)}`}
              cx="60"
              cy="60"
              r={radius}
              className="nongeo-donut-segment"
              style={{
                stroke: analyticsPalette[itemIndex % analyticsPalette.length],
                strokeDasharray: `${length} ${circumference - length}`,
                strokeDashoffset: offset,
              }}
            />
          );
        })}
        <text x="60" y="56" textAnchor="middle">
          {formatCompact(total)}
        </text>
        <text x="60" y="73" textAnchor="middle" className="nongeo-donut-sub">
          {t("nonGeo.recordsLabel")}
        </text>
      </svg>
      <div className="nongeo-donut-legend">
        {data.items.slice(0, 6).map((item, itemIndex) => (
          <span key={`${data.field}-legend-${valueLabel(item.value)}`}>
            <i
              style={{
                background:
                  analyticsPalette[itemIndex % analyticsPalette.length],
              }}
            />
            {valueLabel(item.value)}
          </span>
        ))}
      </div>
    </div>
  );
}

function HistogramChart({ data }: { data: NumericDistribution }) {
  const max = Math.max(...data.bins.map((bin) => bin.count), 1);
  return (
    <div className="nongeo-histogram">
      <div className="nongeo-histogram-bars">
        {data.bins.map((bin) => (
          <span
            key={`${data.field}-${bin.label}`}
            style={{
              height: `${Math.max((bin.count / max) * 100, 6)}%`,
              background: "#357487",
            }}
            title={`${bin.label}: ${bin.count}`}
          />
        ))}
      </div>
      <div className="nongeo-histogram-axis">
        <span>{formatNumber(data.min)}</span>
        <span>{formatNumber((data.min + data.max) / 2)}</span>
        <span>{formatNumber(data.max)}</span>
      </div>
    </div>
  );
}

function CorrelationHeatmap({
  data,
}: {
  data: NonGeoAnalytics["correlation"];
}) {
  const ui = useComputeText();
  if (!data) return <ChartEmpty />;
  return (
    <div>
      <table
        className="analysis-correlation"
        aria-label={ui("指标相关系数", "Measure correlations")}
      >
        <thead>
          <tr>
            <th scope="col" />
            {data.fields.map((field) => (
              <th key={field} scope="col">
                {field}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.fields.map((row, rowIndex) => (
            <tr key={row}>
              <th scope="row">{row}</th>
              {data.fields.map((column, columnIndex) => {
                const value = data.values[rowIndex]?.[columnIndex];
                return (
                  <td
                    key={column}
                    style={{
                      background:
                        typeof value === "number" && Number.isFinite(value)
                          ? correlationColor(value)
                          : "#f4f6f8",
                    }}
                  >
                    {typeof value === "number" && Number.isFinite(value)
                      ? value.toFixed(2)
                      : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="analysis-chart-note">
        {ui(
          "蓝色为正相关，棕色为负相关；颜色越深，相关程度越强。",
          "Blue indicates positive correlation, brown negative; darker colors indicate stronger relationships.",
        )}
      </p>
    </div>
  );
}

function FieldSummary({ fields }: { fields: FieldProfile[] }) {
  const { t } = useTranslation();
  return (
    <div className="nongeo-field-summary">
      {fields.slice(0, 8).map((field) => (
        <div key={field.name}>
          <span>
            <strong>{field.label || field.name}</strong>
            <small>{fieldRoleLabel(field.role, t)}</small>
          </span>
          <em>{formatPercent(field.completeness)}</em>
        </div>
      ))}
    </div>
  );
}

function FieldCompleteness({ fields }: { fields: FieldProfile[] }) {
  return (
    <div className="nongeo-field-completeness">
      {fields.slice(0, 8).map((field) => (
        <div key={field.name}>
          <span>{field.label || field.name}</span>
          <Progress
            percent={Math.round(field.completeness * 100)}
            size="small"
            showInfo={false}
            strokeColor="#16b8a9"
            railColor="rgba(32,91,84,0.12)"
          />
        </div>
      ))}
    </div>
  );
}

function ChartEmpty() {
  const { t } = useTranslation();
  return (
    <Empty
      image={Empty.PRESENTED_IMAGE_SIMPLE}
      description={t("nonGeo.noVisualizationData")}
      className="nongeo-chart-empty"
    />
  );
}

function PermissionEmpty() {
  const { t } = useTranslation();
  return (
    <Alert
      type="warning"
      showIcon
      title={t("nonGeo.noBrowsePermission")}
      description={t("nonGeo.noBrowsePermissionDescription")}
    />
  );
}

function stableRowKey(row: TableRow) {
  const preferred =
    row.id ?? row.ID ?? row["采集号"] ?? row["种"] ?? row["Sample"];
  if (preferred !== undefined && preferred !== null) {
    return String(preferred);
  }
  return Object.entries(row)
    .slice(0, 4)
    .map(([key, value]) => `${key}:${valueLabel(value)}`)
    .join("|");
}

function valueLabel(value: string | number | boolean | null | undefined) {
  if (value === null || value === undefined || value === "") {
    return i18n.t("nonGeo.notRecorded");
  }
  if (typeof value === "number") {
    return formatNumber(value);
  }
  if (typeof value === "boolean") {
    return value ? i18n.t("nonGeo.booleanYes") : i18n.t("nonGeo.booleanNo");
  }
  return value;
}

function formatCompact(value: number) {
  return new Intl.NumberFormat(currentLocale(), {
    notation: value >= 10000 ? "compact" : "standard",
    maximumFractionDigits: 1,
  }).format(value);
}

function formatNumber(value: number) {
  return new Intl.NumberFormat(currentLocale(), {
    maximumFractionDigits: Math.abs(value) < 10 ? 2 : 1,
  }).format(value);
}

function formatPercent(value: number) {
  return `${new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 1 }).format(value * 100)}%`;
}

function fieldRoleLabel(role: FieldProfile["role"], t: TFunction) {
  switch (role) {
    case "identifier":
      return t("nonGeo.roleIdentifier");
    case "category":
      return t("nonGeo.roleCategory");
    case "measure":
      return t("nonGeo.roleMeasure");
    case "date":
      return t("nonGeo.roleDate");
    case "text":
      return t("nonGeo.roleText");
    case "coordinate":
      return t("nonGeo.roleCoordinate");
    default:
      return t("nonGeo.roleUnknown");
  }
}

function correlationColor(value: number) {
  const normalized = Math.max(-1, Math.min(1, value));
  if (normalized >= 0) {
    const alpha = 0.18 + normalized * 0.72;
    return `rgba(53, 116, 135, ${alpha * 0.65})`;
  }
  return `rgba(170, 118, 72, ${0.12 + Math.abs(normalized) * 0.46})`;
}
