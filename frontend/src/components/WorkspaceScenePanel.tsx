import { ProjectNotice, ProjectLabel } from "../projects/ProjectLabel";
import {
  DeleteOutlined,
  EditOutlined,
  FileImageOutlined,
  ReloadOutlined,
  SearchOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";
import {
  App,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Pagination,
  Space,
  Tag,
  Tooltip,
} from "antd";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import ShareButton from "../sharing/ShareButton";
import type {
  WorkspaceAccessGroup,
  WorkspaceSceneSummary,
  WorkspaceSceneKind,
} from "../types";

interface WorkspaceScenePanelProps {
  kind: WorkspaceSceneKind;
  items: WorkspaceSceneSummary[];
  total?: number;
  query?: { q: string; offset: number };
  onQuery?: (query: { q?: string; offset?: number }) => unknown;
  accessGroups: WorkspaceAccessGroup[];
  onLoad: (scene: WorkspaceSceneSummary) => void | Promise<void>;
  onRefresh: () => unknown | Promise<unknown>;
  onUpdate: (scene: WorkspaceSceneSummary) => void;
  onDelete: (sceneId: number) => void;
  onCreateComposition?: (scene: WorkspaceSceneSummary) => void | Promise<void>;
}

interface WorkspaceEditValues {
  name: string;
  description?: string;
  accessGroupIds?: number[];
}

export default function WorkspaceScenePanel({
  kind,
  items,
  total = items.length,
  query,
  onQuery,
  onLoad,
  onRefresh,
  onUpdate,
  onDelete,
  onCreateComposition,
}: WorkspaceScenePanelProps) {
  const { message } = App.useApp();
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const [form] = Form.useForm<WorkspaceEditValues>();
  const [loading, setLoading] = useState(false);
  const [loadingSceneId, setLoadingSceneId] = useState<number | null>(null);
  const [localPage, setPage] = useState(1);
  const [localSearchText, setSearchText] = useState("");
  const page = query ? Math.floor(query.offset / 24) + 1 : localPage;
  const searchText = query?.q ?? localSearchText;
  const [editingScene, setEditingScene] =
    useState<WorkspaceSceneSummary | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const label =
    kind === "project"
      ? english
        ? "project"
        : "工程"
      : english
        ? "thematic map"
        : "专题";
  const filteredItems = useMemo(() => {
    if (onQuery) return items;
    const query = searchText.trim().toLocaleLowerCase("zh-CN");
    if (!query) return items;
    return items.filter((scene) =>
      [
        scene.name,
        scene.description,
        scene.owner.displayName,
        scene.owner.username,
        ...scene.accessGroups.map((group) => group.name),
      ].some((value) => value.toLocaleLowerCase("zh-CN").includes(query)),
    );
  }, [items, searchText]);

  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      await onRefresh();
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? `Failed to load ${label}`
            : `${label}加载失败`,
      );
    } finally {
      setLoading(false);
    }
  }, [label, message, onRefresh]);

  async function loadScene(scene: WorkspaceSceneSummary) {
    setLoadingSceneId(scene.id);
    try {
      await onLoad(scene);
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? `Failed to load ${label}`
            : `${label}加载失败`,
      );
    } finally {
      setLoadingSceneId(null);
    }
  }

  async function removeScene(scene: WorkspaceSceneSummary) {
    try {
      await api.deleteWorkspace(scene.id);
      onDelete(scene.id);
      message.success(english ? `${label} deleted` : `${label}已删除`);
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? `Failed to delete ${label}`
            : `${label}删除失败`,
      );
    }
  }

  function openEditScene(scene: WorkspaceSceneSummary) {
    setEditingScene(scene);
    form.setFieldsValue({
      name: scene.name,
      description: scene.description,
      accessGroupIds: scene.accessGroups.map((group) => group.id),
    });
  }

  async function submitEditScene() {
    if (!editingScene) return;
    let values: WorkspaceEditValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSavingEdit(true);
    try {
      const updated = await api.updateWorkspace(editingScene.id, {
        expectedUpdatedAt: editingScene.updatedAt,
        ...(editingScene.canEdit
          ? {
              name: values.name.trim(),
              description: values.description?.trim() ?? "",
            }
          : {}),
        accessGroupIds: editingScene.accessGroups.map((group) => group.id),
      });
      if ("id" in updated) onUpdate(updated);
      setEditingScene(null);
      message.success(
        english ? `${label} information updated` : `${label}信息已更新`,
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? `Failed to update ${label}`
            : `${label}更新失败`,
      );
    } finally {
      setSavingEdit(false);
    }
  }

  return (
    <section className="panel-section topic-workspace-panel">
      <div className="workspace-scene-toolbar">
        <Input
          allowClear
          size="small"
          prefix={<SearchOutlined />}
          placeholder={
            english
              ? `Search ${label}, name or description`
              : `搜索${label}名称或说明`
          }
          value={searchText}
          onChange={(event) => {
            setSearchText(event.target.value);
            setPage(1);
            onQuery?.({ q: event.target.value, offset: 0 });
          }}
        />
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={() => void loadItems()}
          loading={loading}
        >
          {english ? "Refresh" : "刷新"}
        </Button>
      </div>
      {onQuery && total > 24 ? (
        <Pagination
          size="small"
          current={page}
          pageSize={24}
          total={total}
          showSizeChanger={false}
          onChange={(next) => {
            setPage(next);
            onQuery({ q: searchText, offset: (next - 1) * 24 });
          }}
        />
      ) : null}
      <div className="workspace-scene-summary">
        {english
          ? `${total} loadable ${label}${items.length === 1 ? "" : "s"}`
          : `共 ${total} 个可加载${label}`}
        {searchText.trim()
          ? english
            ? `; ${filteredItems.length} matches`
            : `，匹配 ${filteredItems.length} 个`
          : ""}
      </div>
      {filteredItems.length === 0 ? (
        <Empty
          className="layer-empty"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            searchText.trim()
              ? english
                ? `No matching ${label}`
                : `没有匹配的${label}`
              : english
                ? `No visible ${label}`
                : `暂无可见${label}`
          }
        />
      ) : (
        <div className="topic-scenario-list">
          {filteredItems.map((scene) => (
            <div key={scene.id} className="topic-scenario-row">
              <div className="topic-scenario-main">
                <span>
                  <strong>{scene.name}</strong>
                  <small className="workspace-scene-owner">
                    <UserOutlined />
                    {scene.owner.displayName || scene.owner.username}
                    <Tag color={scene.isOwner ? "cyan" : "blue"}>
                      {scene.isOwner
                        ? english
                          ? "Mine"
                          : "我的"
                        : english
                          ? "Read only"
                          : "只读"}
                    </Tag>
                  </small>
                  <small>
                    {scene.description ||
                      (english ? "No description" : "未填写说明")}
                  </small>
                  <small className="workspace-scene-access">
                    <TeamOutlined />
                    <ProjectLabel id={scene.projectTagId} />
                  </small>
                </span>
              </div>
              <Space size={4} wrap>
                <Button
                  type="primary"
                  size="small"
                  loading={loadingSceneId === scene.id}
                  disabled={
                    loadingSceneId !== null && loadingSceneId !== scene.id
                  }
                  onClick={() => void loadScene(scene)}
                >
                  {english ? "Load" : "加载"}
                </Button>
                {kind === "project" && onCreateComposition ? (
                  <Button
                    size="small"
                    icon={<FileImageOutlined style={{ fontSize: 13 }} />}
                    disabled={!scene.isOwner}
                    onClick={() => void onCreateComposition(scene)}
                  >
                    {english ? "New map output" : "新建出图"}
                  </Button>
                ) : null}
                {(scene.isOwner || scene.canManageAccess) && (
                  <ShareButton
                    kind="workspace"
                    objectId={scene.id}
                    name={scene.name}
                  />
                )}
                {(scene.canEdit || scene.canManageAccess) && (
                  <Tooltip title={english ? `Edit ${label}` : `编辑${label}`}>
                    <Button
                      aria-label={
                        english ? `Edit ${scene.name}` : `编辑${scene.name}`
                      }
                      size="small"
                      icon={<EditOutlined style={{ fontSize: 14 }} />}
                      onClick={() => openEditScene(scene)}
                    />
                  </Tooltip>
                )}
                {scene.canDelete && (
                  <Popconfirm
                    title={english ? `Delete ${label}` : `删除${label}`}
                    description={
                      english
                        ? `Delete “${scene.name}”?`
                        : `确认删除“${scene.name}”？`
                    }
                    okText={english ? "Delete" : "删除"}
                    cancelText={english ? "Cancel" : "取消"}
                    onConfirm={() => void removeScene(scene)}
                  >
                    <Button
                      aria-label={
                        english ? `Delete ${scene.name}` : `删除${scene.name}`
                      }
                      className="topic-scenario-delete-button"
                      size="small"
                      danger
                      icon={<DeleteOutlined style={{ fontSize: 14 }} />}
                    />
                  </Popconfirm>
                )}
              </Space>
            </div>
          ))}
        </div>
      )}
      <Modal
        className="workspace-scene-edit-modal"
        title={english ? `Edit ${label}` : `编辑${label}`}
        open={Boolean(editingScene)}
        okText={english ? "Save" : "保存"}
        cancelText={english ? "Cancel" : "取消"}
        confirmLoading={savingEdit}
        onOk={() => void submitEditScene()}
        onCancel={() => setEditingScene(null)}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" requiredMark={false}>
          <Form.Item
            name="name"
            label={english ? `${label} name` : `${label}名称`}
            rules={[
              {
                required: true,
                whitespace: true,
                message: english
                  ? `Enter the ${label} name`
                  : `请输入${label}名称`,
              },
              {
                max: 160,
                message: english
                  ? `${label} name cannot exceed 160 characters`
                  : `${label}名称不能超过 160 个字符`,
              },
            ]}
          >
            <Input disabled={!editingScene?.canEdit} />
          </Form.Item>
          <Form.Item
            name="description"
            label={english ? `${label} description` : `${label}说明`}
          >
            <Input.TextArea
              rows={4}
              maxLength={1000}
              showCount
              disabled={!editingScene?.canEdit}
            />
          </Form.Item>
          <ProjectNotice />
          <div className="workspace-scene-fixed-access">
            {english
              ? "Private to its owner by default. Recipients can read it after accepting an invitation; superadministrators retain management access."
              : "工程默认仅创建者可见。通过分享邀请并被接受后，对方才能只读加载；超级管理员保留管理权限。"}
          </div>
        </Form>
      </Modal>
    </section>
  );
}
