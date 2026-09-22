import {
  EnvironmentOutlined,
  FilterOutlined,
  PlusOutlined,
  SearchOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  DatePicker,
  Descriptions,
  Empty,
  Input,
  Progress,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type {
  AttributeFilter,
  DataResourceProfile,
  ResourceFilters,
  ResourceListItem,
  User,
} from "../types";
import {
  resourceCategoryName,
  resourceFormatLabel,
  resourceProvider,
  resourceSpatialExtent,
} from "../utils/resources";

export interface DataResourceLoadProgress {
  percent: number;
  message: string;
}

export type DataResourceLoadReporter = (
  progress: DataResourceLoadProgress,
) => void;

interface Props {
  resources: ResourceListItem[];
  profile: DataResourceProfile | null;
  selectedResourceId: ResourceListItem["id"] | null;
  loadingResources?: boolean;
  loadingProfile: boolean;
  querying: boolean;
  permissions: User["permissions"];
  categoryOptions?: Array<{ value: string; label: string }>;
  selectedCategoryCode?: string | null;
  searchKeyword?: string;
  onFilterResources: (filters: ResourceFilters) => void;
  onSelectResource: (resource: ResourceListItem) => void;
  onQuickLoadResource: (
    resource: ResourceListItem,
    reportProgress: DataResourceLoadReporter,
  ) => Promise<void> | void;
  onQueryAndLoad: (filters: AttributeFilter[]) => void;
  onLoadRaster: (
    reportProgress: DataResourceLoadReporter,
  ) => Promise<void> | void;
}

const allDataFilterValue = "__all__";

export default function DataPanel({
  resources,
  profile,
  selectedResourceId,
  loadingResources = false,
  loadingProfile,
  querying,
  permissions,
  categoryOptions = [],
  selectedCategoryCode,
  searchKeyword,
  onFilterResources,
  onSelectResource,
  onQuickLoadResource,
  onQueryAndLoad,
  onLoadRaster,
}: Props) {
  const { t } = useTranslation();
  const [resourceFilters, setResourceFilters] = useState<ResourceFilters>({});
  const [attributeFilters, setAttributeFilters] = useState<AttributeFilter[]>(
    [],
  );
  const [field, setField] = useState<string>();
  const [operator, setOperator] =
    useState<AttributeFilter["operator"]>("contains");
  const [value, setValue] = useState("");
  const [valueTo, setValueTo] = useState("");
  const [resourceLoadProgress, setResourceLoadProgress] = useState(
    () => new Map<ResourceListItem["id"], DataResourceLoadProgress>(),
  );

  const categoryFilterOptions = useMemo(
    () => [
      { value: allDataFilterValue, label: t("map.allCategories") },
      ...categoryOptions,
    ],
    [categoryOptions, t],
  );
  const operatorOptions = useMemo(
    () => [
      { label: t("map.contains"), value: "contains" },
      { label: t("map.equals"), value: "eq" },
      { label: t("map.notEquals"), value: "ne" },
      { label: t("map.greaterThan"), value: "gt" },
      { label: t("map.greaterThanOrEqual"), value: "gte" },
      { label: t("map.lessThan"), value: "lt" },
      { label: t("map.lessThanOrEqual"), value: "lte" },
      { label: t("map.between"), value: "between" },
    ],
    [t],
  );

  const fieldOptions = (profile?.fields ?? []).map((item) => ({
    value: item.name,
    label: `${item.name} (${item.type})`,
  }));
  const selectedIsRaster = profile?.resource.dataType === "raster";
  const canQueryAndLoadVector =
    permissions.canQueryData && permissions.canLoadVectorLayer;

  useEffect(() => {
    const nextQuery = searchKeyword?.trim() || undefined;
    setResourceFilters((current) =>
      current.q === nextQuery
        ? current
        : withResourceFilterValue(current, "q", nextQuery),
    );
  }, [searchKeyword]);

  useEffect(() => {
    const nextCategoryCode = selectedCategoryCode ?? undefined;
    setResourceFilters((current) =>
      current.categoryCode === nextCategoryCode
        ? current
        : withResourceFilterValue(current, "categoryCode", nextCategoryCode),
    );
  }, [selectedCategoryCode]);

  function updateResourceFilter(
    key: keyof ResourceFilters,
    nextValue?: string,
  ) {
    setResourceFilters((current) =>
      withResourceFilterValue(current, key, nextValue),
    );
  }

  function updateAndFilterResources(
    key: keyof ResourceFilters,
    nextValue?: string,
  ) {
    const nextFilters = withResourceFilterValue(
      resourceFilters,
      key,
      nextValue,
    );
    setResourceFilters(nextFilters);
    onFilterResources(cleanResourceFilters(nextFilters));
  }

  function resourcePrimaryCategoryName(resource: ResourceListItem) {
    return (
      resource.categoryPath?.map((item) => item.name).join(" / ") ||
      resourceCategoryName(resource)
    );
  }

  function addAttributeFilter() {
    if (!field || !value.trim()) {
      return;
    }
    setAttributeFilters((current) => [
      ...current,
      {
        id: `${Date.now()}-${field}`,
        field,
        operator,
        value: value.trim(),
        valueTo: operator === "between" ? valueTo.trim() : undefined,
      },
    ]);
    setValue("");
    setValueTo("");
  }

  function removeAttributeFilter(id: string) {
    setAttributeFilters((current) => current.filter((item) => item.id !== id));
  }

  function reportResourceLoad(
    resourceId: ResourceListItem["id"],
    progress: DataResourceLoadProgress,
  ) {
    setResourceLoadProgress((current) => {
      const next = new Map(current);
      next.set(resourceId, {
        percent: Math.min(100, Math.max(0, progress.percent)),
        message: progress.message,
      });
      return next;
    });
  }

  async function runResourceLoad(
    resource: ResourceListItem,
    loader: (reportProgress: DataResourceLoadReporter) => Promise<void> | void,
  ) {
    reportResourceLoad(resource.id, {
      percent: 5,
      message: t("map.loadingResourceInfo"),
    });
    try {
      await loader((progress) => reportResourceLoad(resource.id, progress));
    } finally {
      setResourceLoadProgress((current) => {
        const next = new Map(current);
        next.delete(resource.id);
        return next;
      });
    }
  }

  async function quickLoadResource(resource: ResourceListItem) {
    await runResourceLoad(resource, (reportProgress) =>
      onQuickLoadResource(resource, reportProgress),
    );
  }

  async function loadSelectedRaster() {
    const resource = resources.find((item) => item.id === selectedResourceId);
    if (!resource) return;
    await runResourceLoad(resource, onLoadRaster);
  }

  return (
    <section className="panel-section data-panel">
      <div className="subsection-title">
        <SearchOutlined style={{ fontSize: 15 }} />
        <Typography.Text strong>{t("map.metadataFilter")}</Typography.Text>
      </div>
      <Space orientation="vertical" className="full-width compact-stack">
        <Input
          prefix={<SearchOutlined style={{ fontSize: 15 }} />}
          placeholder={t("map.resourceSearchPlaceholder")}
          value={resourceFilters.q}
          onChange={(event) => updateResourceFilter("q", event.target.value)}
          allowClear
        />
        <div className="data-filter-row">
          <Select
            placeholder={t("map.dataCategory")}
            value={resourceFilters.categoryCode ?? allDataFilterValue}
            allowClear
            options={categoryFilterOptions}
            onChange={(nextValue) => {
              updateAndFilterResources(
                "categoryCode",
                nextValue === allDataFilterValue ? undefined : nextValue,
              );
            }}
          />
          <Select
            placeholder={t("map.dataType")}
            value={resourceFilters.dataType}
            allowClear
            options={[
              { value: "vector", label: t("map.vectorData") },
              { value: "raster", label: t("map.rasterData") },
              { value: "table", label: t("map.tabularData") },
              { value: "document", label: t("map.documentData") },
              { value: "image", label: t("map.imageData") },
            ]}
            onChange={(nextValue) =>
              updateResourceFilter("dataType", nextValue)
            }
          />
        </div>
        <Input
          placeholder={t("map.dataSource")}
          value={resourceFilters.source}
          onChange={(event) =>
            updateResourceFilter("source", event.target.value)
          }
          allowClear
        />
        <DatePicker.RangePicker
          className="full-width"
          onChange={(_, dates) =>
            setResourceFilters((current) => ({
              ...current,
              dateFrom: dates[0] || undefined,
              dateTo: dates[1] || undefined,
            }))
          }
        />
        <Button
          type="primary"
          icon={<FilterOutlined style={{ fontSize: 15 }} />}
          onClick={() =>
            onFilterResources(cleanResourceFilters(resourceFilters))
          }
        >
          {t("map.filterData")}
        </Button>
      </Space>

      <div className="subsection-title">
        <UnorderedListOutlined style={{ fontSize: 15 }} />
        <Typography.Text strong>{t("map.dataResources")}</Typography.Text>
      </div>
      {resources.length > 0 ? (
        <ul className="resource-list" aria-label={t("map.dataResources")}>
          {resources.map((resource) => {
            const loadProgress = resourceLoadProgress.get(resource.id);
            return (
              <li
                key={resource.id}
                className={
                  resource.id === selectedResourceId
                    ? "resource-row resource-row-active"
                    : "resource-row"
                }
              >
                <div className="resource-row-content">
                  <Typography.Text strong className="resource-row-title">
                    {resource.name}
                    {!resource.isQueryable && !resource.isRenderable && (
                      <Tag>{t("common.metadataOnly")}</Tag>
                    )}
                    {resource.isRenderable && (
                      <Tag color="blue">{t("common.raster")}</Tag>
                    )}
                  </Typography.Text>
                  <Typography.Text
                    type="secondary"
                    className="resource-row-meta"
                  >
                    {resourcePrimaryCategoryName(resource) ??
                      t("common.uncategorized")}{" "}
                    · {resourceFormatLabel(resource)}
                  </Typography.Text>
                </div>
                <Button
                  size="small"
                  type={
                    resource.id === selectedResourceId ? "primary" : "default"
                  }
                  disabled={!resource.isQueryable && !resource.isRenderable}
                  onClick={() => onSelectResource(resource)}
                >
                  {t("common.select")}
                </Button>
                <Button
                  size="small"
                  type="primary"
                  ghost
                  className="resource-quick-load-button"
                  disabled={!resource.isQueryable && !resource.isRenderable}
                  loading={Boolean(loadProgress)}
                  onClick={() => void quickLoadResource(resource)}
                >
                  {t("map.quickLoad")}
                </Button>
                {loadProgress && (
                  <DataResourceLoadFeedback
                    resource={resource}
                    progress={loadProgress}
                  />
                )}
              </li>
            );
          })}
        </ul>
      ) : loadingResources ? (
        <div className="data-panel-loading" role="status">
          <Spin size="small" />
          <Typography.Text type="secondary">
            {t("map.syncingCatalog")}
          </Typography.Text>
        </div>
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("map.noResources")}
        />
      )}

      {profile && (
        <>
          <div className="subsection-title">
            <EnvironmentOutlined style={{ fontSize: 15 }} />
            <Typography.Text strong>
              {t("map.fieldsAndMetadata")}
            </Typography.Text>
          </div>
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label={t("map.dataSource")}>
              {profile.resource.source || "-"}
            </Descriptions.Item>
            <Descriptions.Item label={t("map.provider")}>
              {resourceProvider(profile.resource) || "-"}
            </Descriptions.Item>
            <Descriptions.Item label={t("map.spatialExtent")}>
              {resourceSpatialExtent(profile.resource) || "-"}
            </Descriptions.Item>
            <Descriptions.Item
              label={
                selectedIsRaster ? t("map.bandCount") : t("map.featureCount")
              }
            >
              {selectedIsRaster
                ? (profile.raster?.bandCount ?? "-")
                : (profile.featureCount ?? "-")}
            </Descriptions.Item>
            <Descriptions.Item
              label={
                selectedIsRaster ? t("map.rasterSize") : t("map.geometryType")
              }
            >
              {selectedIsRaster
                ? profile.raster?.metadata.size?.join(" x ") || "-"
                : profile.geometryType || "-"}
            </Descriptions.Item>
          </Descriptions>
          {loadingProfile ? (
            <Alert
              className="inline-alert"
              type="info"
              showIcon
              title={t("map.readingFields")}
            />
          ) : (
            <ul className="field-list" aria-label={t("map.fieldList")}>
              {profile.fields.map((item) => (
                <li className="field-row" key={item.name}>
                  <Typography.Text>{item.name}</Typography.Text>
                  <Typography.Text type="secondary">
                    {item.type}
                  </Typography.Text>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {!selectedIsRaster && (
        <>
          <div className="subsection-title">
            <PlusOutlined style={{ fontSize: 15 }} />
            <Typography.Text strong>{t("map.attributeQuery")}</Typography.Text>
          </div>
          <Space orientation="vertical" className="full-width compact-stack">
            <div className="attribute-filter-row">
              <Select
                placeholder={t("map.selectField")}
                value={field}
                options={fieldOptions}
                onChange={setField}
                disabled={!profile}
              />
              <Select
                value={operator}
                options={operatorOptions}
                onChange={setOperator}
              />
            </div>
            <Input
              placeholder={t("map.fieldValue")}
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
            {operator === "between" && (
              <Input
                placeholder={t("map.endValue")}
                value={valueTo}
                onChange={(event) => setValueTo(event.target.value)}
              />
            )}
            <div className="attribute-action-row">
              <Button
                icon={<PlusOutlined style={{ fontSize: 15 }} />}
                disabled={!field || !value.trim()}
                onClick={addAttributeFilter}
              >
                {t("map.addCondition")}
              </Button>
              {canQueryAndLoadVector && (
                <Button
                  type="primary"
                  loading={querying}
                  disabled={!profile}
                  onClick={() => onQueryAndLoad(attributeFilters)}
                >
                  {t("map.queryAndLoad")}
                </Button>
              )}
            </div>
          </Space>
          <Space wrap className="filter-tags">
            {attributeFilters.map((item) => (
              <Tag
                key={item.id}
                closable
                onClose={() => removeAttributeFilter(item.id)}
              >
                {item.field} {operatorLabel(item.operator, operatorOptions)}{" "}
                {item.value}
                {item.valueTo ? ` - ${item.valueTo}` : ""}
              </Tag>
            ))}
          </Space>
        </>
      )}

      {selectedIsRaster && permissions.canLoadRasterLayer && (
        <div className="query-footer">
          <Button
            type="primary"
            disabled={!profile?.raster}
            loading={
              selectedResourceId !== null &&
              resourceLoadProgress.has(selectedResourceId)
            }
            onClick={() => void loadSelectedRaster()}
          >
            {t("map.loadRaster")}
          </Button>
        </div>
      )}
    </section>
  );
}

function DataResourceLoadFeedback({
  resource,
  progress,
}: {
  resource: ResourceListItem;
  progress: DataResourceLoadProgress;
}) {
  const { t } = useTranslation();
  const percent = Math.round(progress.percent);
  return (
    <div
      className="data-resource-load-feedback"
      role="status"
      aria-live="polite"
      aria-label={t("map.loadProgress", { name: resource.name })}
    >
      <div className="data-resource-load-heading">
        <span>
          <Spin size="small" />
          {t("map.loadingToGlobe")}
        </span>
        <b>{percent}%</b>
      </div>
      <Progress percent={percent} size="small" showInfo={false} />
      <small>{progress.message}</small>
    </div>
  );
}

function withResourceFilterValue(
  filters: ResourceFilters,
  key: keyof ResourceFilters,
  nextValue?: string,
): ResourceFilters {
  const next = { ...filters };
  const keyName = key as string;
  if (nextValue?.trim()) {
    (next as Record<string, unknown>)[keyName] = nextValue;
  } else {
    delete (next as Record<string, unknown>)[keyName];
  }
  return next;
}

function cleanResourceFilters(filters: ResourceFilters): ResourceFilters {
  const next = { ...filters };
  Object.entries(next).forEach(([key, value]) => {
    if (
      value === undefined ||
      value === null ||
      (typeof value === "string" && !value.trim())
    ) {
      delete (next as Record<string, unknown>)[key];
    }
  });
  return next;
}

function operatorLabel(
  operator: AttributeFilter["operator"],
  operatorOptions: Array<{ label: string; value: string }>,
) {
  return (
    operatorOptions.find((item) => item.value === operator)?.label ?? operator
  );
}
