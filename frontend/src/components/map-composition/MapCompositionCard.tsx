import {
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  EyeOutlined,
  FolderOpenOutlined,
  RollbackOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { Button, Popconfirm, Space, Tag, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import type { MapComposition } from "../../types";

interface Props {
  composition: MapComposition;
  onPreview: () => void;
  onOpen: () => void;
  onDownload: () => void;
  onPublish: () => void;
  onUnpublish: () => void;
  onRestore: () => void;
  onLoadSource: () => void;
  onDelete: () => void;
}

export default function MapCompositionCard({
  composition,
  onPreview,
  onOpen,
  onDownload,
  onPublish,
  onUnpublish,
  onRestore,
  onLoadSource,
  onDelete,
}: Props) {
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const previewVersion = composition.currentVersion;
  return (
    <article className="map-composition-card">
      <button
        className="map-composition-thumbnail"
        type="button"
        disabled={!composition.canPreview || !previewVersion}
        onClick={onPreview}
      >
        {previewVersion ? (
          <>
            <EyeOutlined />
            <span>
              {english ? "Preview" : "预览"} V{previewVersion.versionNumber}
            </span>
          </>
        ) : (
          <span>{english ? "No result generated" : "尚未生成成果"}</span>
        )}
      </button>
      <div className="map-composition-card-main">
        <div className="map-composition-card-title">
          <strong>{composition.name}</strong>
          <Tag color={statusColor(composition.status)}>
            {statusLabel(composition.status, english)}
          </Tag>
          {!composition.isOwner ? (
            <Tag color="cyan">
              {english ? "Owned by another user" : "非本人专题"}
            </Tag>
          ) : null}
        </div>
        <small>
          {english ? "Source" : "来源"}：{composition.projectName}
        </small>
        <small>
          {english ? "Owner" : "所属"}：
          {composition.owner.displayName || composition.owner.username}
        </small>
        {composition.publishedVersion ? (
          <small>
            {english ? "Published" : "已发布"} V
            {composition.publishedVersion.versionNumber} ·{" "}
            {composition.audienceGroups
              .map((group) => group.name)
              .join(english ? ", " : "、") ||
              (english ? "No roles configured" : "未配置角色")}
          </small>
        ) : (
          <small>
            {composition.description ||
              new Date(composition.updatedAt).toLocaleString(
                english ? "en-US" : "zh-CN",
                {
                  hour12: false,
                },
              )}
          </small>
        )}
      </div>
      <Space size={4} wrap>
        {composition.canEditLayout ? (
          <Button size="small" icon={<EditOutlined />} onClick={onOpen}>
            {english ? "Edit layout" : "编辑版式"}
          </Button>
        ) : null}
        <Button
          size="small"
          icon={<DownloadOutlined />}
          disabled={!composition.canDownload || !previewVersion}
          onClick={onDownload}
        >
          {english ? "Download" : "下载"}
        </Button>
        {composition.canPublish ? (
          <Button size="small" icon={<UploadOutlined />} onClick={onPublish}>
            {composition.status === "published"
              ? english
                ? "Update publication"
                : "更新发布"
              : english
                ? "Publish"
                : "发布"}
          </Button>
        ) : null}
        {composition.canUnpublish ? (
          <Button size="small" onClick={onUnpublish}>
            {english ? "Unpublish" : "下架"}
          </Button>
        ) : null}
        {composition.canRestoreProject ? (
          <Button size="small" icon={<RollbackOutlined />} onClick={onRestore}>
            {english ? "Restore project" : "还原工程"}
          </Button>
        ) : null}
        {composition.canLoadSourceProject ? (
          <Button
            size="small"
            icon={<FolderOpenOutlined />}
            onClick={onLoadSource}
          >
            {english ? "Source project" : "来源工程"}
          </Button>
        ) : null}
        {composition.canDelete ? (
          <Popconfirm
            title={english ? "Delete map draft" : "删除出图稿"}
            description={
              english
                ? `Delete “${composition.name}”? The thematic map, all versions, and result files will be permanently deleted.`
                : `确认删除“${composition.name}”？专题、全部版本记录和成果文件将被永久删除且不可恢复。`
            }
            okText={english ? "Delete" : "删除"}
            cancelText={english ? "Cancel" : "取消"}
            okButtonProps={{ danger: true }}
            onConfirm={onDelete}
          >
            <Tooltip title={english ? "Delete" : "删除"}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        ) : null}
      </Space>
    </article>
  );
}

function statusLabel(status: MapComposition["status"], english = false) {
  return english
    ? { draft: "Draft", completed: "Unpublished", published: "Published" }[
        status
      ]
    : { draft: "草稿", completed: "未发布", published: "已发布" }[status];
}

function statusColor(status: MapComposition["status"]) {
  return { draft: "default", completed: "blue", published: "green" }[status];
}
