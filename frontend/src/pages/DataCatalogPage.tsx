import { ProjectLabel } from "../projects/ProjectLabel";
import { getActiveProject } from "../projects/session";
import {
  ApartmentOutlined,
  AppstoreOutlined,
  DatabaseOutlined,
  FileImageOutlined,
  EyeOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Layout,
  Segmented,
  Select,
  Space,
  Spin,
  Tag,
  Tree,
  Typography,
} from "antd";
import type { DataNode } from "antd/es/tree";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import WorkspaceHeader from "../components/WorkspaceHeader";
import { useComputeText } from "../compute/ui";
import { useAppContext } from "../contexts/AppContext";
import type {
  DataSchemaCatalogNode,
  DataSchemaSummary,
  ResourceFilters,
  ResourceListItem,
} from "../types";
import { findTaxonomyNode, taxonomyTree } from "../utils/taxonomy";
import { isComputeResult, resourceSourceLabel } from "../utils/resources";

type CatalogView = "cards" | "list";

export default function DataCatalogPage() {
  const { message } = App.useApp();
  const { t } = useTranslation();
  const computeUi = useComputeText();
  const { user } = useAppContext();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [schema, setSchema] = useState<DataSchemaSummary | null>(null);
  const [resources, setResources] = useState<ResourceListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<CatalogView>("cards");
  const [keyword, setKeyword] = useState(searchParams.get("q") ?? "");
  const [dataType, setDataType] = useState<ResourceFilters["dataType"]>();
  const [classificationStatus, setClassificationStatus] =
    useState<ResourceFilters["classificationStatus"]>();
  const [detailResource, setDetailResource] = useState<ResourceListItem | null>(
    null,
  );
  const resourceRequestSequenceRef = useRef(0);
  const canBrowseData =
    getActiveProject() === "1" || Boolean(user?.permissions.canBrowseData);
  const dataTypeLabels = useMemo<Record<ResourceListItem["dataType"], string>>(
    () => ({
      vector: t("common.vector"),
      raster: t("common.raster"),
      gene: t("catalog.geneOmics"),
      table: t("common.table"),
      document: t("common.document"),
      image: t("common.image"),
    }),
    [t],
  );
  const categoryCode = searchParams.get("categoryCode") ?? "";
  const tree = useMemo(() => taxonomyTree(schema), [schema]);
  const selectedNode = useMemo(
    () => findTaxonomyNode(tree, categoryCode),
    [categoryCode, tree],
  );

  const loadResources = useCallback(
    async (filters: ResourceFilters) => {
      const requestSequence = ++resourceRequestSequenceRef.current;
      if (!canBrowseData) {
        setResources([]);
        setLoading(false);
        return;
      }
      setLoading(true);
      try {
        const response = await api.resources(filters);
        if (requestSequence === resourceRequestSequenceRef.current) {
          setResources(response.items);
        }
      } catch (error) {
        if (requestSequence === resourceRequestSequenceRef.current) {
          message.error(
            error instanceof Error ? error.message : t("catalog.loadFailed"),
          );
        }
      } finally {
        if (requestSequence === resourceRequestSequenceRef.current) {
          setLoading(false);
        }
      }
    },
    [canBrowseData, message, t],
  );

  useEffect(() => {
    if (!canBrowseData) return;
    let ignore = false;
    api
      .dataSchemaSummary()
      .then((result) => {
        if (!ignore) setSchema(result);
      })
      .catch(() => {
        if (!ignore) setSchema(null);
      });
    return () => {
      ignore = true;
    };
  }, [canBrowseData]);

  useEffect(() => {
    void loadResources({
      ...(categoryCode ? { categoryCode } : {}),
      ...(searchParams.get("q")
        ? { q: searchParams.get("q") ?? undefined }
        : {}),
      ...(dataType ? { dataType } : {}),
      ...(classificationStatus ? { classificationStatus } : {}),
    });
  }, [
    categoryCode,
    classificationStatus,
    dataType,
    loadResources,
    searchParams,
  ]);

  function applySearch() {
    const next = new URLSearchParams(searchParams);
    if (keyword.trim()) next.set("q", keyword.trim());
    else next.delete("q");
    setSearchParams(next);
  }

  useEffect(() => {
    const id = Number(searchParams.get("resourceId"));
    if (id)
      setDetailResource(
        resources.find((resource) => resource.id === id) ?? null,
      );
  }, [resources, searchParams]);

  function selectCategory(code: string | null) {
    const next = new URLSearchParams(searchParams);
    if (code) next.set("categoryCode", code);
    else next.delete("categoryCode");
    setSearchParams(next);
  }

  function openResource(resource: ResourceListItem) {
    if (resource.availableViews.includes("map")) {
      const next = new URLSearchParams();
      if (resource.category?.code)
        next.set("categoryCode", resource.category.code);
      next.set("resourceQ", resource.name);
      navigate(`/map?${next.toString()}`);
      return;
    }
    if (
      resource.availableViews.includes("table") ||
      resource.availableViews.includes("gallery")
    ) {
      navigate(`/nongeo?resourceQ=${encodeURIComponent(resource.name)}`);
      return;
    }
    setDetailResource(resource);
  }

  return (
    <Layout className="data-catalog-shell">
      <WorkspaceHeader
        activeTab="resources"
        canBrowseData={canBrowseData}
        resources={resources}
        dataSchema={schema}
      />
      <main className="data-catalog-page">
        <section
          style={{ padding: "20px 24px", background: "#fff", borderRadius: 12 }}
        >
          <Typography.Title level={2}>数据资源目录</Typography.Title>
          <Typography.Paragraph>
            浏览当前项目的数据，按分类、数据类型和关键词筛选。共{" "}
            {resources.length} 项可见资源。
          </Typography.Paragraph>
        </section>

        {!canBrowseData && (
          <Alert
            type="warning"
            showIcon
            title={t("catalog.noBrowsePermission")}
          />
        )}

        <section id="public-data-catalog" className="data-catalog-toolbar">
          <Input.Search
            allowClear
            value={keyword}
            prefix={<SearchOutlined />}
            placeholder={t("catalog.searchPlaceholder")}
            onChange={(event) => setKeyword(event.target.value)}
            onSearch={applySearch}
          />
          <Select
            allowClear
            placeholder={t("catalog.physicalType")}
            value={dataType}
            options={Object.entries(dataTypeLabels).map(([value, label]) => ({
              value,
              label,
            }))}
            onChange={setDataType}
          />
          <Select
            allowClear
            placeholder={t("catalog.classificationStatus")}
            value={classificationStatus}
            options={[
              { value: "classified", label: t("catalog.classified") },
              { value: "pending", label: t("catalog.pending") },
            ]}
            onChange={setClassificationStatus}
          />
          <Segmented<CatalogView>
            value={view}
            onChange={setView}
            options={[
              {
                value: "cards",
                label: t("catalog.cards"),
                icon: <AppstoreOutlined />,
              },
              {
                value: "list",
                label: t("catalog.list"),
                icon: <DatabaseOutlined />,
              },
            ]}
          />
        </section>

        <div className="data-catalog-body">
          <aside className="data-catalog-taxonomy">
            <div className="data-catalog-section-title">
              <Typography.Text strong>{t("catalog.taxonomy")}</Typography.Text>
              <Button
                type="link"
                size="small"
                onClick={() => selectCategory(null)}
              >
                {t("common.all")}
              </Button>
            </div>
            <Tree
              blockNode
              defaultExpandAll
              selectedKeys={categoryCode ? [categoryCode] : []}
              treeData={taxonomyTreeData(tree)}
              onSelect={(keys) => selectCategory(String(keys[0] ?? "") || null)}
            />
            {selectedNode && (
              <Alert
                className="data-catalog-boundary"
                type="info"
                showIcon
                title={selectedNode.path.join(" / ")}
                description={selectedNode.description}
              />
            )}
          </aside>

          <section className="data-catalog-results">
            <Spin spinning={loading}>
              {resources.length ? (
                <div
                  className={
                    view === "cards"
                      ? "data-resource-grid"
                      : "data-resource-list"
                  }
                >
                  {resources.map((resource) => (
                    <ResourceCard
                      key={resource.id}
                      resource={resource}
                      compact={view === "list"}
                      onOpen={() => openResource(resource)}
                      onDetail={() => setDetailResource(resource)}
                      dataTypeLabel={dataTypeLabels[resource.dataType]}
                      t={t}
                    />
                  ))}
                </div>
              ) : (
                <Empty description={t("catalog.empty")} />
              )}
            </Spin>
          </section>
        </div>
      </main>

      <Drawer
        title={detailResource?.name ?? t("catalog.resourceDetails")}
        size="large"
        open={Boolean(detailResource)}
        onClose={() => {
          setDetailResource(null);
          const next = new URLSearchParams(searchParams);
          next.delete("resourceId");
          setSearchParams(next);
        }}
      >
        {detailResource && (
          <>
            <Space style={{ marginBottom: 20 }}>
              <Button onClick={() => openResource(detailResource)}>
                {computeUi(
                  "前往数据视图 / 地理工作台",
                  "Open data / map workspace",
                )}
              </Button>
              {["raster", "vector", "table"].includes(
                detailResource.dataType,
              ) &&
                user && (
                  <Button
                    type="primary"
                    onClick={() =>
                      navigate(`/compute?resourceId=${detailResource.id}`)
                    }
                  >
                    {computeUi("用于计算", "Use for computation")}
                  </Button>
                )}
            </Space>
            <ResourceDetails
              resource={detailResource}
              dataTypeLabel={dataTypeLabels[detailResource.dataType]}
              t={t}
            />
          </>
        )}
      </Drawer>
    </Layout>
  );
}

function ResourceCard({
  resource,
  compact,
  onOpen,
  onDetail,
  dataTypeLabel,
  t,
}: {
  resource: ResourceListItem;
  compact: boolean;
  onOpen: () => void;
  onDetail: () => void;
  dataTypeLabel: string;
  t: (key: string) => string;
}) {
  const ui = useComputeText();
  const primaryAction = resource.availableViews.includes("map")
    ? t("catalog.enterMap")
    : resource.availableViews.includes("table")
      ? t("catalog.viewTable")
      : resource.availableViews.includes("gallery")
        ? t("catalog.viewImage")
        : t("catalog.viewMetadata");
  return (
    <Card
      className={`data-resource-card${compact ? " data-resource-card-compact" : ""}`}
    >
      <Space orientation="vertical" size={10} className="full-width">
        <Space wrap>
          <Tag>{dataTypeLabel}</Tag>
          <Tag
            color={
              isComputeResult(resource)
                ? "blue"
                : resource.classificationStatus === "classified"
                  ? "green"
                  : "orange"
            }
          >
            {isComputeResult(resource)
              ? ui("计算结果", "Computation result")
              : resource.classificationStatus === "classified"
                ? t("catalog.classified")
                : t("catalog.pending")}
          </Tag>
        </Space>
        <Typography.Title level={4}>{resource.name}</Typography.Title>
        <ProjectLabel id={resource.projectTagId} />
        <Typography.Text
          className="data-resource-card-category"
          type="secondary"
        >
          {resource.categoryPath.length
            ? resource.categoryPath.map((item) => item.name).join(" / ")
            : t("catalog.noAuthoritativeCategory")}
        </Typography.Text>
        <Typography.Paragraph
          className="data-resource-card-description"
          ellipsis={{ rows: 2 }}
        >
          {catalogResourceSummary(resource, t("catalog.noDescription"), t, ui)}
        </Typography.Paragraph>
        <Space className="data-resource-card-actions" wrap>
          <Button type="primary" onClick={onOpen}>
            {primaryAction}
          </Button>
          <Button icon={<EyeOutlined />} onClick={onDetail}>
            {t("common.details")}
          </Button>
        </Space>
      </Space>
    </Card>
  );
}

function ResourceDetails({
  resource,
  dataTypeLabel,
  t,
}: {
  resource: ResourceListItem;
  dataTypeLabel: string;
  t: (key: string) => string;
}) {
  const ui = useComputeText();
  return (
    <Descriptions bordered size="small" column={1}>
      <Descriptions.Item label={t("catalog.businessCategory")}>
        {resource.categoryPath.map((item) => item.name).join(" / ") ||
          t("catalog.pending")}
      </Descriptions.Item>
      <Descriptions.Item label={t("catalog.physicalType")}>
        {dataTypeLabel}
      </Descriptions.Item>
      <Descriptions.Item label={t("catalog.availableViews")}>
        <Space wrap>
          {resource.availableViews.map((view) => (
            <Tag key={view}>{resourceViewLabel(view, t)}</Tag>
          ))}
        </Space>
      </Descriptions.Item>
      <Descriptions.Item label={t("common.source")}>
        {resourceSourceLabel(
          resource,
          ui("平台算法计算", "Platform algorithm computation"),
        ) || t("catalog.notRecorded")}
      </Descriptions.Item>
      <Descriptions.Item label={t("map.provider")}>
        {resource.provider || t("catalog.notRecorded")}
      </Descriptions.Item>
      <Descriptions.Item label={t("catalog.coordinateSystem")}>
        {resource.coordinateSystem || t("catalog.notApplicable")}
      </Descriptions.Item>
      <Descriptions.Item label={t("map.spatialExtent")}>
        {resource.spatialExtent || t("catalog.notApplicable")}
      </Descriptions.Item>
      <Descriptions.Item label={t("common.description")}>
        {catalogResourceSummary(resource, t("catalog.notRecorded"), t, ui)}
      </Descriptions.Item>
    </Descriptions>
  );
}

function catalogResourceSummary(
  resource: ResourceListItem,
  fallback: string,
  t: (key: string) => string,
  ui: (zh: string, en: string) => string,
) {
  if (isComputeResult(resource)) {
    return ui(
      "已入库的算法输出，可查看结果或继续用于计算。",
      "Stored algorithm output, ready to view or use in further computation.",
    );
  }
  const summary = (resource.description || resource.source).trim();
  if (!summary) return fallback;
  if (/^由 Excel\/CSV 导入的地理表[：:]\s*import_data_/i.test(summary)) {
    return t("catalog.geographicImport");
  }
  if (/^由 Excel\/CSV 导入的非地理表[：:]\s*import_data_/i.test(summary)) {
    return t("catalog.nonGeographicImport");
  }
  if (/^自动扫描统一.*GeoPackage 图层[：:]/i.test(summary)) {
    return t("catalog.geopackageScan");
  }
  return summary;
}

function resourceViewLabel(
  view: ResourceListItem["availableViews"][number],
  t: (key: string) => string,
) {
  const labels = {
    map: t("catalog.mapView"),
    table: t("common.table"),
    gallery: t("catalog.galleryView"),
    metadata: t("catalog.metadataView"),
  };
  return labels[view];
}

function taxonomyTreeData(nodes: DataSchemaCatalogNode[]): DataNode[] {
  return nodes.map((node) => ({
    key: node.categoryCode,
    title: (
      <Space size={6}>
        {node.code === "compute_results" ? (
          <DatabaseOutlined />
        ) : node.code === "distribution" ? (
          <FileImageOutlined />
        ) : (
          <ApartmentOutlined />
        )}
        <span>{node.name}</span>
      </Space>
    ),
    children: taxonomyTreeData(node.children),
  }));
}
