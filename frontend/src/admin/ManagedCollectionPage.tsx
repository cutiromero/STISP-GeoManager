import { ProjectLabel } from "../projects/ProjectLabel";
import {
  DeleteOutlined,
  DownloadOutlined,
  FilterOutlined,
  ReloadOutlined,
  SaveOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { ProCard, StatisticCard } from "@ant-design/pro-components";
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TablePaginationConfig } from "antd/es/table/interface";
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { useEnglishLanguage, localText } from "../i18n/useEnglishLanguage";
import type { AdminDataResourceList } from "../types";
import {
  type AccessScopeId,
  ownerAccessScopeId,
  realAccessGroupIds,
  withFixedAccessScopes,
  selectableAccessScopeIds,
} from "./accessScopes";

export {
  ownerAccessScopeId,
  realAccessGroupIds,
  selectableAccessScopeIds,
  withFixedAccessScopes,
};
export type { AccessScopeId };

export type AccessGroup =
  AdminDataResourceList["availableAccessGroups"][number];

export type ManagedFormValues = {
  accessGroupIds: AccessScopeId[];
} & Record<string, unknown>;

export interface ManagedItemBase {
  projectTagId?: number;
  id: number;
  status: string;
  accessGroups: AccessGroup[];
  canManageAccess: boolean;
  updatedAt: string;
}

export interface FilterField {
  name: string;
  label: string;
  kind: "input" | "select" | "date";
  options?: { value: string; label: string }[];
}

export interface ManagedStat {
  title: string;
  value: number;
  prefix?: ReactNode;
}

export interface ManagedCollectionTableRenderArgs<
  TItem extends ManagedItemBase,
> {
  items: TItem[];
  loading: boolean;
  tableColumns: ColumnsType<TItem>;
  pagination: TablePaginationConfig;
}

interface ManagedCollectionPageProps<TItem extends ManagedItemBase> {
  className?: string;
  items: TItem[];
  total: number;
  accessGroups: AccessGroup[];
  loading: boolean;
  filters: Record<string, unknown>;
  filterFields: FilterField[];
  columns: ColumnsType<TItem>;
  stats: ManagedStat[];
  rowName: (item: TItem) => string;
  drawerTitle: string;
  deleteTitle: string;
  deleteDescription: ReactNode;
  ownerScopeLabel: string;
  accessScopeNotice?: ReactNode;
  canMaintain: boolean;
  canMaintainItem?: (item: TItem) => boolean;
  canDelete?: boolean;
  canDeleteItem?: (item: TItem) => boolean;
  canExport?: boolean;
  exportFormats?: string[];
  detailItems: (item: TItem) => { label: string; value: ReactNode }[];
  formInitialValues: (item: TItem) => ManagedFormValues;
  renderFormItems: (item: TItem, canMaintain: boolean) => ReactNode;
  renderTable?: (args: ManagedCollectionTableRenderArgs<TItem>) => ReactNode;
  onFilterChange: (filters: Record<string, unknown>) => void;
  onPageChange: (current: number, pageSize: number) => void;
  onSave: (item: TItem, values: ManagedFormValues) => Promise<TItem | void>;
  onDelete: (item: TItem, confirmationName: string) => Promise<void>;
  onExport?: (format: string) => Promise<void>;
}

export default function ManagedCollectionPage<TItem extends ManagedItemBase>({
  className,
  items,
  total,
  accessGroups,
  loading,
  filters,
  filterFields,
  columns,
  stats,
  rowName,
  drawerTitle,
  deleteTitle,
  deleteDescription,
  canMaintain,
  canMaintainItem,
  canDelete = canMaintain,
  canDeleteItem,
  canExport = false,
  exportFormats = [],
  detailItems,
  formInitialValues,
  renderFormItems,
  renderTable,
  onFilterChange,
  onPageChange,
  onSave,
  onDelete,
  onExport,
}: ManagedCollectionPageProps<TItem>) {
  const english = useEnglishLanguage();
  const l = (zh: string, en: string) => localText(english, zh, en);
  const [filterForm] = Form.useForm();
  const [editForm] = Form.useForm<ManagedFormValues>();
  const [selectedItem, setSelectedItem] = useState<TItem | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<TItem | null>(null);
  const [deleteText, setDeleteText] = useState("");
  const [deleting, setDeleting] = useState(false);

  const tableColumns = useMemo<ColumnsType<TItem>>(
    () => [
      ...columns,
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
        width: 164,
        render: (_, record) => {
          const recordCanMaintain =
            canMaintain && (canMaintainItem?.(record) ?? true);
          const recordCanDelete =
            canDelete && (canDeleteItem?.(record) ?? true);
          return (
            <Space>
              <Tooltip title={l("配置", "Configure")}>
                <Button
                  aria-label={l(
                    `配置${rowName(record)}`,
                    `Configure ${rowName(record)}`,
                  )}
                  icon={<SettingOutlined />}
                  onClick={() => openDrawer(record)}
                  disabled={!recordCanMaintain && !record.canManageAccess}
                />
              </Tooltip>
              <Tooltip
                title={
                  recordCanDelete
                    ? l("删除", "Delete")
                    : l(
                        "当前用户无删除权限",
                        "You do not have delete permission",
                      )
                }
              >
                <Button
                  aria-label={l(
                    `删除${rowName(record)}`,
                    `Delete ${rowName(record)}`,
                  )}
                  danger
                  icon={<DeleteOutlined />}
                  disabled={!recordCanDelete}
                  onClick={() => setDeleteTarget(record)}
                />
              </Tooltip>
            </Space>
          );
        },
      },
    ],
    [
      canDelete,
      canDeleteItem,
      canMaintain,
      canMaintainItem,
      columns,
      english,
      rowName,
    ],
  );

  const selectedCanMaintain = Boolean(
    selectedItem && canMaintain && (canMaintainItem?.(selectedItem) ?? true),
  );

  const tablePagination: TablePaginationConfig = {
    current: Number(filters.current ?? 1),
    pageSize: Number(filters.pageSize ?? 10),
    total,
    showSizeChanger: true,
    showTotal: (nextTotal) => l(`共 ${nextTotal} 条`, `${nextTotal} items`),
    onChange: onPageChange,
  };

  function submitFilters(values: Record<string, unknown>) {
    onFilterChange({
      ...compactFilters(values),
      current: 1,
      pageSize: filters.pageSize,
    });
  }

  function resetFilters() {
    filterForm.resetFields();
    onFilterChange({ current: 1, pageSize: filters.pageSize });
  }

  function openDrawer(item: TItem) {
    setSelectedItem(item);
    const initialValues = formInitialValues(item);
    editForm.setFieldsValue({
      ...initialValues,
      accessGroupIds: selectableAccessScopeIds(
        initialValues.accessGroupIds,
        accessGroups,
      ),
    });
    setDrawerOpen(true);
  }

  async function saveSelected() {
    if (!selectedItem) {
      return;
    }
    try {
      const values = await editForm.validateFields();
      setSaving(true);
      const updated = await onSave(selectedItem, {
        ...values,
        accessGroupIds: selectedItem.accessGroups.map((group) => group.id),
      });
      if (updated) {
        setSelectedItem(updated);
      }
      setDrawerOpen(false);
    } finally {
      setSaving(false);
    }
  }

  async function confirmDelete() {
    if (
      !deleteTarget ||
      !canDelete ||
      !(canDeleteItem?.(deleteTarget) ?? true)
    ) {
      return;
    }
    setDeleting(true);
    try {
      await onDelete(deleteTarget, deleteText);
      setDeleteTarget(null);
      setDeleteText("");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className={`admin-page-stack admin-inventory-page ${className ?? ""}`}>
      <ProCard className="admin-section-card">
        <Form form={filterForm} layout="vertical" onFinish={submitFilters}>
          <div className="inventory-toolbar">
            <Form.Item name="q" className="inventory-search-item">
              <Input
                allowClear
                placeholder={l(
                  "按名称、来源或所属用户快速检索",
                  "Search by name, source, or owner",
                )}
                onPressEnter={() => filterForm.submit()}
              />
            </Form.Item>
            <Space wrap>
              <Button
                type="primary"
                icon={<FilterOutlined />}
                onClick={() => filterForm.submit()}
              >
                {l("筛选", "Filter")}
              </Button>
              <Button icon={<ReloadOutlined />} onClick={resetFilters}>
                {l("重置", "Reset")}
              </Button>
              {exportFormats.map((format) => (
                <Button
                  key={format}
                  icon={<DownloadOutlined />}
                  disabled={!canExport}
                  onClick={() => onExport?.(format)}
                >
                  {format.toUpperCase()}
                </Button>
              ))}
            </Space>
          </div>
          <div className="inventory-filter-grid">
            {filterFields.map((field) => (
              <Form.Item key={field.name} name={field.name} label={field.label}>
                {field.kind === "select" ? (
                  <Select allowClear options={field.options ?? []} />
                ) : (
                  <Input
                    allowClear
                    type={field.kind === "date" ? "date" : undefined}
                  />
                )}
              </Form.Item>
            ))}
          </div>
        </Form>
      </ProCard>

      <StatisticCard.Group className="inventory-stat-group">
        {stats.map((stat) => (
          <StatisticCard
            key={stat.title}
            statistic={{
              title: stat.title,
              value: stat.value,
              prefix: stat.prefix,
            }}
          />
        ))}
      </StatisticCard.Group>

      <ProCard className="admin-section-card inventory-table-card">
        <div className="inventory-table-scroll">
          {renderTable ? (
            renderTable({
              items,
              loading,
              tableColumns,
              pagination: tablePagination,
            })
          ) : (
            <Table<TItem>
              rowKey="id"
              loading={loading}
              columns={tableColumns}
              dataSource={items}
              scroll={{ x: 1280 }}
              pagination={tablePagination}
            />
          )}
        </div>
      </ProCard>

      <Drawer
        size={560}
        title={drawerTitle}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        extra={
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            disabled={!selectedCanMaintain && !selectedItem?.canManageAccess}
            onClick={saveSelected}
          >
            {l("保存", "Save")}
          </Button>
        }
      >
        {selectedItem && (
          <Space orientation="vertical" size={18} className="drawer-stack">
            <Descriptions column={1} size="small" bordered>
              {detailItems(selectedItem).map((item) => (
                <Descriptions.Item key={item.label} label={item.label}>
                  {item.value}
                </Descriptions.Item>
              ))}
            </Descriptions>
            <Form
              form={editForm}
              layout="vertical"
              className="inventory-drawer-form"
            >
              <ProjectLabel id={selectedItem.projectTagId} />
              <Alert
                type="info"
                title="访问范围由项目标签决定；仅对应项目成员和超管可见。公开项目所有人可读。"
              />
              {renderFormItems(selectedItem, selectedCanMaintain)}
            </Form>
          </Space>
        )}
      </Drawer>

      <Modal
        title={deleteTitle}
        open={Boolean(deleteTarget)}
        confirmLoading={deleting}
        okText={l("确认删除", "Confirm delete")}
        okButtonProps={{
          danger: true,
          disabled: deleteText !== (deleteTarget ? rowName(deleteTarget) : ""),
        }}
        onOk={confirmDelete}
        onCancel={() => {
          setDeleteTarget(null);
          setDeleteText("");
        }}
      >
        <Typography.Paragraph>{deleteDescription}</Typography.Paragraph>
        <Typography.Text strong>
          {deleteTarget ? rowName(deleteTarget) : ""}
        </Typography.Text>
        <Input
          value={deleteText}
          onChange={(event) => setDeleteText(event.target.value)}
          placeholder={l("输入完整名称", "Enter the full name")}
          style={{ marginTop: 12 }}
        />
      </Modal>
    </div>
  );
}

function compactFilters(values: Record<string, unknown>) {
  return Object.fromEntries(
    Object.entries(values).filter(
      ([, value]) => value !== undefined && value !== "",
    ),
  );
}
