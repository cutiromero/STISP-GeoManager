import { ProjectLabel } from "../projects/ProjectLabel";
import { FolderOpenOutlined, GlobalOutlined } from "@ant-design/icons";
import {
  App as AntApp,
  Button,
  Form,
  Input,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import ShareButton from "../sharing/ShareButton";
import { useAppContext } from "../contexts/AppContext";
import { localText, useEnglishLanguage } from "../i18n/useEnglishLanguage";
import type {
  AdminWorkspaceFilters,
  AdminWorkspaceList,
  AdminWorkspaceScene,
} from "../types";
import ManagedCollectionPage, {
  type AccessScopeId,
  type FilterField,
  type ManagedFormValues,
  realAccessGroupIds,
  withFixedAccessScopes,
} from "./ManagedCollectionPage";
import {
  isWorkspaceInventoryChange,
  notifyWorkspaceInventoryChanged,
  workspaceInventoryChangedEvent,
} from "../workspace/workspaceSync";

type WorkspaceFormValues = ManagedFormValues & {
  name: string;
  description?: string;
  kind: AdminWorkspaceScene["kind"];
};

const statusLabels = {
  active: { text: "启用", color: "green" },
  inactive: { text: "禁用", color: "default" },
} as const;

const kindLabels: Record<AdminWorkspaceScene["kind"], string> = {
  project: "工程",
};

const initialList: AdminWorkspaceList = {
  items: [],
  total: 0,
  availableAccessGroups: [],
};

export default function AdminWorkspaceManagementPage({
  kind,
}: {
  kind: AdminWorkspaceScene["kind"];
}) {
  const { message } = AntApp.useApp();
  const english = useEnglishLanguage();
  const l = (zh: string, en: string) => localText(english, zh, en);
  const navigate = useNavigate();
  const { user } = useAppContext();
  const [filters, setFilters] = useState<AdminWorkspaceFilters>({
    kind,
    status: "active",
    current: 1,
    pageSize: 10,
  });
  const [data, setData] = useState<AdminWorkspaceList>(initialList);
  const [loading, setLoading] = useState(false);
  const canView = Boolean(user?.permissions.canViewWorkspaces);
  const canChange = Boolean(user?.permissions.canChangeWorkspaces);
  const canMaintain = canChange;
  const canDelete = Boolean(user?.permissions.canDeleteWorkspaces);
  const canOpen = canView || canChange || canDelete;
  const label = english ? "project" : kindLabels[kind];
  const localizedFilterFields: FilterField[] = [
    {
      name: "status",
      kind: "select",
      label: l("状态", "Status"),
      options: [
        { value: "active", label: l("启用", "Enabled") },
        { value: "inactive", label: l("禁用", "Disabled") },
      ],
    },
  ];

  const metrics = useMemo(() => {
    const active = data.items.filter((item) => item.status === "active").length;
    const inactive = data.items.filter(
      (item) => item.status === "inactive",
    ).length;
    const shared = data.items.filter(
      (item) => item.accessGroups.length > 0,
    ).length;
    return { active, inactive, shared };
  }, [data.items]);

  const loadItems = useCallback(
    async (nextFilters: AdminWorkspaceFilters) => {
      setLoading(true);
      try {
        const result = await api.adminWorkspaces(nextFilters);
        setData(result);
      } catch (error) {
        message.error(
          error instanceof Error
            ? error.message
            : l(`${label}加载失败`, `Failed to load ${label}s`),
        );
      } finally {
        setLoading(false);
      }
    },
    [label, message],
  );

  useEffect(() => {
    if (canOpen) {
      void loadItems(filters);
    }
  }, [canOpen, filters, loadItems]);

  useEffect(() => {
    setFilters((currentFilters) => ({
      ...currentFilters,
      kind,
      current: 1,
    }));
  }, [kind]);

  useEffect(() => {
    function refreshFromEvent(event: Event) {
      const detail = event instanceof CustomEvent ? event.detail : undefined;
      if (isWorkspaceInventoryChange(detail)) {
        void loadItems(filters);
      }
    }
    function refreshFromStorage(event: StorageEvent) {
      if (event.key !== workspaceInventoryChangedEvent || !event.newValue) {
        return;
      }
      try {
        if (isWorkspaceInventoryChange(JSON.parse(event.newValue))) {
          void loadItems(filters);
        }
      } catch {
        return;
      }
    }
    function refreshOnFocus() {
      if (document.visibilityState === "visible") {
        void loadItems(filters);
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
  }, [filters, loadItems]);

  if (!canOpen) {
    return <Navigate to="/admin/profile" replace />;
  }

  async function saveItem(
    item: AdminWorkspaceScene,
    values: ManagedFormValues,
  ) {
    try {
      if (!canMaintain || !item.canEdit) {
        if (!item.canManageAccess) {
          message.warning(
            l(
              `当前用户无${label}编辑权限`,
              `You do not have permission to edit this ${label}`,
            ),
          );
          return;
        }
        const updated = await api.updateAdminWorkspace(item.id, {
          expectedUpdatedAt: item.updatedAt,
          action: "updateAccess",
          accessGroupIds: realAccessGroupIds(values.accessGroupIds),
        });
        if ("id" in updated) {
          replaceItem(updated);
          notifyWorkspaceInventoryChanged("workspace");
          message.success(
            l(`${label}可见范围已保存`, `${label} visibility saved`),
          );
          return updated;
        }
        return;
      }
      const formValues = values as WorkspaceFormValues;
      const updated = await api.updateAdminWorkspace(item.id, {
        expectedUpdatedAt: item.updatedAt,
        action: "update",
        name: formValues.name,
        description: formValues.description ?? "",
        kind: formValues.kind,
        status: item.status,
        accessGroupIds: realAccessGroupIds(formValues.accessGroupIds),
      });
      if ("id" in updated) {
        replaceItem(updated);
        notifyWorkspaceInventoryChanged("workspace");
        message.success(
          l(
            `${label}信息和权限已保存`,
            `${label} details and permissions saved`,
          ),
        );
        return updated;
      }
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : l("保存失败", "Save failed"),
      );
    }
  }

  async function toggleStatus(item: AdminWorkspaceScene, checked: boolean) {
    if (!canMaintain || !item.canEdit) {
      message.warning(
        l(
          `当前用户无${label}编辑权限`,
          `You do not have permission to edit this ${label}`,
        ),
      );
      return;
    }
    try {
      const updated = await api.updateAdminWorkspace(item.id, {
        expectedUpdatedAt: item.updatedAt,
        action: "setStatus",
        status: checked ? "active" : "inactive",
      });
      if ("id" in updated) {
        replaceItem(updated);
        notifyWorkspaceInventoryChanged("workspace");
      }
      message.success(
        l(
          `已${checked ? "启用" : "禁用"} ${item.name}`,
          `${item.name} ${checked ? "enabled" : "disabled"}`,
        ),
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("状态更新失败", "Status update failed"),
      );
    }
  }

  async function deleteItem(
    item: AdminWorkspaceScene,
    confirmationName: string,
  ) {
    if (!canDelete || !item.canDelete) {
      message.warning(
        l(
          `当前用户无${label}删除权限`,
          `You do not have permission to delete this ${label}`,
        ),
      );
      return;
    }
    try {
      await api.updateAdminWorkspace(item.id, {
        expectedUpdatedAt: item.updatedAt,
        action: "delete",
        confirmationName,
      });
      setData((current) => ({
        ...current,
        items: current.items.filter((entry) => entry.id !== item.id),
        total: Math.max(current.total - 1, 0),
      }));
      notifyWorkspaceInventoryChanged("workspace");
      message.success(l(`${label}已删除`, `${label} deleted`));
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : l("删除失败", "Delete failed"),
      );
    }
  }

  function replaceItem(item: AdminWorkspaceScene) {
    setData((current) => ({
      ...current,
      items: current.items.map((entry) =>
        entry.id === item.id ? item : entry,
      ),
    }));
  }

  const columns: ColumnsType<AdminWorkspaceScene> = [
    {
      title: l(`${label}名称`, `${capitalize(label)} name`),
      dataIndex: "name",
      key: "name",
      width: 260,
      render: (_, record) => (
        <Space orientation="vertical" size={2}>
          <Typography.Text strong>{record.name}</Typography.Text>
          <Typography.Text type="secondary" className="admin-table-subtext">
            {record.description || l("未填写说明", "No description")}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: l("类型", "Type"),
      dataIndex: "kind",
      key: "kind",
      width: 96,
      render: (value: AdminWorkspaceScene["kind"]) => (
        <Tag>
          {english
            ? value === "project"
              ? "Project"
              : "Topic"
            : kindLabels[value]}
        </Tag>
      ),
    },
    {
      title: l("状态", "Status"),
      dataIndex: "status",
      key: "status",
      width: 112,
      render: (_, record) => (
        <Switch
          size="small"
          checked={record.status === "active"}
          checkedChildren={l("启用", "On")}
          unCheckedChildren={l("禁用", "Off")}
          disabled={!canMaintain || !record.canEdit}
          onChange={(checked) => toggleStatus(record, checked)}
        />
      ),
    },
    {
      title: l("所属用户", "Owner"),
      key: "owner",
      width: 160,
      render: (_, record) => (
        <Space orientation="vertical" size={0}>
          <span>{ownerDisplayName(record)}</span>
          <Typography.Text type="secondary" className="admin-table-subtext">
            {record.owner.username}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: l("可见范围", "Visibility"),
      key: "accessGroups",
      width: 240,
      render: (_, record) => <ProjectLabel id={record.projectTagId} />,
    },
    {
      title: l("快照图层", "Snapshot layers"),
      key: "layers",
      width: 104,
      align: "center",
      render: (_, record) => workspaceLayerCount(record),
    },
    {
      title: l("打开与分享", "Open and share"),
      key: "load",
      width: 190,
      render: (_, record) => (
        <Space size={4}>
          <Button
            type="link"
            icon={<GlobalOutlined />}
            disabled={record.status !== "active"}
            onClick={() => navigate(`/map?sceneId=${record.id}`)}
          >
            {l("打开", "Open")}
          </Button>
          <ShareButton
            type="link"
            kind="workspace"
            objectId={record.id}
            name={record.name}
            disabled={record.status !== "active"}
          />
        </Space>
      ),
    },
  ];

  return (
    <ManagedCollectionPage<AdminWorkspaceScene>
      items={data.items}
      total={data.total}
      accessGroups={data.availableAccessGroups}
      loading={loading}
      filters={filters}
      filterFields={localizedFilterFields}
      columns={columns}
      stats={[
        {
          title: l(`当前${label}`, `Current ${label}s`),
          value: data.total,
          prefix: <FolderOpenOutlined />,
        },
        { title: l("本页启用", "Enabled on this page"), value: metrics.active },
        {
          title: l("本页禁用", "Disabled on this page"),
          value: metrics.inactive,
        },
        {
          title: l("本页已共享", "Shared on this page"),
          value: metrics.shared,
        },
      ]}
      rowName={(item) => item.name}
      drawerTitle={l(`${label}配置`, `${capitalize(label)} configuration`)}
      deleteTitle={l(`删除${label}`, `Delete ${label}`)}
      deleteDescription={l(
        `删除会移除该${label}保存项和共享配置，不会删除原始数据资源。请输入完整名称确认。`,
        `Deleting removes the saved ${label} and sharing configuration, but does not delete source data resources. Enter the full name to confirm.`,
      )}
      ownerScopeLabel={l("所属用户本人可见", "Visible to the owner")}
      accessScopeNotice={
        <Typography.Text type="secondary">
          {l(
            "所属用户本人始终可见；平台会自动保留必要的系统访问范围。",
            "The owner can always see this item; the platform also preserves required system access.",
          )}
        </Typography.Text>
      }
      canMaintain={canMaintain}
      canMaintainItem={(item) => item.canEdit}
      canDelete={canDelete}
      canDeleteItem={(item) => item.canDelete}
      detailItems={(item) => [
        {
          label: l(`${label}名称`, `${capitalize(label)} name`),
          value: item.name,
        },
        {
          label: l("类型", "Type"),
          value: english
            ? item.kind === "project"
              ? "Project"
              : "Topic"
            : kindLabels[item.kind],
        },
        {
          label: l("状态", "Status"),
          value: (
            <Tag color={statusLabels[item.status].color}>
              {english
                ? item.status === "active"
                  ? "Enabled"
                  : "Disabled"
                : statusLabels[item.status].text}
            </Tag>
          ),
        },
        { label: l("所属用户", "Owner"), value: ownerDisplayName(item) },
        {
          label: l("创建时间", "Created at"),
          value: new Date(item.createdAt).toLocaleString(
            english ? "en-US" : "zh-CN",
          ),
        },
        {
          label: l("快照图层数", "Snapshot layer count"),
          value: workspaceLayerCount(item),
        },
        {
          label: l("项目访问范围", "Project access"),
          value: <ProjectLabel id={item.projectTagId} />,
        },
      ]}
      formInitialValues={(item) => ({
        name: item.name,
        description: item.description,
        kind: item.kind,
        accessGroupIds: withFixedAccessScopes(
          item.accessGroups.map((group) => group.id as AccessScopeId),
        ),
      })}
      renderFormItems={(_, maintainable) => (
        <>
          <Typography.Title level={5}>
            {l("基础信息", "Basic information")}
          </Typography.Title>
          <Form.Item
            name="name"
            label={l(`${label}名称`, `${capitalize(label)} name`)}
            rules={[
              {
                required: true,
                message: l(`请输入${label}名称`, `Enter a ${label} name`),
              },
            ]}
          >
            <Input disabled={!maintainable} />
          </Form.Item>
          <Form.Item
            name="description"
            label={l(`${label}说明`, `${capitalize(label)} description`)}
          >
            <Input.TextArea rows={4} disabled={!maintainable} />
          </Form.Item>
          <Form.Item name="kind" label={l("类型", "Type")}>
            <Select
              disabled={!maintainable}
              options={[
                { value: "project", label: l("工程", "Project") },
                { value: "topic", label: l("专题", "Topic") },
              ]}
            />
          </Form.Item>
        </>
      )}
      onFilterChange={(nextFilters) =>
        setFilters({
          ...(nextFilters as AdminWorkspaceFilters),
          kind,
        })
      }
      onPageChange={(current, pageSize) =>
        setFilters((currentFilters) => ({
          ...currentFilters,
          current,
          pageSize,
        }))
      }
      onSave={saveItem}
      onDelete={deleteItem}
    />
  );
}

function ownerDisplayName(item: AdminWorkspaceScene): string {
  return item.owner.displayName || item.owner.username;
}

function workspaceLayerCount(item: AdminWorkspaceScene): number {
  const groups = item.snapshot.groups;
  if (!Array.isArray(groups)) return 0;
  return groups.reduce((total, group) => {
    if (!group || typeof group !== "object") return total;
    const children = (group as { children?: unknown }).children;
    return total + (Array.isArray(children) ? children.length : 0);
  }, 0);
}

function capitalize(value: string) {
  return value ? value[0]!.toUpperCase() + value.slice(1) : value;
}
