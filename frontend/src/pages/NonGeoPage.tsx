import {
  AppstoreOutlined,
  BarChartOutlined,
  BranchesOutlined,
  DatabaseOutlined,
  DotChartOutlined,
  ExperimentOutlined,
  FieldTimeOutlined,
  FileSearchOutlined,
  LineChartOutlined,
  NumberOutlined,
  ProfileOutlined,
  RadarChartOutlined,
  ReloadOutlined,
  SearchOutlined,
  TableOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import {
  Alert,
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
import { useSearchParams } from "react-router-dom";
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
  isNonGeographicResource,
  resourceCategoryName,
  resourceFormatLabel,
  resourceProvider,
} from "../utils/resources";
import { taxonomyLeafOptions } from "../utils/taxonomy";
import { createNonGeoDemo, NON_GEO_DEMO_RESOURCE_ID } from "./nonGeoDemoData";

type ResourceTypeFilter = "all" | "table" | "gene";
type LeftPanelKey = "data" | "views" | "workspace" | "topics";
type NonGeoDomainType = Extract<DataDomainType, "molecular" | "genome">;
type CategoricalDistribution =
  NonGeoAnalytics["categoricalDistributions"][number];
type NumericDistribution = NonGeoAnalytics["numericDistributions"][number];
type FieldProfile = NonGeoFieldProfile;
type TableRow = NonGeoTableRow;

const nonGeoDomainTypes = new Set<DataDomainType>(["molecular", "genome"]);

const leftPanelMeta: Array<{
  key: LeftPanelKey;
  labelKey: string;
  icon: ReactNode;
}> = [
  { key: "data", labelKey: "nonGeo.tabData", icon: <DatabaseOutlined /> },
  {
    key: "views",
    labelKey: "nonGeo.tabViews",
    icon: <AppstoreOutlined />,
  },
  {
    key: "workspace",
    labelKey: "nonGeo.tabWorkspace",
    icon: <ProfileOutlined />,
  },
  {
    key: "topics",
    labelKey: "nonGeo.tabTopics",
    icon: <ExperimentOutlined />,
  },
];

const analysisViewMeta = [
  {
    key: "overview",
    titleKey: "nonGeo.overviewView",
    descriptionKey: "nonGeo.overviewViewDescription",
    icon: <BarChartOutlined />,
  },
  {
    key: "species",
    titleKey: "nonGeo.compositionView",
    descriptionKey: "nonGeo.compositionViewDescription",
    icon: <BranchesOutlined />,
  },
  {
    key: "traits",
    titleKey: "nonGeo.traitsView",
    descriptionKey: "nonGeo.traitsViewDescription",
    icon: <RadarChartOutlined />,
  },
  {
    key: "table",
    titleKey: "nonGeo.tableView",
    descriptionKey: "nonGeo.tableViewDescription",
    icon: <TableOutlined />,
  },
];

const topicPresetMeta = [
  {
    key: "species",
    titleKey: "nonGeo.communityTopic",
    descriptionKey: "nonGeo.communityTopicDescription",
  },
  {
    key: "traits",
    titleKey: "nonGeo.traitsTopic",
    descriptionKey: "nonGeo.traitsTopicDescription",
  },
  {
    key: "overview",
    titleKey: "nonGeo.qualityTopic",
    descriptionKey: "nonGeo.qualityTopicDescription",
  },
  {
    key: "table",
    titleKey: "nonGeo.recordsTopic",
    descriptionKey: "nonGeo.recordsTopicDescription",
  },
];

const analyticsPalette = [
  "#28e0c2",
  "#39c8ff",
  "#f3b54a",
  "#8f7cf8",
  "#5ee07a",
  "#ff6f91",
  "#77e4ff",
  "#d7f45d",
];

export default function NonGeoPage() {
  const { user } = useAppContext();
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
  const [activeLeftPanel, setActiveLeftPanel] = useState<LeftPanelKey>("data");
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
  const selectedDomainType = useMemo<NonGeoDomainType | null>(() => {
    const value = searchParams.get("domainType");
    return nonGeoDomainTypes.has(value as DataDomainType)
      ? (value as NonGeoDomainType)
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
    { label: t("nonGeo.ecologicalTable"), value: "table" },
    { label: t("nonGeo.genetics"), value: "gene" },
  ];
  const leftPanelOptions = leftPanelMeta.map((item) => ({
    ...item,
    label: t(item.labelKey),
  }));
  const analysisViewOptions = analysisViewMeta.map((item) => ({
    ...item,
    title: t(item.titleKey),
    description: t(item.descriptionKey),
  }));
  const topicPresets = topicPresetMeta.map((item) => ({
    ...item,
    title: t(item.titleKey),
    description: t(item.descriptionKey),
  }));

  const selectedResource = useMemo(
    () =>
      effectiveResources.find((resource) => resource.id === activeResourceId) ??
      null,
    [activeResourceId, effectiveResources],
  );

  const filteredResources = useMemo(() => {
    const keyword = resourceKeyword.trim().toLowerCase();
    return effectiveResources.filter((resource) => {
      if (resourceType !== "all" && resource.dataType !== resourceType) {
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
  }, [effectiveResources, resourceKeyword, resourceType]);

  const tableData = tableResult ?? analytics?.tablePreview ?? null;
  const primaryCategory = analytics?.categoricalDistributions[0] ?? null;
  const secondaryCategory = analytics?.categoricalDistributions[1] ?? null;
  const lifeFormDistribution =
    analytics?.categoricalDistributions.find((item) =>
      item.field.includes("生活型"),
    ) ??
    analytics?.categoricalDistributions[2] ??
    null;
  const numericDistributions = analytics?.numericDistributions ?? [];
  const primaryNumeric =
    numericDistributions.find((item) => item.field === selectedMetricField) ??
    numericDistributions[0] ??
    null;
  const secondaryNumeric =
    numericDistributions.find((item) => item.field !== primaryNumeric?.field) ??
    numericDistributions[1] ??
    null;
  const measureFields =
    analytics?.fields.filter((field) => field.role === "measure") ?? [];
  const categoryFields =
    analytics?.fields.filter((field) => field.role === "category") ?? [];

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
        spatialClass: "non_spatial",
        ...(selectedDomainType ? { domainType: selectedDomainType } : {}),
        ...(selectedCategoryCode ? { categoryCode: selectedCategoryCode } : {}),
      });
      const items = response.items.filter(isNonGeographicResource);
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
          if (!canQueryData && demoAvailable) {
            return NON_GEO_DEMO_RESOURCE_ID;
          }
          return (
            items[0]?.id ?? (demoAvailable ? NON_GEO_DEMO_RESOURCE_ID : null)
          );
        });
      }
    } catch (error) {
      if (requestSequence === resourceRequestSequenceRef.current) {
        setResources([]);
        setActiveResourceId(demoAvailable ? NON_GEO_DEMO_RESOURCE_ID : null);
        if (demoAvailable) {
          message.warning(t("nonGeo.resourcesUnavailableDemo"));
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
      if (!canQueryData) {
        if (demoAvailable) {
          setActiveResourceId(NON_GEO_DEMO_RESOURCE_ID);
          setAnalytics(demoBundle.analytics);
          setAnalyticsError("");
        } else {
          setAnalytics(null);
          setAnalyticsError(t("nonGeo.noQueryPermission"));
        }
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
          if (demoAvailable) {
            setActiveResourceId(NON_GEO_DEMO_RESOURCE_ID);
            setAnalytics(demoBundle.analytics);
            setAnalyticsError("");
          } else {
            setAnalytics(null);
            setAnalyticsError(
              error instanceof Error
                ? error.message
                : t("nonGeo.analysisFailed"),
            );
          }
        }
      } finally {
        if (requestSequence === analyticsRequestSequenceRef.current) {
          setLoadingAnalytics(false);
        }
      }
    },
    [canQueryData, demoAvailable, demoBundle.analytics, t],
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
    if (!selectedDomainType) {
      return;
    }
    setResourceType("gene");
    setActiveLeftPanel("data");
  }, [selectedDomainType]);

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
          <span>{field.name}</span>
          {field.description && <small>{field.description}</small>}
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
            lifeFormDistribution={lifeFormDistribution}
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
        children: (
          <TraitsContent
            analytics={analytics}
            tableData={tableData}
            numeric={secondaryNumeric}
          />
        ),
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
      lifeFormDistribution,
      primaryCategory,
      primaryNumeric,
      queryTable,
      queryingTable,
      secondaryCategory,
      secondaryNumeric,
      tableColumns,
      tableData,
      t,
    ],
  );

  const activeView =
    analysisViewOptions.find((item) => item.key === analysisTab) ??
    analysisViewOptions[0]!;
  const dataTypeLabel =
    resourceType === "table"
      ? t("nonGeo.ecologicalTables")
      : resourceType === "gene"
        ? t("nonGeo.geneticData")
        : t("nonGeo.allResources");

  const leftPanelContent = (
    <>
      {activeLeftPanel === "data" && (
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
        </>
      )}

      {activeLeftPanel === "views" && (
        <>
          <PanelTitle
            icon={<AppstoreOutlined />}
            title={t("nonGeo.analysisViews")}
          />
          <div className="nongeo-view-list">
            {analysisViewOptions.map((view) => (
              <button
                key={view.key}
                type="button"
                className={
                  analysisTab === view.key
                    ? "nongeo-view-row nongeo-view-row-active"
                    : "nongeo-view-row"
                }
                onClick={() => setAnalysisTab(view.key)}
              >
                <span className="nongeo-view-icon">{view.icon}</span>
                <span>
                  <strong>{view.title}</strong>
                  <small>{view.description}</small>
                </span>
              </button>
            ))}
          </div>
          <section className="nongeo-current-card">
            <Typography.Text strong>
              {t("nonGeo.currentCanvas")}
            </Typography.Text>
            <span>{activeView.title}</span>
            <small>
              {selectedResource?.name ?? t("nonGeo.noResourceSelected")}
            </small>
          </section>
        </>
      )}

      {activeLeftPanel === "workspace" && (
        <>
          <PanelTitle
            icon={<ProfileOutlined />}
            title={t("nonGeo.workspace")}
          />
          <section className="nongeo-current-card nongeo-workspace-card">
            <Typography.Text strong>
              {selectedResource?.name ?? t("nonGeo.noResourceSelected")}
            </Typography.Text>
            <div className="nongeo-state-list">
              <span>
                <small>{t("nonGeo.currentView")}</small>
                <strong>{activeView.title}</strong>
              </span>
              <span>
                <small>{t("nonGeo.recordCount")}</small>
                <strong>
                  {analytics ? formatCompact(analytics.summary.rowCount) : "-"}
                </strong>
              </span>
              <span>
                <small>{t("nonGeo.fieldCount")}</small>
                <strong>{analytics?.summary.fieldCount ?? "-"}</strong>
              </span>
              <span>
                <small>{t("nonGeo.completeness")}</small>
                <strong>
                  {analytics
                    ? formatPercent(analytics.summary.completeness)
                    : "-"}
                </strong>
              </span>
            </div>
          </section>
          <section className="nongeo-mini-section">
            <PanelTitle
              icon={<TagsOutlined />}
              title={t("nonGeo.analysisAssets")}
            />
            <div className="nongeo-chip-grid">
              <span className="nongeo-chip">
                {t("nonGeo.resourceSnapshot")}
              </span>
              <span className="nongeo-chip">{t("nonGeo.viewComposition")}</span>
              <span className="nongeo-chip">{t("nonGeo.fieldDefinition")}</span>
              <span className="nongeo-chip">{t("nonGeo.qualityOverview")}</span>
            </div>
          </section>
        </>
      )}

      {activeLeftPanel === "topics" && (
        <>
          <PanelTitle
            icon={<ExperimentOutlined />}
            title={t("nonGeo.topicAnalysis")}
          />
          <div className="nongeo-topic-list">
            {topicPresets.map((topic) => (
              <button
                key={topic.title}
                type="button"
                className={
                  analysisTab === topic.key
                    ? "nongeo-topic-row nongeo-topic-row-active"
                    : "nongeo-topic-row"
                }
                onClick={() => setAnalysisTab(topic.key)}
              >
                <strong>{topic.title}</strong>
                <small>{topic.description}</small>
              </button>
            ))}
          </div>
        </>
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
      <div className="workspace-body workspace-body-nongeo">
        <main className="nongeo-stage" aria-label={t("nonGeo.workbenchLabel")}>
          <aside className="nongeo-panel nongeo-resource-panel">
            <div className="nongeo-workbench-tabs" role="tablist">
              {leftPanelOptions.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  role="tab"
                  aria-selected={activeLeftPanel === item.key}
                  className={
                    activeLeftPanel === item.key
                      ? "nongeo-workbench-tab nongeo-workbench-tab-active"
                      : "nongeo-workbench-tab"
                  }
                  onClick={() => setActiveLeftPanel(item.key)}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
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
              <Space className="nongeo-analysis-tools">
                <div className="nongeo-metric-selector">
                  <span className="nongeo-metric-selector-icon">
                    <NumberOutlined />
                  </span>
                  <span className="nongeo-metric-selector-label">
                    {t("nonGeo.coreMetric")}
                  </span>
                  <Select
                    className="nongeo-field-select"
                    placeholder={t("nonGeo.metricField")}
                    value={primaryNumeric?.field}
                    popupMatchSelectWidth={false}
                    options={numericDistributions.map((field) => ({
                      value: field.field,
                      label: field.label || field.field,
                    }))}
                    onChange={setSelectedMetricField}
                  />
                </div>
                <Button
                  aria-label={t("nonGeo.queryDetails")}
                  icon={<FileSearchOutlined />}
                  loading={queryingTable}
                  onClick={() => void queryTable()}
                >
                  {t("nonGeo.queryDetails")}
                </Button>
              </Space>
            </div>

            {!canBrowseData ? (
              <PermissionEmpty />
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
          </section>

          <aside className="nongeo-panel nongeo-insight-panel">
            <PanelTitle
              icon={<ProfileOutlined />}
              title={t("nonGeo.fieldsAndInsights")}
            />
            {analytics ? (
              <>
                <section className="nongeo-resource-profile">
                  <Typography.Text strong>
                    {analytics.resource.name}
                  </Typography.Text>
                  <Typography.Paragraph ellipsis={{ rows: 3 }}>
                    {"description" in analytics.resource &&
                    analytics.resource.description
                      ? analytics.resource.description
                      : t("nonGeo.noResourceDescription")}
                  </Typography.Paragraph>
                  <div className="nongeo-profile-tags">
                    <Tag color="cyan">
                      {resourceFormatLabel(analytics.resource)}
                    </Tag>
                    <Tag>
                      {resourceCategoryName(analytics.resource) ??
                        t("nonGeo.uncategorized")}
                    </Tag>
                    <Tag>
                      {resourceProvider(analytics.resource) ||
                        t("nonGeo.unrecordedOrganization")}
                    </Tag>
                  </div>
                </section>
                <MetricRing value={analytics.summary.completeness} />
                <section className="nongeo-mini-section">
                  <PanelTitle
                    icon={<TagsOutlined />}
                    title={t("nonGeo.fieldRoles")}
                  />
                  <div className="nongeo-role-grid">
                    <RoleCounter
                      label={t("nonGeo.roleMeasure")}
                      value={measureFields.length}
                    />
                    <RoleCounter
                      label={t("nonGeo.roleCategory")}
                      value={categoryFields.length}
                    />
                    <RoleCounter
                      label={t("nonGeo.roleText")}
                      value={analytics.summary.textFieldCount}
                    />
                  </div>
                </section>
                <section className="nongeo-mini-section">
                  <PanelTitle
                    icon={<ExperimentOutlined />}
                    title={t("nonGeo.dataInsights")}
                  />
                  <div className="nongeo-insight-list">
                    {analytics.insights.map((insight) => (
                      <div key={insight} className="nongeo-insight-item">
                        <span />
                        <Typography.Text>{insight}</Typography.Text>
                      </div>
                    ))}
                  </div>
                </section>
                <section className="nongeo-mini-section">
                  <PanelTitle
                    icon={<FieldTimeOutlined />}
                    title={t("nonGeo.fieldCompleteness")}
                  />
                  <FieldCompleteness fields={analytics.fields} />
                </section>
              </>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("nonGeo.fieldPortraitEmpty")}
              />
            )}
          </aside>
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
  lifeFormDistribution,
}: {
  analytics: NonGeoAnalytics | null;
  primaryCategory: CategoricalDistribution | null;
  secondaryCategory: CategoricalDistribution | null;
  primaryNumeric: NumericDistribution | null;
  lifeFormDistribution: CategoricalDistribution | null;
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
          icon={<BarChartOutlined />}
        >
          {primaryCategory ? (
            <HorizontalBarChart data={primaryCategory} />
          ) : (
            <ChartEmpty />
          )}
        </ChartBox>
        <ChartBox
          title={lifeFormDistribution?.label ?? t("nonGeo.compositionAnalysis")}
          icon={<DotChartOutlined />}
        >
          {lifeFormDistribution ? (
            <DonutChart data={lifeFormDistribution} />
          ) : (
            <ChartEmpty />
          )}
        </ChartBox>
        <ChartBox
          title={primaryNumeric?.label ?? t("nonGeo.numericDistribution")}
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
  numeric,
}: {
  analytics: NonGeoAnalytics | null;
  tableData: NonGeoTableQueryResult | null;
  numeric: NumericDistribution | null;
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
        <ScatterChart tableData={tableData} />
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
      <ChartBox
        title={numeric?.label ?? t("nonGeo.boxOverview")}
        icon={<LineChartOutlined />}
      >
        {numeric ? <BoxSummary data={numeric} /> : <ChartEmpty />}
      </ChartBox>
      <ChartBox title={t("nonGeo.keyFieldPortrait")} icon={<ProfileOutlined />}>
        <FieldSummary fields={analytics.fields} />
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
}: {
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
        {data.bins.map((bin, binIndex) => (
          <span
            key={`${data.field}-${bin.label}`}
            style={{
              height: `${Math.max((bin.count / max) * 100, 6)}%`,
              background: analyticsPalette[binIndex % analyticsPalette.length],
            }}
            title={`${bin.label}: ${bin.count}`}
          />
        ))}
      </div>
      <div className="nongeo-histogram-axis">
        <span>{formatNumber(data.min)}</span>
        <span>{formatNumber(data.mean)}</span>
        <span>{formatNumber(data.max)}</span>
      </div>
    </div>
  );
}

function BoxSummary({ data }: { data: NumericDistribution }) {
  const { t } = useTranslation();
  const range = data.max - data.min || 1;
  const q1 = ((data.q1 - data.min) / range) * 100;
  const q3 = ((data.q3 - data.min) / range) * 100;
  const median = ((data.median - data.min) / range) * 100;
  return (
    <div className="nongeo-box-summary">
      <div className="nongeo-box-line">
        <span style={{ left: `${q1}%`, width: `${Math.max(q3 - q1, 2)}%` }} />
        <i style={{ left: `${median}%` }} />
      </div>
      <div className="nongeo-box-values">
        <span>
          {t("nonGeo.minimumShort")} {formatNumber(data.min)}
        </span>
        <span>
          {t("nonGeo.meanShort")} {formatNumber(data.mean)}
        </span>
        <span>
          {t("nonGeo.maximumShort")} {formatNumber(data.max)}
        </span>
      </div>
    </div>
  );
}

function CorrelationHeatmap({
  data,
}: {
  data: NonGeoAnalytics["correlation"];
}) {
  if (!data) {
    return <ChartEmpty />;
  }
  return (
    <div
      className="nongeo-correlation"
      style={{
        gridTemplateColumns: `repeat(${data.fields.length}, minmax(24px, 1fr))`,
      }}
    >
      {data.fields.flatMap((rowField, rowIndex) =>
        data.fields.map((columnField, columnIndex) => {
          const value = data.values[rowIndex]?.[columnIndex] ?? 0;
          return (
            <span
              key={`${rowField}-${columnField}`}
              title={`${rowField} × ${columnField}: ${value.toFixed(2)}`}
              style={{ background: correlationColor(value) }}
            >
              {value.toFixed(1)}
            </span>
          );
        }),
      )}
    </div>
  );
}

function ScatterChart({
  tableData,
}: {
  tableData: NonGeoTableQueryResult | null;
}) {
  const { t } = useTranslation();
  const numericFields =
    tableData?.fields
      .filter((field) => /int|float|number|double/i.test(field.type))
      .slice(0, 2) ?? [];
  if (!tableData || numericFields.length < 2) {
    return <ChartEmpty />;
  }
  const xField = numericFields[0];
  const yField = numericFields[1];
  if (!xField || !yField) {
    return <ChartEmpty />;
  }
  const points = tableData.rows
    .map((row) => ({
      key: stableRowKey(row),
      x: toNumber(row[xField.name]),
      y: toNumber(row[yField.name]),
      label: valueLabel(
        row["种"] ??
          row["名称"] ??
          row.species_cn ??
          row.scientific_name ??
          row[xField.name],
      ),
    }))
    .filter(
      (point): point is { key: string; x: number; y: number; label: string } =>
        point.x !== null && point.y !== null,
    );
  if (points.length === 0) {
    return <ChartEmpty />;
  }
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;
  return (
    <div className="nongeo-scatter-wrap">
      <svg viewBox="0 0 320 190" aria-label={t("nonGeo.scatterLabel")}>
        <rect x="24" y="16" width="272" height="138" rx="8" />
        {points.map((point, pointIndex) => (
          <circle
            key={point.key}
            cx={24 + ((point.x - minX) / rangeX) * 272}
            cy={154 - ((point.y - minY) / rangeY) * 138}
            r={7}
            style={{
              fill: analyticsPalette[pointIndex % analyticsPalette.length],
            }}
          >
            <title>{point.label}</title>
          </circle>
        ))}
        <text x="24" y="178">
          {xField.name}
        </text>
        <text x="24" y="12">
          {yField.name}
        </text>
      </svg>
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

function MetricRing({ value }: { value: number }) {
  const { t } = useTranslation();
  return (
    <section className="nongeo-ring-card">
      <Progress
        type="circle"
        percent={Math.round(value * 100)}
        size={92}
        strokeColor="#16b8a9"
        railColor="rgba(32,91,84,0.12)"
      />
      <div>
        <Typography.Text strong>{t("nonGeo.dataCompleteness")}</Typography.Text>
        <small>{t("nonGeo.dataCompletenessDescription")}</small>
      </div>
    </section>
  );
}

function RoleCounter({ label, value }: { label: string; value: number }) {
  return (
    <div className="nongeo-role-counter">
      <strong>{value}</strong>
      <span>{label}</span>
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

function toNumber(value: string | number | boolean | null | undefined) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
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
  return `${Math.round(value * 100)}%`;
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
    return `rgba(40, 224, 194, ${alpha})`;
  }
  return `rgba(255, 111, 145, ${0.18 + Math.abs(normalized) * 0.72})`;
}
