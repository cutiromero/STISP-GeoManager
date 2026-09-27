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
  SearchOutlined,
  TableOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Collapse,
  App,
  Badge,
  Button,
  Empty,
  Input,
  Layout,
  Progress,
  Segmented,
  Select,
  Skeleton,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import type { TableProps } from "antd";
import type { TFunction } from "i18next";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import WorkspaceHeader from "../components/WorkspaceHeader";
import { platformBrand } from "../config/platformBrand";
import { useAppContext } from "../contexts/AppContext";
import i18n, { currentLocale } from "../i18n";
import type {
  DataDomainType,
  DataSchemaSummary,
  NonGeoAnalytics,
  NonGeoFieldProfile,
  NonGeoTableQueryResult,
  NonGeoTableRow,
  ResourceListItem,
} from "../types";
import {
  isGeographicResource,
  resourceCategoryName,
  resourceFormatLabel,
} from "../utils/resources";
import { taxonomyLeafOptions } from "../utils/taxonomy";
import { createNonGeoDemo, NON_GEO_DEMO_RESOURCE_ID } from "./nonGeoDemoData";
import NonGeoScatter, { isMeasurement } from "./NonGeoScatter";
import { useComputeText } from "../compute/ui";
import "../styles/nongeo-simple.css";

type ResourceTypeFilter = "all" | "spatial" | "non_spatial";

type CategoricalDistribution =
  NonGeoAnalytics["categoricalDistributions"][number];
type NumericDistribution = NonGeoAnalytics["numericDistributions"][number];
type FieldProfile = NonGeoFieldProfile;
type TableRow = NonGeoTableRow;

const analysisDomains = new Set<DataDomainType>([
  "germplasm",
  "genome",
  "individual",
  "community",
  "population",
  "field_survey",
  "remote_sensing",
  "molecular",
  "vector",
  "other",
]);

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

export default function NonGeoPage() {
  const { user } = useAppContext();
  const ui = useComputeText();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { t, i18n: translationI18n } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const permissions = user?.permissions;
  const canBrowseData = Boolean(permissions?.canBrowseData);
  const canQueryData = Boolean(permissions?.canQueryData);
  const [resources, setResources] = useState<ResourceListItem[]>([]);
  const [dataSchema, setDataSchema] = useState<DataSchemaSummary | null>(null);
  const [resourceKeyword, setResourceKeyword] = useState("");
  const [resourceType, setResourceType] = useState<ResourceTypeFilter>("all");
  const [activeResourceId, setActiveResourceId] = useState<number | null>(null);
  const [loadingResources, setLoadingResources] = useState(false);
  const resourceRequestSequenceRef = useRef(0);
  const analyticsRequestSequenceRef = useRef(0);
  const tableQueryRequestSequenceRef = useRef(0);
  const [analytics, setAnalytics] = useState<NonGeoAnalytics | null>(null);
  const [analyticsError, setAnalyticsError] = useState("");
  const [loadingAnalytics, setLoadingAnalytics] = useState(false);
  const [tableResult, setTableResult] = useState<NonGeoTableQueryResult | null>(
    null,
  );
  const [queryingTable, setQueryingTable] = useState(false);
  const [analysisTab, setAnalysisTab] = useState("overview");
  const [selectedMetricField, setSelectedMetricField] = useState<
    string | undefined
  >();
  const selectedDomainType = useMemo<DataDomainType | null>(() => {
    const value = searchParams.get("domainType");
    return analysisDomains.has(value as DataDomainType)
      ? (value as DataDomainType)
      : null;
  }, [searchParams]);
  const selectedCategoryCode = searchParams.get("categoryCode") || undefined;
  const demoAvailable = !selectedDomainType && !selectedCategoryCode;
  const demoBundle = useMemo(
    () => createNonGeoDemo(currentLocale()),
    [translationI18n.resolvedLanguage],
  );
  const effectiveResources = useMemo(
    () => (demoAvailable ? [...resources, demoBundle.resource] : resources),
    [demoAvailable, demoBundle.resource, resources],
  );
  const categoryOptions = useMemo(
    () => taxonomyLeafOptions(dataSchema),
    [dataSchema],
  );
  const nonGeoTypeOptions = [
    { label: t("nonGeo.filterAll"), value: "all" },
    { label: ui("地理", "Spatial"), value: "spatial" },
    { label: ui("非地理", "Non-spatial"), value: "non_spatial" },
  ];
  const selectedResource = useMemo(
    () =>
      effectiveResources.find((resource) => resource.id === activeResourceId) ??
      null,
    [activeResourceId, effectiveResources],
  );

  const filteredResources = useMemo(() => {
    const keyword = resourceKeyword.trim().toLowerCase();
    return resources.filter((resource) => {
      if (
        resourceType !== "all" &&
        (isGeographicResource(resource) ? "spatial" : "non_spatial") !==
          resourceType
      ) {
        return false;
      }
      if (!keyword) {
        return true;
      }
      const haystack = [
        resource.name,
        resource.code,
        resource.source,
        resource.provider,
        resource.description,
        resourceCategoryName(resource) ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(keyword);
    });
  }, [resources, resourceKeyword, resourceType]);

  const tableData = tableResult ?? analytics?.tablePreview ?? null;
  const [categoryField, setCategoryField] = useState<string>();
  const categories = analytics?.categoricalDistributions ?? [];
  const primaryCategory =
    categories.find((item) => item.field === categoryField) ??
    categories[0] ??
    null;
  const secondaryCategory =
    categories.find((item) => item.field !== primaryCategory?.field) ?? null;
  const compositionCategory = primaryCategory;
  const canAnalyzeSelected =
    selectedResource?.dataType === "table" ||
    selectedResource?.dataType === "gene";
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
  const loadResources = useCallback(async () => {
    const requestSequence = ++resourceRequestSequenceRef.current;
    if (!canBrowseData) {
      setResources([]);
      setActiveResourceId(null);
      setLoadingResources(false);
      return;
    }
    setLoadingResources(true);
    try {
      const response = await api.resources({
        ...(selectedDomainType ? { domainType: selectedDomainType } : {}),
        ...(selectedCategoryCode ? { categoryCode: selectedCategoryCode } : {}),
      });
      const items = response.items;
      if (requestSequence === resourceRequestSequenceRef.current) {
        setResources(items);
        setActiveResourceId((current) => {
          const currentStillExists =
            current === NON_GEO_DEMO_RESOURCE_ID
              ? demoAvailable
              : current !== null &&
                items.some((resource) => resource.id === current);
          if (currentStillExists) {
            return current;
          }
          return items[0]?.id ?? null;
        });
      }
    } catch (error) {
      if (requestSequence === resourceRequestSequenceRef.current) {
        setResources([]);
        setActiveResourceId(null);
        if (demoAvailable) {
          message.warning(t("nonGeo.resourcesLoadFailed"));
        } else {
          message.error(
            error instanceof Error
              ? error.message
              : t("nonGeo.resourcesLoadFailed"),
          );
        }
      }
    } finally {
      if (requestSequence === resourceRequestSequenceRef.current) {
        setLoadingResources(false);
      }
    }
  }, [
    canBrowseData,
    canQueryData,
    demoAvailable,
    message,
    selectedCategoryCode,
    selectedDomainType,
    t,
  ]);

  useEffect(() => {
    if (!canBrowseData) return;
    let ignore = false;
    api
      .dataSchemaSummary()
      .then((result) => {
        if (!ignore) setDataSchema(result);
      })
      .catch(() => {
        if (!ignore) setDataSchema(null);
      });
    return () => {
      ignore = true;
    };
  }, [canBrowseData]);

  const loadAnalytics = useCallback(
    async (resourceId: number) => {
      const requestSequence = ++analyticsRequestSequenceRef.current;
      setLoadingAnalytics(true);
      setAnalyticsError("");
      setTableResult(null);
      if (resourceId === NON_GEO_DEMO_RESOURCE_ID && demoAvailable) {
        setAnalytics(demoBundle.analytics);
        setLoadingAnalytics(false);
        return;
      }
      if (!canQueryData || !canAnalyzeSelected) {
        setAnalytics(null);
        setAnalyticsError(
          canAnalyzeSelected && !canQueryData
            ? t("nonGeo.noQueryPermission")
            : "",
        );
        setLoadingAnalytics(false);
        return;
      }
      try {
        const result = await api.nonGeoAnalysis(resourceId);
        if (requestSequence === analyticsRequestSequenceRef.current) {
          setAnalytics(result);
          setAnalyticsError("");
        }
      } catch (error) {
        if (requestSequence === analyticsRequestSequenceRef.current) {
          setAnalytics(null);
          setAnalyticsError(
            error instanceof Error ? error.message : t("nonGeo.analysisFailed"),
          );
        }
      } finally {
        if (requestSequence === analyticsRequestSequenceRef.current) {
          setLoadingAnalytics(false);
        }
      }
    },
    [canQueryData, canAnalyzeSelected, demoAvailable, demoBundle.analytics, t],
  );

  const queryTable = useCallback(async () => {
    if (activeResourceId === null) {
      return;
    }
    if (activeResourceId === NON_GEO_DEMO_RESOURCE_ID && demoAvailable) {
      setQueryingTable(true);
      setTableResult(demoBundle.table);
      setAnalysisTab("table");
      setQueryingTable(false);
      return;
    }
    if (!canQueryData) {
      message.warning(t("nonGeo.noQueryPermission"));
      return;
    }
    const requestSequence = ++tableQueryRequestSequenceRef.current;
    setQueryingTable(true);
    try {
      const result = await api.nonGeoQuery(activeResourceId, {
        limit: 80,
        offset: 0,
        ...(primaryNumeric
          ? { sortField: primaryNumeric.field, sortDirection: "desc" as const }
          : {}),
      });
      if (requestSequence === tableQueryRequestSequenceRef.current) {
        setTableResult(result);
        setAnalysisTab("table");
      }
    } catch (error) {
      if (requestSequence === tableQueryRequestSequenceRef.current) {
        message.error(
          error instanceof Error
            ? error.message
            : t("nonGeo.detailsQueryFailed"),
        );
      }
    } finally {
      if (requestSequence === tableQueryRequestSequenceRef.current) {
        setQueryingTable(false);
      }
    }
  }, [
    activeResourceId,
    canQueryData,
    demoAvailable,
    demoBundle.table,
    message,
    primaryNumeric,
    t,
  ]);

  useEffect(() => {
    void loadResources();
  }, [loadResources]);

  useEffect(() => {
    setActiveResourceId((current) => {
      if (
        current === NON_GEO_DEMO_RESOURCE_ID ||
        filteredResources.some((item) => item.id === current)
      )
        return current;
      return filteredResources[0]?.id ?? null;
    });
  }, [filteredResources]);

  useEffect(() => {
    tableQueryRequestSequenceRef.current += 1;
    setQueryingTable(false);
    setTableResult(null);
    if (activeResourceId !== null) {
      void loadAnalytics(activeResourceId);
      return;
    }
    analyticsRequestSequenceRef.current += 1;
    setAnalytics(null);
    setAnalyticsError("");
    setLoadingAnalytics(false);
  }, [activeResourceId, loadAnalytics]);

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

  const dataTypeLabel =
    resourceType === "spatial"
      ? ui("地理数据", "Spatial data")
      : resourceType === "non_spatial"
        ? ui("非地理数据", "Non-spatial data")
        : t("nonGeo.allResources");

  const leftPanelContent = (
    <>
      <PanelTitle
        icon={<DatabaseOutlined />}
        title={t("nonGeo.dataResources")}
        extra={
          <Button
            size="small"
            type="text"
            aria-label={t("nonGeo.refreshResources")}
            icon={<ReloadOutlined />}
            loading={loadingResources}
            onClick={() => void loadResources()}
          />
        }
      />
      <Input
        prefix={<SearchOutlined />}
        placeholder={t("nonGeo.searchPlaceholder")}
        allowClear
        value={resourceKeyword}
        onChange={(event) => setResourceKeyword(event.target.value)}
      />
      <Select
        allowClear
        showSearch
        optionFilterProp="label"
        placeholder={t("nonGeo.categoryPlaceholder")}
        value={selectedCategoryCode}
        options={categoryOptions}
        onChange={(categoryCode) => {
          const next = new URLSearchParams(searchParams);
          if (categoryCode) next.set("categoryCode", categoryCode);
          else next.delete("categoryCode");
          setSearchParams(next, { replace: true });
        }}
      />
      <Segmented
        block
        options={nonGeoTypeOptions}
        value={resourceType}
        onChange={(value) => setResourceType(value as ResourceTypeFilter)}
      />
      <div className="nongeo-resource-count">
        <span>
          {t("nonGeo.resourceCount", { count: filteredResources.length })}
        </span>
        <Tag color="cyan">{dataTypeLabel}</Tag>
      </div>
      <div className="nongeo-resource-list">
        {loadingResources ? (
          <Skeleton active paragraph={{ rows: 7 }} title={false} />
        ) : filteredResources.length > 0 ? (
          filteredResources.map((resource) => (
            <ResourceRow
              key={resourceKey(resource)}
              resource={resource}
              active={resource.id === activeResourceId}
              onSelect={() => setActiveResourceId(resource.id)}
            />
          ))
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t("nonGeo.noAnalyzableResources")}
          />
        )}
      </div>
      {canBrowseData && demoAvailable && (
        <section className="analysis-example-entry">
          <Typography.Text type="secondary">
            {ui("示例", "Example")}
          </Typography.Text>
          <Button
            block
            onClick={() => setActiveResourceId(NON_GEO_DEMO_RESOURCE_ID)}
          >
            {ui("查看胡杨数据示例", "View the poplar example")}
          </Button>
        </section>
      )}
    </>
  );

  return (
    <Layout className="workspace">
      <WorkspaceHeader
        activeTab="nongeo"
        canBrowseData={canBrowseData}
        dataSchema={dataSchema}
      />
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
                      t("nonGeo.selectResource")}
                  </Typography.Title>
                  {activeResourceId === NON_GEO_DEMO_RESOURCE_ID ? (
                    <Tag color="gold">{t("nonGeo.demoBadge")}</Tag>
                  ) : null}
                </div>
              </div>
              {canAnalyzeSelected &&
                (canQueryData ||
                  activeResourceId === NON_GEO_DEMO_RESOURCE_ID) && (
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

            {activeResourceId === NON_GEO_DEMO_RESOURCE_ID && (
              <p className="nongeo-demo-note">
                {ui(
                  "内置示例，用于体验图表和明细查询。",
                  "Built-in example for exploring charts and table queries.",
                )}
              </p>
            )}
            {!canBrowseData ? (
              <PermissionEmpty />
            ) : selectedResource && !canAnalyzeSelected ? (
              <section className="analysis-resource-guide">
                <Tag>
                  {isGeographicResource(selectedResource)
                    ? ui("地理数据", "Spatial data")
                    : ui("非地理数据", "Non-spatial data")}{" "}
                  · {resourceFormatLabel(selectedResource)}
                </Tag>
                <Typography.Title level={4}>
                  {ui("选择分析方式", "Choose an analysis workflow")}
                </Typography.Title>
                <p>
                  {isGeographicResource(selectedResource)
                    ? ui(
                        "空间分布与图层属性在地理工作台查看；裁剪、转换等处理在计算中心进行。",
                        "Explore spatial patterns and layer attributes in the map workspace; use the compute center for clipping, conversion and other processing.",
                      )
                    : ui(
                        "文档、图片等文件可在数据资源中查看。需要统计分析时，可将其中的结构化记录整理为表格后导入。",
                        "View documents, images and other files in data resources. Import structured records as a table to analyze them statistically.",
                      )}
                </p>
                <Space wrap>
                  {isGeographicResource(selectedResource) && (
                    <Button
                      onClick={() =>
                        navigate(
                          `/map?resourceQ=${encodeURIComponent(selectedResource.name)}`,
                        )
                      }
                    >
                      {ui("在地理工作台查找", "Find in map workspace")}
                    </Button>
                  )}
                  {isGeographicResource(selectedResource) && (
                    <Button onClick={() => navigate("/compute")}>
                      {ui("查看计算工具", "Browse compute tools")}
                    </Button>
                  )}
                  <Button onClick={() => navigate("/resources/catalog")}>
                    {ui("查看数据资源", "Open data resources")}
                  </Button>
                </Space>
              </section>
            ) : loadingAnalytics ? (
              <div className="nongeo-loading">
                <Skeleton active paragraph={{ rows: 12 }} />
              </div>
            ) : analyticsError ? (
              <Alert
                type="warning"
                showIcon
                title={t("nonGeo.analysisUnavailable")}
                description={analyticsError}
              />
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
                description={t("nonGeo.selectLeftResource")}
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

function resourceKey(resource: ResourceListItem) {
  return `${resource.dataType}-${String(resource.id)}-${resource.name}`;
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
