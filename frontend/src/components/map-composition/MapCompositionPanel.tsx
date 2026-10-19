import { ReloadOutlined } from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Segmented,
  Select,
} from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import type {
  MapComposition,
  WorkspaceAccessGroup,
  WorkspaceScene,
} from "../../types";
import { downloadBlob } from "../../utils/download";
import MapCompositionCard from "./MapCompositionCard";

interface Props {
  items: MapComposition[];
  availableAudienceGroups: WorkspaceAccessGroup[];
  availableProjectAccessGroups: WorkspaceAccessGroup[];
  loading: boolean;
  onRefresh: () => unknown | Promise<unknown>;
  onOpen: (composition: MapComposition) => void | Promise<void>;
  onLoadSource: (composition: MapComposition) => void | Promise<void>;
  onRestored: (project: WorkspaceScene) => void | Promise<void>;
  onChanged: (composition: MapComposition) => void;
  onDeleted: (compositionId: number) => void;
}

interface PublishValues {
  versionNumber: number;
  audienceGroupIds: number[];
}

interface RestoreValues {
  versionNumber: number;
  name: string;
  description?: string;
  accessGroupIds?: number[];
  unavailableResourcePolicy: "skip" | "fail";
}

export default function MapCompositionPanel({
  items,
  loading,
  onRefresh,
  onOpen,
  onLoadSource,
  onRestored,
  onChanged,
  onDeleted,
}: Props) {
  const { message, notification } = App.useApp();
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const [publishForm] = Form.useForm<PublishValues>();
  const [restoreForm] = Form.useForm<RestoreValues>();
  const [status, setStatus] = useState<"all" | MapComposition["status"]>("all");
  const [previewUrl, setPreviewUrl] = useState("");
  const [previewTitle, setPreviewTitle] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [publishingComposition, setPublishingComposition] =
    useState<MapComposition | null>(null);
  const [restoringComposition, setRestoringComposition] =
    useState<MapComposition | null>(null);
  const visibleItems = useMemo(
    () => items.filter((item) => status === "all" || item.status === status),
    [items, status],
  );

  useEffect(
    () => () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl],
  );

  async function preview(composition: MapComposition) {
    const version = composition.currentVersion;
    if (!composition.canPreview || !version) return;
    try {
      const result = await api.downloadMapCompositionVersion(
        composition.id,
        version.versionNumber,
        "preview",
      );
      const nextUrl = URL.createObjectURL(result.blob);
      setPreviewUrl((current) => {
        if (current) URL.revokeObjectURL(current);
        return nextUrl;
      });
      setPreviewTitle(`${composition.name} / V${version.versionNumber}`);
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to preview thematic map"
            : "专题图预览失败",
      );
    }
  }

  async function download(composition: MapComposition) {
    const version = composition.currentVersion;
    if (!composition.canDownload || !version) return;
    try {
      const result = await api.downloadMapCompositionVersion(
        composition.id,
        version.versionNumber,
      );
      downloadBlob(result.blob, result.filename);
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to download thematic result"
            : "专题成果下载失败",
      );
    }
  }

  function openPublish(composition: MapComposition) {
    const defaultVersion =
      composition.publishedVersion?.versionNumber ??
      composition.currentVersion?.versionNumber;
    if (!defaultVersion) {
      message.warning(
        english
          ? "Generate at least one thematic result version first"
          : "请先生成至少一个专题成果版本",
      );
      return;
    }
    setPublishingComposition(composition);
    publishForm.setFieldsValue({
      versionNumber: defaultVersion,
      audienceGroupIds: composition.audienceGroups.map((group) => group.id),
    });
  }

  async function submitPublish() {
    if (!publishingComposition) return;
    const values = await publishForm.validateFields();
    setPublishing(true);
    try {
      const result = await api.publishMapComposition(
        publishingComposition.id,
        values,
      );
      onChanged(result);
      setPublishingComposition(null);
      message.success(
        publishingComposition.status === "published"
          ? english
            ? "Published version and audience updated"
            : "专题发布版本和范围已更新"
          : english
            ? "Thematic map published"
            : "专题已发布",
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to publish thematic map"
            : "专题发布失败",
      );
    } finally {
      setPublishing(false);
    }
  }

  async function unpublish(composition: MapComposition) {
    try {
      const result = await api.unpublishMapComposition(composition.id);
      onChanged(result);
      message.success(
        english
          ? "The thematic map is unpublished and visible only to its owner and administrators"
          : "专题已下架，仅所属用户和管理员可见",
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to unpublish thematic map"
            : "专题下架失败",
      );
    }
  }

  function openRestore(composition: MapComposition) {
    const version = composition.publishedVersion ?? composition.currentVersion;
    if (!version) return;
    setRestoringComposition(composition);
    restoreForm.setFieldsValue({
      versionNumber: version.versionNumber,
      name: english
        ? `${composition.name} V${version.versionNumber} restored project`
        : `${composition.name} V${version.versionNumber} 恢复工程`,
      description: english
        ? `Restored from thematic result “${composition.name}” V${version.versionNumber}`
        : `由专题“${composition.name}”成果 V${version.versionNumber} 恢复`,
      accessGroupIds: [],
      unavailableResourcePolicy: "skip",
    });
  }

  async function submitRestore() {
    if (!restoringComposition) return;
    const values = await restoreForm.validateFields();
    setRestoring(true);
    try {
      const result = await api.restoreMapCompositionProject(
        restoringComposition.id,
        values,
      );
      setRestoringComposition(null);
      if (result.warnings.length > 0) {
        notification.warning({
          message: english
            ? "Project restored; some layers were not loaded"
            : "工程已恢复，部分图层未加载",
          description: result.warnings
            .map((warning) => warning.message)
            .join(english ? "; " : "；"),
          duration: 8,
        });
      } else {
        message.success(
          english
            ? "The thematic version was restored as a new project"
            : "专题版本已还原为新工程",
        );
      }
      await onRestored(result.project);
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to restore thematic map"
            : "专题还原失败",
      );
    } finally {
      setRestoring(false);
    }
  }

  async function deleteComposition(composition: MapComposition) {
    try {
      await api.deleteMapComposition(composition.id);
      onDeleted(composition.id);
      message.success(english ? "Map draft deleted" : "出图稿已删除");
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to delete map draft"
            : "出图稿删除失败",
      );
    }
  }

  return (
    <section className="panel-section map-composition-panel">
      <div className="map-composition-panel-toolbar">
        <Segmented
          size="small"
          value={status}
          options={[
            { label: english ? "All" : "全部", value: "all" },
            { label: english ? "Draft" : "草稿", value: "draft" },
            { label: english ? "Unpublished" : "未发布", value: "completed" },
            { label: english ? "Published" : "已发布", value: "published" },
          ]}
          onChange={(value) =>
            setStatus(value as "all" | MapComposition["status"])
          }
        />
        <Button
          size="small"
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={() => void onRefresh()}
        />
      </div>
      {visibleItems.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            english ? "No visible thematic-map results" : "暂无可见专题出图成果"
          }
        />
      ) : (
        <div className="map-composition-list">
          {visibleItems.map((composition) => (
            <MapCompositionCard
              key={composition.id}
              composition={composition}
              onPreview={() => void preview(composition)}
              onOpen={() => void onOpen(composition)}
              onDownload={() => void download(composition)}
              onPublish={() => openPublish(composition)}
              onUnpublish={() => void unpublish(composition)}
              onRestore={() => openRestore(composition)}
              onLoadSource={() => void onLoadSource(composition)}
              onDelete={() => void deleteComposition(composition)}
            />
          ))}
        </div>
      )}
      <Modal
        title={previewTitle}
        open={Boolean(previewUrl)}
        footer={null}
        width="min(1000px, 92vw)"
        onCancel={() => setPreviewUrl("")}
      >
        {previewUrl ? (
          <img
            className="map-composition-preview-image"
            src={previewUrl}
            alt={previewTitle}
          />
        ) : null}
      </Modal>
      <Modal
        title={
          publishingComposition?.status === "published"
            ? english
              ? "Update publication"
              : "更新专题发布"
            : english
              ? "Publish thematic map"
              : "发布专题"
        }
        open={Boolean(publishingComposition)}
        okText={english ? "Publish" : "确认发布"}
        confirmLoading={publishing}
        onOk={() => void submitPublish()}
        onCancel={() => setPublishingComposition(null)}
        destroyOnHidden
      >
        <Alert
          type="info"
          showIcon
          title={
            english
              ? "Before publication, only the owner and platform/super administrators can view it"
              : "发布前仅所属用户、平台管理员和超级管理员可见"
          }
          description={
            english
              ? "After publication, members of this project can view it. The Public project is open to everyone. Download and restore require the corresponding permissions."
              : "发布后，所属项目成员可查看；公开项目所有人可读。下载和还原仍需相应功能权限。"
          }
          style={{ marginBottom: 16 }}
        />
        <Form form={publishForm} layout="vertical">
          <Form.Item
            name="versionNumber"
            label={english ? "Published version" : "正式发布版本"}
            rules={[
              {
                required: true,
                message: english
                  ? "Select a version to publish"
                  : "请选择发布版本",
              },
            ]}
          >
            <Select
              options={(publishingComposition?.versions ?? []).map(
                (version) => ({
                  value: version.versionNumber,
                  label: `V${version.versionNumber} / ${version.format.toUpperCase()} / ${new Date(version.createdAt).toLocaleString(english ? "en-US" : "zh-CN")}`,
                }),
              )}
            />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title={
          english
            ? "Restore thematic version as a new project"
            : "还原专题版本为新工程"
        }
        open={Boolean(restoringComposition)}
        okText={english ? "Create and load project" : "创建并加载工程"}
        confirmLoading={restoring}
        onOk={() => void submitRestore()}
        onCancel={() => setRestoringComposition(null)}
        destroyOnHidden
      >
        <Form form={restoreForm} layout="vertical">
          <Form.Item
            name="versionNumber"
            label={english ? "Version to restore" : "恢复版本"}
            rules={[
              {
                required: true,
                message: english
                  ? "Select a version to restore"
                  : "请选择恢复版本",
              },
            ]}
          >
            <Select
              options={(restoringComposition?.versions ?? []).map(
                (version) => ({
                  value: version.versionNumber,
                  label: `V${version.versionNumber} / ${version.format.toUpperCase()}`,
                }),
              )}
            />
          </Form.Item>
          <Form.Item
            name="name"
            label={english ? "New project name" : "新工程名称"}
            rules={[
              {
                required: true,
                message: english
                  ? "Enter the new project name"
                  : "请输入新工程名称",
              },
            ]}
          >
            <Input maxLength={160} />
          </Form.Item>
          <Form.Item
            name="description"
            label={english ? "Project description" : "工程说明"}
          >
            <Input.TextArea rows={3} maxLength={2000} />
          </Form.Item>
          <Form.Item
            name="unavailableResourcePolicy"
            label={english ? "Unavailable-resource policy" : "不可用资源处理"}
            rules={[{ required: true }]}
          >
            <Select
              options={[
                {
                  value: "skip",
                  label: english
                    ? "Skip and report (recommended)"
                    : "跳过并提示（推荐）",
                },
                {
                  value: "fail",
                  label: english
                    ? "Stop restoring if any resource is unavailable"
                    : "存在不可用资源时停止恢复",
                },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </section>
  );
}
