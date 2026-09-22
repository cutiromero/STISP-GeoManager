import { ProjectNotice, ProjectLabel } from "../projects/ProjectLabel";
import {
  EyeOutlined,
  FileOutlined,
  FileImageOutlined,
  GlobalOutlined,
  ReloadOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { ProCard, StatisticCard } from "@ant-design/pro-components";
import {
  Alert,
  App as AntApp,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tabs,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAppContext } from "../contexts/AppContext";
import { localText, useEnglishLanguage } from "../i18n/useEnglishLanguage";
import type {
  MapComposition,
  ResultArtifact,
  WorkspaceAccessGroup,
} from "../types";
import { downloadBlob } from "../utils/download";
import {
  isWorkspaceInventoryChange,
  notifyWorkspaceInventoryChanged,
  workspaceInventoryChangedEvent,
} from "../workspace/workspaceSync";

const statusLabels: Record<
  MapComposition["status"],
  { text: string; color: string }
> = {
  draft: { text: "草稿", color: "default" },
  completed: { text: "未发布", color: "blue" },
  published: { text: "已发布", color: "green" },
};

type StatusFilter = "all" | MapComposition["status"];

const resultStatusLabels = {
  draft: { text: "已下架/历史草稿", color: "default" },
  published: { text: "已发布", color: "green" },
} satisfies Record<ResultArtifact["status"], { text: string; color: string }>;

const resultTypeLabels: Record<ResultArtifact["resultType"], string> = {
  map: "地图",
  chart: "图表",
  report: "报告",
  table: "表格",
  image: "图片",
  other: "其他",
};

export default function AdminTopicCompositionManagementPage() {
  const { message } = AntApp.useApp();
  const english = useEnglishLanguage();
  const l = (zh: string, en: string) => localText(english, zh, en);
  const statusText = (value: MapComposition["status"]) =>
    english
      ? { draft: "Draft", completed: "Unpublished", published: "Published" }[
          value
        ]
      : statusLabels[value].text;
  const resultStatusText = (value: ResultArtifact["status"]) =>
    english
      ? value === "published"
        ? "Published"
        : "Unpublished / historical draft"
      : resultStatusLabels[value].text;
  const resultTypeText = (value: ResultArtifact["resultType"]) =>
    english
      ? {
          map: "Map",
          chart: "Chart",
          report: "Report",
          table: "Table",
          image: "Image",
          other: "Other",
        }[value]
      : resultTypeLabels[value];
  const [publishForm] = Form.useForm<{
    versionNumber?: number;
    audienceGroupIds: number[];
  }>();
  const navigate = useNavigate();
  const { user } = useAppContext();
  const [items, setItems] = useState<MapComposition[]>([]);
  const [resultItems, setResultItems] = useState<ResultArtifact[]>([]);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [previewUrl, setPreviewUrl] = useState("");
  const [previewTitle, setPreviewTitle] = useState("");
  const [previewFormat, setPreviewFormat] = useState("");
  const [previewingKey, setPreviewingKey] = useState<string | null>(null);
  const [, setAvailableAudienceGroups] = useState<WorkspaceAccessGroup[]>([]);
  const [publishingComposition, setPublishingComposition] =
    useState<MapComposition | null>(null);
  const [publishingArtifact, setPublishingArtifact] =
    useState<ResultArtifact | null>(null);
  const [publishing, setPublishing] = useState(false);
  const canManageCompositions = Boolean(
    user?.permissions.canViewMapCompositions ||
    user?.permissions.canChangeMapCompositions ||
    user?.permissions.canDeleteMapCompositions ||
    user?.permissions.canPublishMapCompositions,
  );
  const canManageArtifacts = Boolean(user?.permissions.canViewResultArtifacts);
  const canOpen = canManageCompositions || canManageArtifacts;
  const loadItems = useCallback(async () => {
    if (!canOpen) {
      setItems([]);
      return;
    }
    setLoading(true);
    const [compositionResponse, artifactResponse] = await Promise.allSettled([
      canManageCompositions
        ? api.mapCompositions()
        : Promise.resolve({ items: [], availableAudienceGroups: [] }),
      canManageArtifacts
        ? api.resultArtifacts()
        : Promise.resolve({ items: [], availableAccessGroups: [] }),
    ]);
    if (compositionResponse.status === "fulfilled") {
      setItems(compositionResponse.value.items);
    } else {
      setItems([]);
      message.error(
        l("专题图成果加载失败", "Failed to load thematic-map results"),
      );
    }
    if (artifactResponse.status === "fulfilled") {
      setResultItems(artifactResponse.value.items);
    } else {
      setResultItems([]);
      message.error(l("导入成果加载失败", "Failed to load imported results"));
    }
    const compositionGroups =
      compositionResponse.status === "fulfilled"
        ? compositionResponse.value.availableAudienceGroups
        : [];
    const artifactGroups =
      artifactResponse.status === "fulfilled"
        ? artifactResponse.value.availableAccessGroups
        : [];
    setAvailableAudienceGroups(
      [...compositionGroups, ...artifactGroups].filter(
        (group, groupIndex, groups) =>
          groups.findIndex((candidate) => candidate.id === group.id) ===
          groupIndex,
      ),
    );
    setLoading(false);
  }, [canManageArtifacts, canManageCompositions, canOpen, english, message]);

  useEffect(() => {
    void loadItems();
  }, [loadItems]);

  useEffect(() => {
    function refreshFromEvent(event: Event) {
      const detail = event instanceof CustomEvent ? event.detail : undefined;
      if (isWorkspaceInventoryChange(detail)) {
        void loadItems();
      }
    }
    function refreshFromStorage(event: StorageEvent) {
      if (event.key !== workspaceInventoryChangedEvent || !event.newValue) {
        return;
      }
      try {
        if (isWorkspaceInventoryChange(JSON.parse(event.newValue))) {
          void loadItems();
        }
      } catch {
        return;
      }
    }
    function refreshOnFocus() {
      if (document.visibilityState === "visible") {
        void loadItems();
      }
    }
    window.addEventListener(workspaceInventoryChangedEvent, refreshFromEvent);
    window.addEventListener("storage", refreshFromStorage);
    window.addEventListener("focus", refreshOnFocus);
    document.addEventListener("visibilitychange", refreshOnFocus);
    return () => {
      window.removeEventListener(
        workspaceInventoryChangedEvent,
        refreshFromEvent,
      );
      window.removeEventListener("storage", refreshFromStorage);
      window.removeEventListener("focus", refreshOnFocus);
      document.removeEventListener("visibilitychange", refreshOnFocus);
    };
  }, [loadItems]);

  useEffect(
    () => () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl],
  );

  const filteredItems = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase("zh-CN");
    return items.filter((item) => {
      const statusMatched = status === "all" || item.status === status;
      if (!statusMatched) return false;
      if (!keyword) return true;
      return [
        item.name,
        item.description,
        item.projectName,
        item.owner.displayName,
        item.owner.username,
      ].some((value) =>
        (value ?? "").toLocaleLowerCase("zh-CN").includes(keyword),
      );
    });
  }, [items, query, status]);

  const filteredResultItems = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase("zh-CN");
    return resultItems.filter((item) => {
      if (status !== "all" && item.status !== status) return false;
      if (!keyword) return true;
      return [
        item.name,
        item.description,
        item.provider,
        item.fileName,
        item.owner.displayName,
        item.owner.username,
      ].some((value) =>
        (value ?? "").toLocaleLowerCase("zh-CN").includes(keyword),
      );
    });
  }, [query, resultItems, status]);

  const metrics = useMemo(
    () => ({
      total: items.length + resultItems.length,
      mapping: items.length,
      imported: resultItems.length,
      published:
        items.filter((item) => item.status === "published").length +
        resultItems.filter((item) => item.status === "published").length,
    }),
    [items, resultItems],
  );

  if (!canOpen) {
    return <Navigate to="/admin/profile" replace />;
  }

  async function preview(composition: MapComposition) {
    if (!composition.currentVersion) {
      message.warning(
        l(
          "该专题暂无可预览成果",
          "This thematic map has no previewable result",
        ),
      );
      return;
    }
    const key = `mapping-${composition.id}`;
    setPreviewingKey(key);
    try {
      const result = await withPreviewTimeout(
        api.downloadMapCompositionVersion(
          composition.id,
          composition.currentVersion.versionNumber,
          "preview",
        ),
      );
      const nextUrl = URL.createObjectURL(result.blob);
      setPreviewUrl((current) => {
        if (current) URL.revokeObjectURL(current);
        return nextUrl;
      });
      setPreviewTitle(
        `${composition.name} V${composition.currentVersion.versionNumber}`,
      );
      setPreviewFormat("png");
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("专题预览失败", "Thematic-map preview failed"),
      );
    } finally {
      setPreviewingKey((current) => (current === key ? null : current));
    }
  }

  async function download(composition: MapComposition) {
    if (!composition.currentVersion) {
      message.warning(
        l(
          "该专题暂无可下载成果",
          "This thematic map has no downloadable result",
        ),
      );
      return;
    }
    try {
      const result = await api.downloadMapCompositionVersion(
        composition.id,
        composition.currentVersion.versionNumber,
      );
      downloadBlob(result.blob, result.filename);
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("专题下载失败", "Thematic-map download failed"),
      );
    }
  }

  async function unpublish(composition: MapComposition) {
    try {
      const result = await api.unpublishMapComposition(composition.id);
      setItems((current) =>
        current.map((item) => (item.id === result.id ? result : item)),
      );
      notifyWorkspaceInventoryChanged("composition");
      message.success(l("专题已下架", "Thematic map unpublished"));
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("专题下架失败", "Failed to unpublish thematic map"),
      );
    }
  }

  function openPublish(composition: MapComposition) {
    const versionNumber =
      composition.publishedVersion?.versionNumber ??
      composition.currentVersion?.versionNumber;
    if (!versionNumber) {
      message.warning(
        l(
          "该专题尚未生成成果版本",
          "No result version has been generated for this thematic map",
        ),
      );
      return;
    }
    setPublishingArtifact(null);
    setPublishingComposition(composition);
    publishForm.setFieldsValue({
      versionNumber,
      audienceGroupIds: composition.audienceGroups.map((group) => group.id),
    });
  }

  async function submitPublish() {
    if (!publishingComposition && !publishingArtifact) return;
    const values = await publishForm.validateFields();
    setPublishing(true);
    try {
      if (publishingComposition) {
        const result = await api.publishMapComposition(
          publishingComposition.id,
          {
            versionNumber: values.versionNumber!,
            audienceGroupIds: publishingComposition.audienceGroups.map(
              (group) => group.id,
            ),
          },
        );
        setItems((current) =>
          current.map((item) => (item.id === result.id ? result : item)),
        );
        notifyWorkspaceInventoryChanged("composition");
      } else if (publishingArtifact) {
        const result = await api.updateResultArtifact(publishingArtifact.id, {
          action: "publish",
          accessGroupIds: publishingArtifact.accessGroups.map(
            (group) => group.id,
          ),
        });
        if (!("deleted" in result)) {
          setResultItems((current) =>
            current.map((item) => (item.id === result.id ? result : item)),
          );
        }
        notifyWorkspaceInventoryChanged("result");
      }
      setPublishingComposition(null);
      setPublishingArtifact(null);
      message.success(l("成果已发布", "Result published"));
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("专题发布失败", "Failed to publish result"),
      );
    } finally {
      setPublishing(false);
    }
  }

  async function deleteComposition(composition: MapComposition) {
    try {
      await api.deleteMapComposition(composition.id);
      setItems((current) =>
        current.filter((item) => item.id !== composition.id),
      );
      notifyWorkspaceInventoryChanged("composition");
      message.success(l("专题已删除", "Thematic map deleted"));
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("专题删除失败", "Failed to delete thematic map"),
      );
    }
  }

  async function previewArtifact(artifact: ResultArtifact) {
    if (!artifact.canPreview) {
      message.warning(
        l(
          "该成果格式不支持在线预览",
          "This result format cannot be previewed online",
        ),
      );
      return;
    }
    const key = `artifact-${artifact.id}`;
    setPreviewingKey(key);
    try {
      const result = await withPreviewTimeout(
        api.downloadResultArtifact(artifact.id, "preview"),
      );
      const nextUrl = URL.createObjectURL(result.blob);
      setPreviewUrl((current) => {
        if (current) URL.revokeObjectURL(current);
        return nextUrl;
      });
      setPreviewTitle(artifact.name);
      setPreviewFormat(artifact.fileFormat);
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("成果预览失败", "Result preview failed"),
      );
    } finally {
      setPreviewingKey((current) => (current === key ? null : current));
    }
  }

  async function downloadArtifact(artifact: ResultArtifact) {
    try {
      const result = await api.downloadResultArtifact(artifact.id);
      downloadBlob(result.blob, result.filename);
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("成果下载失败", "Result download failed"),
      );
    }
  }

  function openArtifactPublish(artifact: ResultArtifact) {
    setPublishingComposition(null);
    setPublishingArtifact(artifact);
    publishForm.setFieldsValue({
      versionNumber: undefined,
      audienceGroupIds: artifact.accessGroups.map((group) => group.id),
    });
  }

  async function unpublishArtifact(artifact: ResultArtifact) {
    try {
      const result = await api.updateResultArtifact(artifact.id, {
        action: "unpublish",
      });
      if (!("deleted" in result)) {
        setResultItems((current) =>
          current.map((item) => (item.id === result.id ? result : item)),
        );
      }
      notifyWorkspaceInventoryChanged("result");
      message.success(l("成果已下架", "Result unpublished"));
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("成果下架失败", "Failed to unpublish result"),
      );
    }
  }

  async function deleteArtifact(artifact: ResultArtifact) {
    try {
      await api.updateResultArtifact(artifact.id, { action: "delete" });
      setResultItems((current) =>
        current.filter((item) => item.id !== artifact.id),
      );
      notifyWorkspaceInventoryChanged("result");
      message.success(l("成果文件已删除", "Result file deleted"));
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("成果删除失败", "Failed to delete result"),
      );
    }
  }

  const columns: ColumnsType<MapComposition> = [
    {
      title: l("专题名称", "Thematic-map name"),
      dataIndex: "name",
      key: "name",
      width: 260,
      render: (_, record) => (
        <Space orientation="vertical" size={2}>
          <Typography.Text strong>{record.name}</Typography.Text>
          <ProjectLabel id={record.projectTagId} />
          <Typography.Text type="secondary" className="admin-table-subtext">
            {l("来源工程：", "Source project: ")}
            {record.projectName}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: l("类型", "Type"),
      key: "type",
      width: 96,
      render: () => <Tag>{l("专题出图", "Thematic map")}</Tag>,
    },
    {
      title: l("状态", "Status"),
      dataIndex: "status",
      key: "status",
      width: 112,
      render: (value: MapComposition["status"]) => (
        <Tag color={statusLabels[value].color}>{statusText(value)}</Tag>
      ),
    },
    {
      title: l("所属用户", "Owner"),
      key: "owner",
      width: 160,
      render: (_, record) => (
        <Space orientation="vertical" size={0}>
          <span>{record.owner.displayName || record.owner.username}</span>
          <Typography.Text type="secondary" className="admin-table-subtext">
            {record.owner.username}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: l("成果版本", "Result version"),
      key: "version",
      width: 112,
      render: (_, record) =>
        record.currentVersion
          ? `V${record.currentVersion.versionNumber}`
          : l("未生成", "Not generated"),
    },
    {
      title: l("更新时间", "Updated at"),
      dataIndex: "updatedAt",
      key: "updatedAt",
      width: 190,
      render: (value: string) =>
        new Date(value).toLocaleString(english ? "en-US" : "zh-CN"),
    },
    {
      title: l("操作", "Actions"),
      key: "actions",
      width: 360,
      render: (_, record) => (
        <Space wrap>
          <Button
            type="link"
            icon={<GlobalOutlined />}
            onClick={() => navigate(`/map?sceneId=${record.projectId}`)}
          >
            {l("打开工程", "Open project")}
          </Button>
          <Button
            type="link"
            icon={<EyeOutlined />}
            loading={previewingKey === `mapping-${record.id}`}
            disabled={!record.canPreview || !record.currentVersion}
            onClick={() => void preview(record)}
          >
            {l("预览", "Preview")}
          </Button>
          <Button
            type="link"
            disabled={!record.canDownload || !record.currentVersion}
            onClick={() => void download(record)}
          >
            {l("下载", "Download")}
          </Button>
          <Button
            type="link"
            disabled={!record.canPublish}
            onClick={() => openPublish(record)}
          >
            {record.status === "published"
              ? l("更新发布", "Update publication")
              : l("发布", "Publish")}
          </Button>
          {record.canUnpublish ? (
            <Button type="link" onClick={() => void unpublish(record)}>
              {l("下架", "Unpublish")}
            </Button>
          ) : null}
          <Popconfirm
            title={l("删除专题", "Delete thematic map")}
            description={l(
              `确认删除“${record.name}”？专题、全部版本记录和成果文件将被永久删除且不可恢复。`,
              `Delete “${record.name}”? The thematic map, all version records, and result files will be permanently deleted.`,
            )}
            okText={l("删除", "Delete")}
            cancelText={l("取消", "Cancel")}
            okButtonProps={{ danger: true }}
            disabled={!record.canDelete}
            onConfirm={() => void deleteComposition(record)}
          >
            <Button type="link" danger disabled={!record.canDelete}>
              {l("删除", "Delete")}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const resultColumns: ColumnsType<ResultArtifact> = [
    {
      title: l("成果名称", "Result name"),
      dataIndex: "name",
      key: "name",
      width: 280,
      render: (_, record) => (
        <Space orientation="vertical" size={2}>
          <Typography.Text strong>{record.name}</Typography.Text>
          <ProjectLabel id={record.projectTagId} />
          <Typography.Text type="secondary" className="admin-table-subtext">
            {record.provider || record.fileName}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: l("来源 / 类型", "Source / type"),
      key: "type",
      width: 190,
      render: (_, record) => (
        <Space wrap size={4}>
          <Tag color={record.sourceType === "analysis" ? "blue" : "gold"}>
            {record.sourceType === "analysis"
              ? l("平台分析", "Platform analysis")
              : l("直接导入", "Direct import")}
          </Tag>
          <Tag>{resultTypeText(record.resultType)}</Tag>
        </Space>
      ),
    },
    {
      title: l("状态", "Status"),
      dataIndex: "status",
      key: "status",
      width: 140,
      render: (value: ResultArtifact["status"]) => (
        <Tag color={resultStatusLabels[value].color}>
          {resultStatusText(value)}
        </Tag>
      ),
    },
    {
      title: l("创建者", "Creator"),
      key: "owner",
      width: 160,
      render: (_, record) =>
        record.owner.displayName ||
        record.owner.username ||
        l("系统维护", "System maintenance"),
    },
    {
      title: l("文件", "File"),
      key: "file",
      width: 140,
      render: (_, record) => (
        <Space orientation="vertical" size={0}>
          <Typography.Text>{record.fileFormat.toUpperCase()}</Typography.Text>
          <Typography.Text type="secondary">
            {formatFileSize(record.sizeBytes)}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: l("更新时间", "Updated at"),
      dataIndex: "updatedAt",
      key: "updatedAt",
      width: 190,
      render: (value: string) =>
        new Date(value).toLocaleString(english ? "en-US" : "zh-CN"),
    },
    {
      title: l("操作", "Actions"),
      key: "actions",
      width: 340,
      render: (_, record) => (
        <Space wrap>
          <Button
            type="link"
            icon={<EyeOutlined />}
            loading={previewingKey === `artifact-${record.id}`}
            disabled={!record.canPreview}
            onClick={() => void previewArtifact(record)}
          >
            {l("预览", "Preview")}
          </Button>
          <Button
            type="link"
            disabled={!record.canDownload}
            onClick={() => void downloadArtifact(record)}
          >
            {l("下载", "Download")}
          </Button>
          <Button
            type="link"
            disabled={!record.canPublish}
            onClick={() => openArtifactPublish(record)}
          >
            {record.status === "published"
              ? l("更新范围", "Update audience")
              : l("发布", "Publish")}
          </Button>
          {record.canUnpublish ? (
            <Button type="link" onClick={() => void unpublishArtifact(record)}>
              {l("下架", "Unpublish")}
            </Button>
          ) : null}
          <Popconfirm
            title={l("删除成果文件", "Delete result file")}
            description={l(
              `确认删除“${record.name}”？成果记录和文件将被永久删除且不可恢复。`,
              `Delete “${record.name}”? The result record and file will be permanently deleted.`,
            )}
            okText={l("删除", "Delete")}
            cancelText={l("取消", "Cancel")}
            okButtonProps={{ danger: true }}
            disabled={!record.canDelete}
            onConfirm={() => void deleteArtifact(record)}
          >
            <Button type="link" danger disabled={!record.canDelete}>
              {l("删除", "Delete")}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className="admin-page-stack admin-inventory-page">
      <ProCard className="admin-section-card">
        <Alert
          showIcon
          type="info"
          title={l("统一成果管理", "Unified result management")}
          description={l(
            "专题图成果沿用制图查看、导出和发布权限；导入成果使用独立的查看、导入、下载、发布和删除权限。对象所属用户只能执行已获授权操作，平台管理主体可管理全部成果。",
            "Thematic-map results use map-composition view, export, and publish permissions. Imported results use separate view, import, download, publish, and delete permissions. Owners may perform only authorized actions; platform administrators can manage all results.",
          )}
          style={{ marginBottom: 16 }}
        />
        <Form layout="vertical">
          <div className="inventory-toolbar">
            <Form.Item className="inventory-search-item">
              <Input
                allowClear
                value={query}
                placeholder={l(
                  "按成果名称、来源工程、文件、单位或创建者快速搜索",
                  "Search by result name, source project, file, provider, or creator",
                )}
                onChange={(event) => setQuery(event.target.value)}
              />
            </Form.Item>
            <Space wrap>
              <Select<StatusFilter>
                value={status}
                style={{ width: 144 }}
                onChange={setStatus}
                options={[
                  { value: "all", label: l("全部状态", "All statuses") },
                  {
                    value: "draft",
                    label: l("草稿 / 已下架", "Draft / unpublished"),
                  },
                  { value: "completed", label: l("未发布", "Unpublished") },
                  { value: "published", label: l("已发布", "Published") },
                ]}
              />
              <Button
                icon={<ReloadOutlined />}
                loading={loading}
                onClick={() => void loadItems()}
              >
                {l("刷新", "Refresh")}
              </Button>
            </Space>
          </div>
        </Form>
      </ProCard>

      <StatisticCard.Group className="inventory-stat-group">
        <StatisticCard
          statistic={{
            title: l("全部成果", "All results"),
            value: metrics.total,
            prefix: <FileOutlined />,
          }}
        />
        <StatisticCard
          statistic={{
            title: l("专题图成果", "Thematic-map results"),
            value: metrics.mapping,
            prefix: <FileImageOutlined />,
          }}
        />
        <StatisticCard
          statistic={{
            title: l("导入成果", "Imported results"),
            value: metrics.imported,
            prefix: <UploadOutlined />,
          }}
        />
        <StatisticCard
          statistic={{
            title: l("已发布", "Published"),
            value: metrics.published,
          }}
        />
      </StatisticCard.Group>

      <ProCard className="admin-section-card inventory-table-card">
        <Tabs
          items={[
            ...(canManageCompositions
              ? [
                  {
                    key: "mapping",
                    label: l(
                      `专题图成果（${filteredItems.length}）`,
                      `Thematic-map results (${filteredItems.length})`,
                    ),
                    children: (
                      <div className="inventory-table-scroll">
                        <Table<MapComposition>
                          rowKey="id"
                          loading={loading}
                          columns={columns}
                          dataSource={filteredItems}
                          scroll={{ x: 1280 }}
                          pagination={{
                            pageSize: 10,
                            showSizeChanger: true,
                            showTotal: (total) =>
                              l(`共 ${total} 条`, `${total} items`),
                          }}
                          locale={{
                            emptyText: (
                              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
                            ),
                          }}
                        />
                      </div>
                    ),
                  },
                ]
              : []),
            ...(canManageArtifacts
              ? [
                  {
                    key: "artifacts",
                    label: l(
                      `导入成果（${filteredResultItems.length}）`,
                      `Imported results (${filteredResultItems.length})`,
                    ),
                    children: (
                      <div className="inventory-table-scroll">
                        <Table<ResultArtifact>
                          rowKey="id"
                          loading={loading}
                          columns={resultColumns}
                          dataSource={filteredResultItems}
                          scroll={{ x: 1440 }}
                          pagination={{
                            pageSize: 10,
                            showSizeChanger: true,
                            showTotal: (total) =>
                              l(`共 ${total} 条`, `${total} items`),
                          }}
                          locale={{
                            emptyText: (
                              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
                            ),
                          }}
                        />
                      </div>
                    ),
                  },
                ]
              : []),
          ]}
        />
      </ProCard>

      <Modal
        title={previewTitle}
        open={Boolean(previewUrl)}
        footer={null}
        width="min(1000px, 92vw)"
        onCancel={() => setPreviewUrl("")}
      >
        {previewUrl && previewFormat === "pdf" ? (
          <iframe
            className="result-pdf-preview"
            src={previewUrl}
            title={previewTitle}
          />
        ) : previewUrl ? (
          <img
            className="map-composition-preview-image"
            src={previewUrl}
            alt={previewTitle}
          />
        ) : null}
      </Modal>
      <Modal
        title={
          publishingArtifact
            ? l("发布导入成果", "Publish imported result")
            : l("发布专题图成果", "Publish thematic-map result")
        }
        open={Boolean(publishingComposition || publishingArtifact)}
        okText={l("确认发布", "Confirm publish")}
        confirmLoading={publishing}
        onOk={() => void submitPublish()}
        onCancel={() => {
          setPublishingComposition(null);
          setPublishingArtifact(null);
        }}
        destroyOnHidden
      >
        <Form form={publishForm} layout="vertical">
          {publishingComposition ? (
            <Form.Item
              name="versionNumber"
              label={l("正式发布版本", "Version to publish")}
              rules={[
                {
                  required: true,
                  message: l("请选择发布版本", "Select a version to publish"),
                },
              ]}
            >
              <Select
                options={publishingComposition.versions.map((version) => ({
                  value: version.versionNumber,
                  label: `V${version.versionNumber} · ${version.format.toUpperCase()}`,
                }))}
              />
            </Form.Item>
          ) : null}
          <ProjectNotice />
        </Form>
      </Modal>
    </div>
  );
}

function withPreviewTimeout<T>(request: Promise<T>, timeoutMs = 20_000) {
  let timeoutId: number | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timeoutId = window.setTimeout(
      () => reject(new Error("成果预览等待超时，请稍后重试")),
      timeoutMs,
    );
  });
  return Promise.race([request, timeout]).finally(() => {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId);
  });
}

function formatFileSize(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
