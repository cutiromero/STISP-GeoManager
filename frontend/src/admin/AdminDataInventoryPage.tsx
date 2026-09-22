import { ProjectLabel, ProjectNotice } from "../projects/ProjectLabel";
import { useProjectContext } from "../projects/ProjectContext";
import {
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  PlusOutlined,
  StopOutlined,
} from "@ant-design/icons";
import {
  App as AntApp,
  Button,
  Checkbox,
  Form,
  Input,
  Modal,
  Pagination,
  Popconfirm,
  Space,
  Select,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../api/client";
import { useAppContext } from "../contexts/AppContext";
import { localText, useEnglishLanguage } from "../i18n/useEnglishLanguage";
import type {
  AdminDataResource,
  AdminDataResourceFilters,
  AdminDataResourceGroup,
  AdminDataResourceList,
} from "../types";
import { downloadBlob } from "../utils/download";
import DataSchemaOverview from "./DataSchemaOverview";
import {
  fallbackTaxonomyTree,
  flattenTaxonomy,
  taxonomyTree,
} from "../utils/taxonomy";
import ManagedCollectionPage, {
  type AccessScopeId,
  type FilterField,
  type ManagedCollectionTableRenderArgs,
  type ManagedFormValues,
  realAccessGroupIds,
  withFixedAccessScopes,
} from "./ManagedCollectionPage";

type VisualizationFormValues = ManagedFormValues & {
  resourceName: string;
  categoryCode: string;
  layerName: string;
  defaultVisible: boolean;
  ownerOnly: boolean;
  pointColor?: string;
  symbolizationJson?: string;
  rasterRulesJson?: string;
};

const dataTypeLabels: Record<AdminDataResource["dataType"], string> = {
  vector: "矢量",
  raster: "栅格",
  gene: "基因",
  table: "表格",
  document: "文档",
  image: "图片",
};

const statusLabels = {
  active: { text: "启用", color: "green" },
  inactive: { text: "禁用", color: "default" },
} as const;

const initialList: AdminDataResourceList = {
  items: [],
  total: 0,
  summary: {
    total: 0,
    activeCount: 0,
    inactiveCount: 0,
    restrictedCount: 0,
    sizeBytes: 0,
    itemCount: 0,
  },
  groupSummaries: [],
  availableAccessGroups: [],
  inventoryGroups: [],
};

const allInventoryGroupId = "__all__";
const unclassifiedInventoryGroupId = "__unclassified__";

type CategoryInventoryGroupId = `__category__:${string}`;
type InventoryGroupId =
  | number
  | typeof allInventoryGroupId
  | typeof unclassifiedInventoryGroupId
  | CategoryInventoryGroupId;
type InventoryGroupKind =
  | "all"
  | "category-root"
  | "category-leaf"
  | "unclassified"
  | "custom";
type InventoryGroupSummary = AdminDataResourceList["groupSummaries"][number];
type GroupModalState = { kind: "create" } | null;

interface InventoryGroup {
  id: InventoryGroupId;
  name: string;
  resources: AdminDataResource[];
  resourceCount: number;
  sizeBytes: number;
  itemCount: number;
  enabled: boolean;
  partiallyEnabled: boolean;
  kind: InventoryGroupKind;
  subgroups: InventoryGroup[];
}

interface InventoryGroupDefinition {
  id: InventoryGroupId;
  name: string;
  kind: InventoryGroupKind;
  categoryCode?: string;
  children?: InventoryGroupDefinition[];
}

const allInventoryGroup: InventoryGroupDefinition = {
  id: allInventoryGroupId,
  name: "全部数据",
  kind: "all",
};

const categoryInventoryGroups: InventoryGroupDefinition[] =
  fallbackTaxonomyTree.map((root) => ({
    id: `__category__:${root.categoryCode}` as CategoryInventoryGroupId,
    name: root.name,
    kind: "category-root",
    categoryCode: root.categoryCode,
    children: root.children.map((child) => ({
      id: `__category__:${child.categoryCode}` as CategoryInventoryGroupId,
      name: child.name,
      kind: "category-leaf",
      categoryCode: child.categoryCode,
    })),
  }));

const unclassifiedInventoryGroup: InventoryGroupDefinition = {
  id: unclassifiedInventoryGroupId,
  name: "未分组（其他）",
  kind: "unclassified",
};

const inventoryGroupNameColumnWidth = 220;
const inventoryResourceNameColumnWidth = 260;
const inventoryActionColumnWidth = 112;
const inventoryGroupTableScrollX = 720;
const inventoryResourceTableScrollX = 1600;
const inventoryResourceColumnWidths: Record<string, number> = {
  name: inventoryResourceNameColumnWidth,
  dataType: 92,
  dataSize: 150,
  status: 112,
  source: 190,
  uploader: 150,
  dataDate: 120,
  updatedAt: 190,
  actions: inventoryActionColumnWidth,
};
const inventoryEllipsisColumnKeys = new Set([
  "name",
  "source",
  "uploader",
  "dataDate",
  "updatedAt",
]);

export default function AdminDataInventoryPage() {
  const { message } = AntApp.useApp();
  const english = useEnglishLanguage();
  const l = (zh: string, en: string) => localText(english, zh, en);
  const dataTypeText = (value: AdminDataResource["dataType"]) =>
    english
      ? {
          vector: "Vector",
          raster: "Raster",
          gene: "Gene",
          table: "Table",
          document: "Document",
          image: "Image",
        }[value]
      : dataTypeLabels[value];
  const localizedTaxonomy = taxonomyTree(undefined);
  const taxonomyNameByCode = new Map(
    flattenTaxonomy(localizedTaxonomy).map((node) => [
      node.categoryCode,
      node.name,
    ]),
  );
  const groupDisplayName = (group: InventoryGroup) => {
    if (!english || group.kind === "custom") return group.name;
    if (group.kind === "all") return "All data";
    if (group.kind === "unclassified") return "Unclassified (Other)";
    const code = String(group.id).replace("__category__:", "");
    return taxonomyNameByCode.get(code) ?? group.name;
  };
  const groupKindText = (kind: InventoryGroupKind) =>
    english
      ? {
          all: "All",
          "category-root": "Domain",
          "category-leaf": "Category",
          unclassified: "Unclassified",
          custom: "Custom",
        }[kind]
      : inventoryGroupKindLabel(kind);
  const localizedFilterFields: FilterField[] = [
    {
      name: "categoryCode",
      label: l("数据分类", "Data category"),
      kind: "select",
      options: flattenTaxonomy(localizedTaxonomy).map((node) => ({
        value: node.categoryCode,
        label: node.path.join(" / "),
      })),
    },
    {
      name: "classificationStatus",
      label: l("归类状态", "Classification status"),
      kind: "select",
      options: [
        { value: "classified", label: l("已分类", "Classified") },
        { value: "pending", label: l("待归类", "Pending") },
      ],
    },
    {
      name: "dataType",
      label: l("数据类型", "Data type"),
      kind: "select",
      options: Object.keys(dataTypeLabels).map((value) => ({
        value,
        label: dataTypeText(value as AdminDataResource["dataType"]),
      })),
    },
    {
      name: "status",
      label: l("状态", "Status"),
      kind: "select",
      options: [
        { value: "active", label: l("启用", "Enabled") },
        { value: "inactive", label: l("禁用", "Disabled") },
      ],
    },
    { name: "source", label: l("数据来源", "Data source"), kind: "input" },
    { name: "provider", label: l("提供单位", "Provider"), kind: "input" },
    { name: "dateFrom", label: l("起始日期", "Start date"), kind: "date" },
    { name: "dateTo", label: l("截止日期", "End date"), kind: "date" },
  ];
  const { user } = useAppContext();
  const projectContext = useProjectContext();
  const [filters, setFilters] = useState<AdminDataResourceFilters>({
    current: 1,
    pageSize: 50,
  });
  const [data, setData] = useState<AdminDataResourceList>(initialList);
  const [loading, setLoading] = useState(false);
  const resourceRequestSequenceRef = useRef(0);
  const [groupName, setGroupName] = useState("");
  const [groupModal, setGroupModal] = useState<GroupModalState>(null);
  const [savingGroup, setSavingGroup] = useState(false);
  const [editingGroupId, setEditingGroupId] = useState<InventoryGroupId | null>(
    null,
  );
  const [editingGroupName, setEditingGroupName] = useState("");
  const [savingGroupId, setSavingGroupId] = useState<InventoryGroupId | null>(
    null,
  );
  const [draggingResourceId, setDraggingResourceId] = useState<number | null>(
    null,
  );
  const [movingResourceId, setMovingResourceId] = useState<number | null>(null);
  const [updatingGroupId, setUpdatingGroupId] =
    useState<InventoryGroupId | null>(null);
  const [expandedInventoryGroupIds, setExpandedInventoryGroupIds] = useState<
    InventoryGroupId[]
  >([allInventoryGroupId]);
  const [expandedLeafGroupIds, setExpandedLeafGroupIds] = useState<
    InventoryGroupId[]
  >([]);

  const canView = Boolean(user?.permissions.canViewDataResources);
  const canChange = Boolean(user?.permissions.canChangeDataResources);
  const canDelete = Boolean(user?.permissions.canDeleteDataResources);
  const canUpload = Boolean(user?.permissions.canUploadData);
  const canExport = Boolean(user?.permissions.canExportData);
  const canBrowseData = Boolean(user?.permissions.canBrowseData);
  const canOpenInventory =
    canView || canChange || canDelete || canUpload || canExport;

  const inventoryGroups = useMemo(
    () =>
      buildInventoryGroups(
        data.items,
        data.inventoryGroups ?? [],
        data.groupSummaries,
      ),
    [data.groupSummaries, data.inventoryGroups, data.items],
  );

  const loadResources = useCallback(
    async (nextFilters: AdminDataResourceFilters) => {
      const requestSequence = ++resourceRequestSequenceRef.current;
      setLoading(true);
      try {
        const result = await api.adminDataResources(nextFilters);
        if (requestSequence === resourceRequestSequenceRef.current) {
          setData(result);
        }
      } catch (error) {
        if (requestSequence === resourceRequestSequenceRef.current) {
          message.error(
            error instanceof Error
              ? error.message
              : l("存量数据加载失败", "Failed to load inventory data"),
          );
        }
      } finally {
        if (requestSequence === resourceRequestSequenceRef.current) {
          setLoading(false);
        }
      }
    },
    [english, message],
  );

  useEffect(() => {
    if (canOpenInventory) {
      void loadResources(filters);
    }
  }, [canOpenInventory, filters, loadResources]);

  if (!canOpenInventory) {
    return <Navigate to="/admin/profile" replace />;
  }

  async function saveResourceSettings(
    resource: AdminDataResource,
    values: ManagedFormValues,
  ) {
    try {
      if (!canChange) {
        if (!resource.canManageAccess) {
          message.warning(
            l(
              "当前用户不能修改该数据的可见范围",
              "You cannot change this resource's visibility",
            ),
          );
          return;
        }
        const updated = await api.updateAdminDataResource(resource.id, {
          action: "updateAccess",
          accessGroupIds: realAccessGroupIds(values.accessGroupIds),
          ownerOnly: Boolean(values.ownerOnly),
        });
        if ("id" in updated) {
          replaceResource(updated);
          void loadResources(filters);
          message.success(l("数据可见范围已保存", "Data visibility saved"));
          return updated;
        }
        return;
      }
      const formValues = values as VisualizationFormValues;
      const symbolization = parseJsonObject(
        formValues.symbolizationJson,
        l("矢量符号", "Vector symbolization"),
        english,
      );
      if (resource.dataType === "vector") {
        symbolization.pointColor = formValues.pointColor;
      }
      const rasterRules = parseJsonObject(
        formValues.rasterRulesJson,
        l("栅格规则", "Raster rules"),
        english,
      );
      const updated = await api.updateAdminDataResource(resource.id, {
        action: "update",
        name: formValues.resourceName.trim(),
        categoryCode: formValues.categoryCode,
        accessGroupIds: realAccessGroupIds(formValues.accessGroupIds),
        ownerOnly: formValues.ownerOnly,
        visualization: {
          layerName: formValues.layerName,
          defaultVisible: formValues.defaultVisible,
          defaultOpacity: currentDefaultOpacity(resource),
          symbolization,
          rasterRules,
        },
      });
      if ("id" in updated) {
        replaceResource(updated);
        void loadResources(filters);
        message.success(
          l(
            "数据名称、权限与默认可视化方案已保存",
            "Data name, permissions, and default visualization saved",
          ),
        );
        return updated;
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    }
  }

  async function toggleStatus(resource: AdminDataResource, checked: boolean) {
    if (!canChange) {
      message.warning(
        l("当前用户无数据编辑权限", "You do not have data-edit permission"),
      );
      return;
    }
    const nextStatus = checked ? "active" : "inactive";
    try {
      const updated = await api.updateAdminDataResource(resource.id, {
        action: "setStatus",
        status: nextStatus,
      });
      if ("id" in updated) {
        replaceResource(updated);
      }
      void loadResources(filters);
      message.success(
        l(
          `已${checked ? "启用" : "禁用"} ${resource.name}`,
          `${resource.name} ${checked ? "enabled" : "disabled"}`,
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

  async function exportInventory(format: string) {
    if (!canExport) {
      message.warning(
        l("当前用户无数据导出权限", "You do not have data-export permission"),
      );
      return;
    }
    try {
      const exportFormat = format === "xlsx" ? "xlsx" : "csv";
      const { blob, filename } = await api.exportAdminDataResources({
        ...exportFilters(filters),
        format: exportFormat,
      });
      downloadBlob(blob, filename);
      message.success(
        l(
          `已导出 ${exportFormat.toUpperCase()} 清单`,
          `${exportFormat.toUpperCase()} inventory exported`,
        ),
      );
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : l("导出失败", "Export failed"),
      );
    }
  }

  async function deleteResource(
    resource: AdminDataResource,
    confirmationName: string,
  ) {
    if (!canDelete) {
      message.warning(
        l("当前用户无删除权限", "You do not have delete permission"),
      );
      return;
    }
    try {
      await api.updateAdminDataResource(resource.id, {
        action: "delete",
        confirmationName,
      });
      setData((current) => ({
        ...current,
        items: current.items.filter((item) => item.id !== resource.id),
        total: Math.max(current.total - 1, 0),
      }));
      void loadResources(filters);
      message.success(l("数据资源已删除", "Data resource deleted"));
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : l("删除失败", "Delete failed"),
      );
    }
  }

  function replaceResource(resource: AdminDataResource) {
    setData((current) => ({
      ...current,
      items: current.items.map((item) =>
        item.id === resource.id ? resource : item,
      ),
    }));
  }

  function openCreateGroupModal() {
    setGroupName("");
    setGroupModal({ kind: "create" });
  }

  function startInlineEditGroup(group: InventoryGroup) {
    setEditingGroupId(group.id);
    setEditingGroupName(group.name);
  }

  async function saveGroupModal() {
    const trimmedName = groupName.trim();
    if (!trimmedName) {
      message.warning(l("请输入资料夹名称", "Enter a group name"));
      return;
    }
    if (inventoryGroups.some((group) => group.name === trimmedName)) {
      message.warning(l("资料夹名称已存在", "That group name already exists"));
      return;
    }
    setSavingGroup(true);
    try {
      const created = await api.createAdminDataResourceGroup({
        name: trimmedName,
      });
      setData((current) => ({
        ...current,
        inventoryGroups: [...(current.inventoryGroups ?? []), created],
      }));
      void loadResources(filters);
      message.success(
        l(
          `已新增资料夹（不控制访问权限）：${trimmedName}`,
          `Group created: ${trimmedName}`,
        ),
      );
      setGroupName("");
      setGroupModal(null);
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("资料夹保存失败", "Failed to save group"),
      );
    } finally {
      setSavingGroup(false);
    }
  }

  async function saveInlineGroupName(group: InventoryGroup) {
    if (group.kind !== "custom" || savingGroupId === group.id) {
      return;
    }
    const trimmedName = editingGroupName.trim();
    if (!trimmedName) {
      message.warning(l("请输入资料夹名称", "Enter a group name"));
      setEditingGroupName(group.name);
      setEditingGroupId(null);
      return;
    }
    if (trimmedName === group.name) {
      setEditingGroupId(null);
      return;
    }
    if (
      inventoryGroups.some(
        (currentGroup) =>
          currentGroup.id !== group.id && currentGroup.name === trimmedName,
      )
    ) {
      message.warning(l("资料夹名称已存在", "That group name already exists"));
      return;
    }
    setSavingGroupId(group.id);
    try {
      const updated = await api.updateAdminDataResourceGroup(Number(group.id), {
        action: "update",
        name: trimmedName,
      });
      if ("id" in updated) {
        replaceInventoryGroup(updated);
        void loadResources(filters);
        message.success(l("资料夹名称已更新", "Group name updated"));
      }
      setEditingGroupId(null);
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("资料夹保存失败", "Failed to save group"),
      );
    } finally {
      setSavingGroupId(null);
    }
  }

  async function toggleGroupStatus(group: InventoryGroup, checked: boolean) {
    const manageableResources = group.resources.filter(
      (resource) => canChange && resource.status !== groupStatus(checked),
    );
    if (manageableResources.length === 0) {
      message.warning(
        l(
          "当前资料夹没有需要同步状态的数据",
          "This group has no data whose status needs updating",
        ),
      );
      return;
    }
    setUpdatingGroupId(group.id);
    const updatedResources: AdminDataResource[] = [];
    try {
      for (const resource of manageableResources) {
        const updated = await api.updateAdminDataResource(resource.id, {
          action: "setStatus",
          status: groupStatus(checked),
        });
        if ("id" in updated) {
          updatedResources.push(updated);
        }
      }
      replaceResources(updatedResources);
      void loadResources(filters);
      message.success(
        l(
          `已${checked ? "启用" : "禁用"} ${group.name} 组内数据`,
          `${group.name} group data ${checked ? "enabled" : "disabled"}`,
        ),
      );
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "资料夹状态同步失败",
      );
      void loadResources(filters);
    } finally {
      setUpdatingGroupId(null);
    }
  }

  async function moveResourceToGroup(
    resourceId: number,
    group: InventoryGroup,
  ) {
    if (!canChange) {
      message.warning(
        l("当前用户无数据编辑权限", "You do not have data-edit permission"),
      );
      return;
    }
    const resource = data.items.find((item) => item.id === resourceId);
    if (!resource) {
      return;
    }
    if (!canAcceptInventoryDrop(group)) {
      return;
    }
    const nextGroupId = group.kind === "all" ? null : Number(group.id);
    if (resource.inventoryGroupId === nextGroupId) {
      return;
    }
    setMovingResourceId(resourceId);
    try {
      const updated = await api.updateAdminDataResource(resource.id, {
        action: "updateInventoryGroup",
        inventoryGroupId: nextGroupId,
      });
      if ("id" in updated) {
        replaceResource(updated);
      }
      void loadResources(filters);
      message.success(l(`已移动到${group.name}`, `Moved to ${group.name}`));
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "数据资料夹更新失败",
      );
    } finally {
      setMovingResourceId(null);
    }
  }

  async function deleteInventoryGroup(group: InventoryGroup) {
    if (group.kind !== "custom") {
      return;
    }
    setUpdatingGroupId(group.id);
    try {
      await api.updateAdminDataResourceGroup(Number(group.id), {
        action: "delete",
      });
      setData((current) => ({
        ...current,
        inventoryGroups: (current.inventoryGroups ?? []).filter(
          (item) => item.id !== group.id,
        ),
        items: current.items.map((item) =>
          item.inventoryGroupId === group.id
            ? { ...item, inventoryGroupId: null }
            : item,
        ),
      }));
      void loadResources(filters);
      message.success(
        l(
          `已删除资料夹：${group.name}，数据仍保留在数据分类中`,
          `Group deleted: ${group.name}. The data remains in its authoritative category.`,
        ),
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("删除资料夹失败", "Failed to delete group"),
      );
    } finally {
      setUpdatingGroupId(null);
    }
  }

  function replaceResources(resources: AdminDataResource[]) {
    if (resources.length === 0) {
      return;
    }
    const byId = new Map(resources.map((resource) => [resource.id, resource]));
    setData((current) => ({
      ...current,
      items: current.items.map((item) => byId.get(item.id) ?? item),
    }));
  }

  function replaceInventoryGroup(group: AdminDataResourceGroup) {
    setData((current) => ({
      ...current,
      inventoryGroups: (current.inventoryGroups ?? []).map((item) =>
        item.id === group.id ? group : item,
      ),
    }));
  }

  const columns: ColumnsType<AdminDataResource> = [
    {
      title: l("数据资源", "Data resource"),
      dataIndex: "name",
      key: "name",
      width: inventoryResourceNameColumnWidth,
      ellipsis: true,
      render: (_, record) => (
        <Button
          type="link"
          className="inventory-resource-name-button"
          title={record.name}
        >
          {record.name}
        </Button>
      ),
    },
    {
      title: l("所属项目标签", "Project tag"),
      key: "projectTagId",
      width: 160,
      render: (_, record) => <ProjectLabel id={record.projectTagId} />,
    },
    {
      title: l("数据分类", "Data category"),
      key: "category",
      width: 220,
      render: (_, record) => (
        <Space orientation="vertical" size={0}>
          <Typography.Text>
            {record.categoryPath.map((item) => item.name).join(" / ") ||
              l("待归类", "Pending classification")}
          </Typography.Text>
          {record.classificationStatus === "pending" && (
            <Tag color="orange">{l("待归类", "Pending")}</Tag>
          )}
        </Space>
      ),
    },
    {
      title: l("类型", "Type"),
      dataIndex: "dataType",
      key: "dataType",
      width: 92,
      render: (value: AdminDataResource["dataType"]) => (
        <Tag>{dataTypeText(value)}</Tag>
      ),
    },
    {
      title: l("数据规模", "Data size"),
      key: "dataSize",
      width: 150,
      render: (_, record) => (
        <Space orientation="vertical" size={0}>
          <span>{formatBytes(record.sizeBytes ?? 0)}</span>
          <Typography.Text type="secondary" className="admin-table-subtext">
            {l(`${record.itemCount ?? 0} 条`, `${record.itemCount ?? 0} items`)}
          </Typography.Text>
        </Space>
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
          disabled={!canChange}
          onChange={(checked) => toggleStatus(record, checked)}
        />
      ),
    },
    {
      title: l("来源/单位", "Source / provider"),
      key: "source",
      width: 190,
      render: (_, record) => (
        <Space
          orientation="vertical"
          size={0}
          className="inventory-table-stack-cell"
        >
          <Typography.Text
            ellipsis={{ tooltip: record.source || l("未记录", "Not recorded") }}
          >
            {record.source || l("未记录", "Not recorded")}
          </Typography.Text>
          <Typography.Text
            type="secondary"
            className="admin-table-subtext"
            ellipsis={{
              tooltip:
                record.provider || l("未记录提供单位", "Provider not recorded"),
            }}
          >
            {record.provider || l("未记录提供单位", "Provider not recorded")}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: l("上传用户", "Uploader"),
      key: "uploader",
      width: 150,
      render: (_, record) => (
        <Space
          orientation="vertical"
          size={0}
          className="inventory-table-stack-cell"
        >
          <Typography.Text ellipsis={{ tooltip: uploaderDisplayName(record) }}>
            {uploaderDisplayName(record)}
          </Typography.Text>
          {record.uploader?.username && (
            <Typography.Text
              type="secondary"
              className="admin-table-subtext"
              ellipsis={{ tooltip: record.uploader.username }}
            >
              {record.uploader.username}
            </Typography.Text>
          )}
        </Space>
      ),
    },
    {
      title: l("数据日期", "Data date"),
      dataIndex: "dataDate",
      key: "dataDate",
      width: 120,
      render: (value: string | null) => value || "-",
    },
  ];

  const renderGroupedTable = ({
    tableColumns,
    loading: tableLoading,
    pagination,
  }: ManagedCollectionTableRenderArgs<AdminDataResource>) => {
    const nestedTableColumns = prepareNestedTableColumns(tableColumns);
    const groupColumns: ColumnsType<InventoryGroup> = [
      {
        title: l("资料夹名称", "Group name"),
        dataIndex: "name",
        key: "name",
        width: inventoryGroupNameColumnWidth,
        ellipsis: true,
        render: (_, group) => (
          <Space size={6} className="inventory-group-name-cell">
            {editingGroupId === group.id ? (
              <Input
                autoFocus
                size="small"
                aria-label={l(
                  `编辑资料夹名称${group.name}`,
                  `Edit group name ${group.name}`,
                )}
                className="inventory-group-name-input"
                value={editingGroupName}
                disabled={savingGroupId === group.id}
                onChange={(event) => setEditingGroupName(event.target.value)}
                onBlur={() => {
                  void saveInlineGroupName(group);
                }}
                onPressEnter={(event) => event.currentTarget.blur()}
              />
            ) : (
              <>
                <Typography.Text
                  strong
                  ellipsis={{ tooltip: groupDisplayName(group) }}
                >
                  {groupDisplayName(group)}
                </Typography.Text>
                {group.kind === "custom" && (
                  <Tooltip title={l("编辑资料夹名称", "Edit group name")}>
                    <Button
                      type="text"
                      size="small"
                      aria-label={l(
                        `编辑资料夹${group.name}`,
                        `Edit group ${group.name}`,
                      )}
                      className="inventory-group-edit-button"
                      icon={<EditOutlined />}
                      onClick={() => startInlineEditGroup(group)}
                    />
                  </Tooltip>
                )}
                <Tag color={inventoryGroupKindColor(group.kind)}>
                  {groupKindText(group.kind)}
                </Tag>
              </>
            )}
          </Space>
        ),
      },
      {
        title: l("操作", "Actions"),
        key: "groupActions",
        width: inventoryActionColumnWidth,
        render: (_, group) =>
          group.kind !== "custom" ? (
            <Tooltip
              title={l("系统分组不可删除", "System groups cannot be deleted")}
            >
              <Button
                icon={<DeleteOutlined />}
                disabled
                aria-label={l(
                  `删除系统分组${group.name}`,
                  `Delete system group ${group.name}`,
                )}
              />
            </Tooltip>
          ) : (
            <Popconfirm
              title={l("删除资料夹", "Delete group")}
              description={l(
                "删除后仅移除自定义归档关系，数据仍保留在对应的数据分类中。",
                "Deleting removes only the custom grouping. The data remains in its authoritative category.",
              )}
              okText={l("删除", "Delete")}
              cancelText={l("取消", "Cancel")}
              onConfirm={() => deleteInventoryGroup(group)}
            >
              <Button
                danger
                icon={<DeleteOutlined />}
                loading={updatingGroupId === group.id}
                aria-label={l(
                  `删除资料夹${group.name}`,
                  `Delete group ${group.name}`,
                )}
              />
            </Popconfirm>
          ),
      },
      {
        title: l("总数据规模", "Total data size"),
        key: "groupSize",
        width: 180,
        render: (_, group) => (
          <Space orientation="vertical" size={0}>
            <span>{formatBytes(group.sizeBytes)}</span>
            <Typography.Text
              type="secondary"
              className="admin-table-subtext"
              ellipsis={{
                tooltip: l(
                  `${group.itemCount} 条，${group.resourceCount} 项数据`,
                  `${group.itemCount} items in ${group.resourceCount} resources`,
                ),
              }}
            >
              {l(
                `${group.itemCount} 条，${group.resourceCount} 项数据`,
                `${group.itemCount} items in ${group.resourceCount} resources`,
              )}
            </Typography.Text>
          </Space>
        ),
      },
      {
        title: l("当前页状态", "Current-page status"),
        key: "groupAccess",
        width: 150,
        render: (_, group) => {
          const disabled =
            group.resources.length === 0 ||
            (!canChange &&
              !group.resources.every((resource) => resource.canManageAccess));
          return (
            <Checkbox
              className="inventory-group-status-checkbox"
              aria-label={l(
                `${group.name}资料夹状态`,
                `${group.name} group status`,
              )}
              checked={group.enabled}
              indeterminate={group.partiallyEnabled}
              disabled={disabled || updatingGroupId === group.id}
              onChange={(event) =>
                toggleGroupStatus(group, event.target.checked)
              }
            >
              {group.partiallyEnabled
                ? l("部分启用", "Partly enabled")
                : group.enabled
                  ? l("启用", "Enabled")
                  : l("禁用", "Disabled")}
            </Checkbox>
          );
        },
      },
    ];

    const renderGroupResources = (group: InventoryGroup) => (
      <div
        onDragOver={(event) => {
          if (canAcceptInventoryDrop(group)) {
            event.preventDefault();
          }
        }}
        onDrop={() => {
          if (draggingResourceId !== null && canAcceptInventoryDrop(group)) {
            void moveResourceToGroup(draggingResourceId, group);
            setDraggingResourceId(null);
          }
        }}
      >
        <div className="inventory-group-page-note">
          <Typography.Text type="secondary">
            {group.resources.length === group.resourceCount
              ? l(
                  `本页已显示该组全部 ${group.resourceCount} 项数据`,
                  `All ${group.resourceCount} resources in this group are shown on this page`,
                )
              : l(
                  `当前页显示 ${group.resources.length} 项，该组共 ${group.resourceCount} 项；可使用上方分页查看其余数据`,
                  `${group.resources.length} of ${group.resourceCount} resources are shown; use pagination above to view the rest`,
                )}
          </Typography.Text>
        </div>
        <Table<AdminDataResource>
          rowKey="id"
          size="small"
          className="inventory-group-resource-table"
          columns={nestedTableColumns}
          dataSource={group.resources}
          pagination={false}
          tableLayout="fixed"
          scroll={{ x: inventoryResourceTableScrollX }}
          onRow={(resource) => ({
            draggable: canChange,
            onDragStart: () => setDraggingResourceId(resource.id),
            onDragEnd: () => setDraggingResourceId(null),
            className:
              movingResourceId === resource.id
                ? "inventory-resource-moving-row"
                : undefined,
          })}
        />
      </div>
    );

    const renderExpandedGroup = (group: InventoryGroup) =>
      group.subgroups.length > 0 ? (
        <Table<InventoryGroup>
          rowKey={(child) => String(child.id)}
          size="small"
          className="inventory-category-child-table"
          columns={groupColumns}
          dataSource={group.subgroups}
          tableLayout="fixed"
          scroll={{ x: inventoryGroupTableScrollX }}
          pagination={false}
          expandable={{
            expandedRowKeys: expandedLeafGroupIds,
            rowExpandable: (child) => child.resourceCount > 0,
            expandedRowRender: renderGroupResources,
            onExpand: (expanded, child) => {
              setExpandedLeafGroupIds((current) =>
                expanded ? [child.id] : current.filter((id) => id !== child.id),
              );
            },
          }}
        />
      ) : (
        renderGroupResources(group)
      );

    return (
      <Space orientation="vertical" size={12} className="inventory-group-table">
        <div className="inventory-group-footer">
          <Pagination
            current={pagination.current}
            pageSize={pagination.pageSize}
            total={pagination.total}
            showSizeChanger={pagination.showSizeChanger}
            onChange={pagination.onChange}
            showTotal={(nextTotal) =>
              l(`共 ${nextTotal} 项数据`, `${nextTotal} resources`)
            }
          />
          <Button
            icon={<PlusOutlined />}
            aria-label={l("新增资料夹（不控制访问权限）", "Add group")}
            className="inventory-add-group-button"
            disabled={!canChange}
            onClick={openCreateGroupModal}
          >
            {l("新增资料夹（不控制访问权限）", "Add group")}
          </Button>
        </div>
        <Table<InventoryGroup>
          rowKey={(group) => String(group.id)}
          loading={tableLoading}
          columns={groupColumns}
          dataSource={inventoryGroups}
          tableLayout="fixed"
          scroll={{ x: inventoryGroupTableScrollX }}
          pagination={false}
          onRow={(group) => ({
            onDragOver: (event) => {
              if (canAcceptInventoryDrop(group)) {
                event.preventDefault();
              }
            },
            onDrop: () => {
              if (
                draggingResourceId !== null &&
                canAcceptInventoryDrop(group)
              ) {
                void moveResourceToGroup(draggingResourceId, group);
                setDraggingResourceId(null);
              }
            },
          })}
          expandable={{
            expandedRowKeys: expandedInventoryGroupIds,
            rowExpandable: (group) =>
              group.subgroups.length > 0 || group.resourceCount > 0,
            expandedRowRender: renderExpandedGroup,
            onExpand: (expanded, group) => {
              setExpandedInventoryGroupIds((current) =>
                expanded ? [group.id] : current.filter((id) => id !== group.id),
              );
              setExpandedLeafGroupIds([]);
            },
          }}
        />
      </Space>
    );
  };

  return (
    <>
      <ProjectNotice />
      {projectContext && (
        <Space wrap style={{ marginBottom: 16 }}>
          <Typography.Text strong>
            {l("按所属项目筛选", "Filter by project")}
          </Typography.Text>
          <Select
            aria-label={l("存量数据所属项目", "Inventory project filter")}
            value={projectContext.current}
            style={{ minWidth: 240 }}
            onChange={(id) => projectContext.choose(id)}
            options={projectContext.projects.map((project) => ({
              value: String(project.id),
              label: project.name,
            }))}
          />
          <Typography.Text type="secondary">
            {l(
              "项目标签决定数据访问权限；资料夹仅用于整理。",
              "Project tags control access; folders only organize data.",
            )}
          </Typography.Text>
        </Space>
      )}
      <DataSchemaOverview canBrowseData={canBrowseData} />
      <ManagedCollectionPage<AdminDataResource>
        items={data.items}
        total={data.total}
        accessGroups={data.availableAccessGroups}
        loading={loading}
        filters={filters}
        filterFields={localizedFilterFields}
        columns={columns}
        stats={[
          {
            title: l("筛选结果总数", "Filtered total"),
            value: data.summary.total,
          },
          {
            title: l("启用数据", "Enabled data"),
            value: data.summary.activeCount,
            prefix: <EyeOutlined />,
          },
          {
            title: l("禁用数据", "Disabled data"),
            value: data.summary.inactiveCount,
            prefix: <StopOutlined />,
          },
          {
            title: l("受限访问", "Restricted access"),
            value: data.summary.restrictedCount,
          },
        ]}
        rowName={(item) => item.name}
        drawerTitle={
          canChange
            ? l("存量数据配置", "Inventory data configuration")
            : l("数据可见范围", "Data visibility")
        }
        deleteTitle={l("删除存量数据", "Delete inventory data")}
        deleteDescription={l(
          "删除会移除数据资源登记和关联图层；用户导入的表或矢量图层会同步清理。请输入数据名称确认。",
          "Deleting removes the data-resource record and linked layers; user-imported tables or vector layers are cleaned up as well. Enter the data name to confirm.",
        )}
        ownerScopeLabel={l("上传者本人可见", "Visible to the uploader")}
        canMaintain={canChange}
        canDelete={canDelete}
        canExport={canExport}
        exportFormats={["csv", "xlsx"]}
        renderTable={renderGroupedTable}
        detailItems={(resource) => [
          { label: l("数据名称", "Data name"), value: resource.name },
          {
            label: l("所属项目标签", "Project tag"),
            value: <ProjectLabel id={resource.projectTagId} />,
          },
          {
            label: l("数据分类", "Data category"),
            value:
              resource.categoryPath.map((item) => item.name).join(" / ") ||
              l("待归类", "Pending classification"),
          },
          { label: l("类型", "Type"), value: dataTypeText(resource.dataType) },
          {
            label: l("状态", "Status"),
            value: (
              <Tag color={statusLabels[resource.status].color}>
                {english
                  ? resource.status === "active"
                    ? "Enabled"
                    : "Disabled"
                  : statusLabels[resource.status].text}
              </Tag>
            ),
          },
          {
            label: l("上传用户", "Uploader"),
            value: uploaderDisplayName(resource),
          },
          {
            label: l("数据大小", "Data size"),
            value: formatBytes(resource.sizeBytes ?? 0),
          },
          {
            label: l("数据条目数", "Data item count"),
            value: resource.itemCount ?? 0,
          },
        ]}
        formInitialValues={(resource) => initialVisualizationValues(resource)}
        renderFormItems={(resource, maintainable) => (
          <>
            <Form.Item label={l("所属项目标签", "Project tag")}>
              <ProjectLabel id={resource.projectTagId} />
              <Typography.Paragraph type="secondary">
                {l(
                  "归属在上传时指定；公开项目所有人可访问，其他项目仅对应成员和超管可访问。",
                  "Assigned during upload. Public is accessible to everyone; other projects are accessible to their members and super admins.",
                )}
              </Typography.Paragraph>
            </Form.Item>
            <Typography.Title level={5}>
              {l("基本信息", "Basic information")}
            </Typography.Title>
            <Form.Item
              name="resourceName"
              label={l("数据资源名称", "Data resource name")}
              rules={[
                {
                  required: true,
                  whitespace: true,
                  message: l(
                    "请输入数据资源名称",
                    "Enter a data resource name",
                  ),
                },
                {
                  max: 160,
                  message: l(
                    "数据资源名称不能超过 160 个字符",
                    "Data resource name must not exceed 160 characters",
                  ),
                },
              ]}
            >
              <Input disabled={!maintainable} />
            </Form.Item>
            <Typography.Title level={5}>
              {l("数据分类", "Data category")}
            </Typography.Title>
            <Form.Item
              name="categoryCode"
              label={l(
                "按坐标信息自动分类",
                "Geographic or non-geographic data",
              )}
              rules={[
                {
                  required: true,
                  message: l(
                    "请选择数据分类",
                    "Select an authoritative category",
                  ),
                },
              ]}
            >
              <Select
                showSearch
                optionFilterProp="label"
                disabled
                options={flattenTaxonomy(localizedTaxonomy)
                  .filter((node) => node.selectable)
                  .map((node) => ({
                    value: node.categoryCode,
                    label: node.path.join(" / "),
                  }))}
              />
            </Form.Item>
            <Typography.Title level={5}>
              {l("默认可视化方案", "Default visualization")}
            </Typography.Title>
            <Form.Item
              name="layerName"
              label={l("默认图层名称", "Default layer name")}
              rules={[
                {
                  required: true,
                  message: l(
                    "请输入默认图层名称",
                    "Enter a default layer name",
                  ),
                },
              ]}
            >
              <Input disabled={!maintainable} />
            </Form.Item>
            <Form.Item
              name="defaultVisible"
              label={l("默认显示", "Visible by default")}
              valuePropName="checked"
            >
              <Switch
                checkedChildren={l("显示", "Show")}
                unCheckedChildren={l("隐藏", "Hide")}
                disabled={!maintainable}
              />
            </Form.Item>
            <Form.Item
              name="ownerOnly"
              label={l("可见范围", "Visibility")}
              valuePropName="checked"
              extra={l(
                "关闭时项目组内所有成员可见；开启后仅上传者本人和超级管理员可见。",
                "When off, every member of the project can view it. When on, only the uploader and super administrators can view it.",
              )}
            >
              <Switch
                checkedChildren={l("仅自己", "Only me")}
                unCheckedChildren={l("项目组", "Project")}
                disabled={!resource.canManageAccess}
              />
            </Form.Item>
            {resource.dataType === "vector" && (
              <Form.Item
                name="pointColor"
                label={l("点位/主色", "Point / primary color")}
              >
                <Input type="color" disabled={!maintainable} />
              </Form.Item>
            )}
            <Form.Item
              name="symbolizationJson"
              label={l("矢量符号 JSON", "Vector symbolization JSON")}
            >
              <Input.TextArea
                rows={6}
                spellCheck={false}
                disabled={!maintainable}
              />
            </Form.Item>
            <Form.Item
              name="rasterRulesJson"
              label={l("栅格规则 JSON", "Raster rules JSON")}
            >
              <Input.TextArea
                rows={6}
                spellCheck={false}
                disabled={!maintainable}
              />
            </Form.Item>
          </>
        )}
        onFilterChange={(nextFilters) =>
          setFilters(nextFilters as AdminDataResourceFilters)
        }
        onPageChange={(current, pageSize) =>
          setFilters((currentFilters) => ({
            ...currentFilters,
            current,
            pageSize,
          }))
        }
        onSave={saveResourceSettings}
        onDelete={deleteResource}
        onExport={exportInventory}
      />
      <Modal
        title={l("新增资料夹（不控制访问权限）", "Add group")}
        open={Boolean(groupModal)}
        okText={l("新建", "Create")}
        okButtonProps={{ "aria-label": l("新建", "Create") }}
        cancelText={l("取消", "Cancel")}
        confirmLoading={savingGroup}
        onOk={saveGroupModal}
        onCancel={() => setGroupModal(null)}
      >
        <Input
          autoFocus
          allowClear
          value={groupName}
          placeholder={l("输入资料夹名称", "Enter a group name")}
          onChange={(event) => setGroupName(event.target.value)}
          onPressEnter={saveGroupModal}
        />
      </Modal>
    </>
  );
}

function prepareNestedTableColumns(
  columns: ColumnsType<AdminDataResource>,
): ColumnsType<AdminDataResource> {
  const sortableColumns = columns.map(addResourceColumnSorter);
  const actionIndex = sortableColumns.findIndex(
    (column) => column.key === "actions",
  );
  const nameIndex = sortableColumns.findIndex(
    (column) => column.key === "name",
  );
  if (actionIndex < 0 || nameIndex < 0 || actionIndex === nameIndex + 1) {
    return sortableColumns;
  }

  const nextColumns = [...sortableColumns];
  const [actionColumn] = nextColumns.splice(actionIndex, 1);
  if (!actionColumn) {
    return sortableColumns;
  }
  const currentNameIndex = nextColumns.findIndex(
    (column) => column.key === "name",
  );
  nextColumns.splice(currentNameIndex + 1, 0, actionColumn);
  return nextColumns;
}

function addResourceColumnSorter(
  column: ColumnsType<AdminDataResource>[number],
): ColumnsType<AdminDataResource>[number] {
  if ("children" in column) {
    return column;
  }
  const key = String(column.key ?? "");
  const fixedColumn = {
    ...column,
    ...(inventoryResourceColumnWidths[key]
      ? { width: inventoryResourceColumnWidths[key] }
      : {}),
    ...(inventoryEllipsisColumnKeys.has(key) ? { ellipsis: true } : {}),
  };
  if (column.key === "name") {
    return {
      ...fixedColumn,
      sorter: resourceColumnSorters.name,
    };
  }
  if (column.key === "actions") {
    return fixedColumn;
  }
  const sorter = resourceColumnSorters[key];
  return sorter ? { ...fixedColumn, sorter } : fixedColumn;
}

const resourceColumnSorters: Record<
  string,
  (left: AdminDataResource, right: AdminDataResource) => number
> = {
  name: (left, right) => compareText(left.name, right.name),
  dataType: (left, right) =>
    compareText(dataTypeLabels[left.dataType], dataTypeLabels[right.dataType]),
  dataSize: (left, right) =>
    left.sizeBytes - right.sizeBytes || left.itemCount - right.itemCount,
  status: (left, right) =>
    compareText(
      statusLabels[left.status].text,
      statusLabels[right.status].text,
    ),
  source: (left, right) =>
    compareText(left.source, right.source) ||
    compareText(left.provider, right.provider),
  uploader: (left, right) =>
    compareText(uploaderDisplayName(left), uploaderDisplayName(right)),
  dataDate: (left, right) =>
    compareText(left.dataDate ?? "", right.dataDate ?? ""),
  updatedAt: (left, right) =>
    Date.parse(left.updatedAt) - Date.parse(right.updatedAt),
};

function compareText(left: string, right: string): number {
  return left.localeCompare(right, "zh-CN");
}

function uploaderDisplayName(resource: AdminDataResource): string {
  return (
    resource.uploader?.displayName ||
    resource.uploader?.username ||
    resource.maintainer ||
    "未知"
  );
}

function initialVisualizationValues(
  resource: AdminDataResource,
): VisualizationFormValues {
  const visualization = resource.defaultVisualization;
  const layer = resource.defaultLayer;
  const symbolization: Record<string, unknown> =
    typeof visualization.symbolization === "object" &&
    visualization.symbolization !== null
      ? (visualization.symbolization as Record<string, unknown>)
      : (layer?.symbolization ?? {});
  const rasterRules: Record<string, unknown> =
    typeof visualization.rasterRules === "object" &&
    visualization.rasterRules !== null
      ? (visualization.rasterRules as Record<string, unknown>)
      : (layer?.rasterRules ?? {});
  return {
    resourceName: resource.name,
    categoryCode: resource.category?.code ?? "",
    layerName:
      textValue(visualization.layerName) || layer?.name || resource.name,
    defaultVisible: Boolean(
      visualization.defaultVisible ?? layer?.defaultVisible ?? false,
    ),
    ownerOnly: resource.ownerOnly,
    pointColor: textValue(symbolization.pointColor) || "#2f7d62",
    symbolizationJson: JSON.stringify(symbolization, null, 2),
    rasterRulesJson: JSON.stringify(rasterRules, null, 2),
    accessGroupIds: withFixedAccessScopes(
      resource.accessGroups.map((group) => group.id as AccessScopeId),
    ),
  };
}

function buildInventoryGroups(
  resources: AdminDataResource[],
  persistedGroups: AdminDataResourceGroup[],
  groupSummaries: InventoryGroupSummary[],
): InventoryGroup[] {
  const groupDefinitions: InventoryGroupDefinition[] = [
    allInventoryGroup,
    ...categoryInventoryGroups,
    unclassifiedInventoryGroup,
    ...persistedGroups.map((group) => ({
      id: group.id,
      name: group.name,
      kind: "custom" as const,
    })),
  ];
  const summaryByKey = new Map(
    groupSummaries.map((summary) => [summary.key, summary]),
  );
  const buildGroup = (group: InventoryGroupDefinition): InventoryGroup =>
    createInventoryGroup({
      ...group,
      summary: summaryByKey.get(inventoryGroupSummaryKey(group)),
      resources: resources.filter((resource) =>
        resourceBelongsToInventoryGroup(resource, group),
      ),
      subgroups: (group.children ?? []).map(buildGroup),
    });
  return groupDefinitions.map(buildGroup);
}

function createInventoryGroup({
  id,
  name,
  resources,
  kind,
  summary,
  subgroups,
}: {
  id: InventoryGroupId;
  name: string;
  resources: AdminDataResource[];
  kind: InventoryGroupKind;
  summary?: InventoryGroupSummary;
  subgroups: InventoryGroup[];
}): InventoryGroup {
  const activeCount = resources.filter(
    (resource) => resource.status === "active",
  ).length;
  return {
    id,
    name,
    resources,
    resourceCount: summary?.resourceCount ?? resources.length,
    enabled: resources.length > 0 && activeCount === resources.length,
    partiallyEnabled: activeCount > 0 && activeCount < resources.length,
    kind,
    subgroups,
    sizeBytes:
      summary?.sizeBytes ??
      resources.reduce(
        (total, resource) => total + (resource.sizeBytes ?? 0),
        0,
      ),
    itemCount:
      summary?.itemCount ??
      resources.reduce(
        (total, resource) => total + (resource.itemCount ?? 0),
        0,
      ),
  };
}

function inventoryGroupSummaryKey(group: InventoryGroupDefinition) {
  return group.kind === "custom" ? `__custom__:${group.id}` : String(group.id);
}

function resourceBelongsToInventoryGroup(
  resource: AdminDataResource,
  group: InventoryGroupDefinition,
) {
  if (group.kind === "all") return true;
  if (group.kind === "unclassified") {
    return resource.classificationStatus === "pending" || !resource.category;
  }
  if (group.kind === "category-root" || group.kind === "category-leaf") {
    return resource.categoryPath.some(
      (item) => item.code === group.categoryCode,
    );
  }
  return resource.inventoryGroupId === group.id;
}

function inventoryGroupKindLabel(kind: InventoryGroupKind) {
  if (kind === "all") return "汇总";
  if (kind === "category-root") return "一级大类";
  if (kind === "category-leaf") return "业务小类";
  if (kind === "unclassified") return "待治理";
  return "自定义";
}

function inventoryGroupKindColor(kind: InventoryGroupKind) {
  if (kind === "all") return "blue";
  if (kind === "category-root") return "green";
  if (kind === "category-leaf") return "cyan";
  if (kind === "unclassified") return "orange";
  return "default";
}

function canAcceptInventoryDrop(group: InventoryGroup) {
  return group.kind === "all" || group.kind === "custom";
}

function groupStatus(enabled: boolean): AdminDataResource["status"] {
  return enabled ? "active" : "inactive";
}

function exportFilters(filters: AdminDataResourceFilters) {
  const { current, pageSize, ...rest } = filters;
  void current;
  void pageSize;
  return rest;
}

function textValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function currentDefaultOpacity(resource: AdminDataResource) {
  return Number(
    resource.defaultVisualization.defaultOpacity ??
      resource.defaultLayer?.defaultOpacity ??
      85,
  );
}

function parseJsonObject(
  value: string | undefined,
  label: string,
  english: boolean,
) {
  if (!value?.trim()) {
    return {};
  }
  try {
    const parsed = JSON.parse(value);
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      Array.isArray(parsed)
    ) {
      throw new Error(
        english ? `${label} must be a JSON object` : `${label}必须是 JSON 对象`,
      );
    }
    return parsed as Record<string, unknown>;
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(
        english
          ? `${label} is invalid: ${error.message}`
          : `${label}格式错误：${error.message}`,
      );
    }
    throw new Error(english ? `${label} is invalid` : `${label}格式错误`);
  }
}

function formatBytes(value: number) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let current = value;
  let unitIndex = 0;
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024;
    unitIndex += 1;
  }
  return `${current.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}
