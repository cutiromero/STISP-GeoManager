import {
  CloudOutlined,
  DatabaseOutlined,
  DownloadOutlined,
  HddOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import { ProCard } from "@ant-design/pro-components";
import {
  Alert,
  App,
  Button,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Progress,
  Select,
  Skeleton,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api/client";
import { localText, useEnglishLanguage } from "../i18n/useEnglishLanguage";
import type {
  AdminDashboard,
  AdminBackupOverview,
  AdminBackupRun,
  AdminBackupSettings,
  AdminBackupSettingsUpdate,
  BackupPlanType,
  BackupTargetType,
} from "../types";
import { downloadBlob } from "../utils/download";
import { startSequentialPolling } from "../utils/sequentialPolling";

interface BackupFormValues {
  plans: {
    platform: PlanFormValues;
    research: PlanFormValues;
  };
  local: {
    directory: string;
  };
  objectStorage: {
    provider: "s3_compatible";
    endpoint: string;
    region: string;
    bucket: string;
    prefix: string;
    accessKeyId: string;
    secretAccessKey?: string;
  };
}

interface PlanFormValues {
  enabled: boolean;
  dailyAt: string;
  target: BackupTargetType;
  retentionCount: number;
  includeLogs: boolean;
}

const planMeta: Record<
  BackupPlanType,
  { title: string; icon: ReactNode; scope: string; source: string }
> = {
  research: {
    title: "科研数据备份",
    icon: <HddOutlined />,
    scope: "vector、raster、gene、table",
    source: "科研数据根目录",
  },
  platform: {
    title: "平台数据备份",
    icon: <DatabaseOutlined />,
    scope: "SQLite 数据库、上传附件、系统配置、可选运行日志",
    source: "业务数据根目录",
  },
};

const statusText: Record<string, string> = {
  queued: "等待中",
  running: "运行中",
  success: "成功",
  failed: "失败",
};

const statusColor: Record<string, string> = {
  queued: "default",
  running: "processing",
  success: "success",
  failed: "error",
};

export default function AdminDataBackupPage() {
  const { message } = App.useApp();
  const english = useEnglishLanguage();
  const l = (zh: string, en: string) => localText(english, zh, en);
  const planTitle = (planType: BackupPlanType) =>
    planType === "research"
      ? l("科研数据备份", "Research data backup")
      : l("平台数据备份", "Platform data backup");
  const planSource = (planType: BackupPlanType) =>
    planType === "research"
      ? l("科研数据根目录", "Research data root")
      : l("业务数据根目录", "Application data root");
  const planScope = (planType: BackupPlanType) =>
    planType === "research"
      ? "vector, raster, gene, table"
      : l(
          "SQLite 数据库、上传附件、系统配置、可选运行日志",
          "SQLite database, uploaded files, system configuration, and optional runtime logs",
        );
  const localizedTargetOptions = [
    {
      label: l("云端对象存储", "Cloud object storage"),
      value: "object_storage",
    },
    { label: l("本地目录", "Local directory"), value: "local" },
  ];
  const [form] = Form.useForm<BackupFormValues>();
  const [overview, setOverview] = useState<AdminBackupOverview | null>(null);
  const [dashboard, setDashboard] = useState<AdminDashboard | null>(null);
  const [runs, setRuns] = useState<AdminBackupRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testingTarget, setTestingTarget] = useState<BackupTargetType | null>(
    null,
  );
  const [startingPlan, setStartingPlan] = useState<BackupPlanType | null>(null);
  const [pollRunId, setPollRunId] = useState<number | null>(null);
  const startRequestInFlightRef = useRef(false);

  const activeRun = useMemo(() => {
    const runsById = new Map<number, AdminBackupRun>();
    for (const run of overview?.activeRuns ?? []) {
      runsById.set(run.id, run);
    }
    for (const run of runs) {
      runsById.set(run.id, run);
    }
    return [...runsById.values()]
      .sort((left, right) => right.id - left.id)
      .find((run) => run.status === "queued" || run.status === "running");
  }, [overview?.activeRuns, runs]);

  const loadData = useCallback(
    async (signal?: AbortSignal) => {
      const [overviewData, runData, dashboardData] = await Promise.all([
        api.adminBackupOverview({ signal }),
        api.adminBackupRuns({ current: 1, pageSize: 20 }, { signal }),
        api.adminDashboard("day", { signal }).catch(() => null),
      ]);
      if (signal?.aborted) return;
      setOverview(overviewData);
      setRuns(runData.items);
      setDashboard(dashboardData);
      form.setFieldsValue(settingsToFormValues(overviewData.settings));
    },
    [form],
  );

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    loadData(controller.signal)
      .catch((error) => {
        if (controller.signal.aborted) return;
        message.error(
          error instanceof Error
            ? error.message
            : l("数据备份配置加载失败", "Failed to load backup configuration"),
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [english, loadData, message]);

  useEffect(() => {
    if (activeRun && pollRunId !== activeRun.id) {
      setPollRunId(activeRun.id);
    }
  }, [activeRun, pollRunId]);

  useEffect(() => {
    if (!pollRunId) return;
    return startSequentialPolling(
      async (signal) => {
        try {
          const run = await api.adminBackupRun(pollRunId, { signal });
          if (signal.aborted) return false;
          setRuns((current) => mergeRun(current, run));
          if (run.status === "success" || run.status === "failed") {
            await loadData(signal);
            if (!signal.aborted) {
              setPollRunId(null);
            }
            return false;
          }
          return true;
        } catch {
          if (!signal.aborted) {
            setPollRunId(null);
          }
          return false;
        }
      },
      { intervalMs: 2500 },
    );
  }, [loadData, pollRunId]);

  async function handleSave() {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const updated = await api.updateAdminBackupSettings(
        formValuesToPayload(values),
      );
      form.setFieldsValue(settingsToFormValues(updated));
      setOverview((current) =>
        current ? { ...current, settings: updated } : current,
      );
      message.success(l("数据备份配置已保存", "Backup configuration saved"));
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : l("保存失败", "Save failed"),
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleTestTarget(targetType: BackupTargetType) {
    const values = form.getFieldsValue(true);
    setTestingTarget(targetType);
    try {
      const result = await api.testAdminBackupTarget({
        targetType,
        local: targetType === "local" ? values.local : undefined,
        objectStorage:
          targetType === "object_storage"
            ? cleanObjectStoragePayload(values.objectStorage)
            : undefined,
      });
      if (result.status === "success") {
        message.success(result.message);
      } else {
        message.error(result.message);
      }
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("连接测试失败", "Connection test failed"),
      );
    } finally {
      setTestingTarget(null);
    }
  }

  async function handleStartBackup(planType: BackupPlanType) {
    if (activeRun || startRequestInFlightRef.current) {
      return;
    }
    startRequestInFlightRef.current = true;
    const values = form.getFieldsValue(true);
    const plan = values.plans[planType];
    setStartingPlan(planType);
    try {
      const run = await api.createAdminBackupRun({
        planType,
        targetType: plan.target,
        includeLogs: planType === "platform" ? plan.includeLogs : false,
      });
      setRuns((current) => mergeRun(current, run));
      if (run.status === "queued" || run.status === "running") {
        setPollRunId(run.id);
      }
      message.success(l("备份任务已创建", "Backup task created"));
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("备份任务创建失败", "Failed to create backup task"),
      );
    } finally {
      startRequestInFlightRef.current = false;
      setStartingPlan(null);
    }
  }

  const handleDownload = useCallback(
    async (run: AdminBackupRun) => {
      try {
        const result = await api.downloadAdminBackupRun(run.id);
        downloadBlob(result.blob, result.filename || run.archiveName);
      } catch (error) {
        message.error(
          error instanceof Error
            ? error.message
            : l("备份下载失败", "Backup download failed"),
        );
      }
    },
    [english, message],
  );

  const columns = useMemo<ColumnsType<AdminBackupRun>>(
    () => backupRunColumns(handleDownload, english),
    [english, handleDownload],
  );
  const visibleInventoryScope = dashboard?.cards.dataOverview?.visibleResources;

  if (loading) {
    return (
      <ProCard className="admin-section-card">
        <Skeleton active paragraph={{ rows: 10 }} />
      </ProCard>
    );
  }

  if (!overview) {
    return (
      <Empty
        description={l(
          "数据备份配置加载失败",
          "Failed to load backup configuration",
        )}
      />
    );
  }

  return (
    <Form
      form={form}
      layout="vertical"
      className="admin-page-stack admin-backup-page"
    >
      <Alert
        type="info"
        showIcon
        title={l(
          "数据备份属于系统级维护功能",
          "Data backup is a system maintenance function",
        )}
        description={l(
          "推荐使用云端对象存储作为异地备份目标；本地目录仅适合作为临时导出或内网备份选项，不能替代容灾。",
          "Cloud object storage is recommended for off-site backups. A local directory is suitable only for temporary exports or intranet backups and is not a disaster-recovery substitute.",
        )}
      />

      <div className="backup-summary-grid">
        {overview.summaries.map((summary) => (
          <ProCard key={summary.planType} className="admin-section-card">
            <Space orientation="vertical" size={8}>
              <Space>
                {planMeta[summary.planType].icon}
                <Typography.Text strong>
                  {english ? planTitle(summary.planType) : summary.label}
                </Typography.Text>
              </Space>
              <Typography.Text type="secondary">
                {planSource(summary.planType)}
              </Typography.Text>
              <Typography.Title level={4} className="backup-summary-value">
                {formatBytes(summary.sizeBytes)}
              </Typography.Title>
              <Typography.Text type="secondary">
                {l(
                  `${summary.fileCount} 个可备份文件`,
                  `${summary.fileCount} files available for backup`,
                )}
              </Typography.Text>
              {summary.planType === "platform" && visibleInventoryScope ? (
                <Typography.Text type="secondary">
                  {l(
                    `存量登记 ${formatBytes(visibleInventoryScope.totalSizeBytes)} / ${visibleInventoryScope.totalResources} 项 / ${visibleInventoryScope.totalItemCount} 条`,
                    `Inventory: ${formatBytes(visibleInventoryScope.totalSizeBytes)} / ${visibleInventoryScope.totalResources} resources / ${visibleInventoryScope.totalItemCount} items`,
                  )}
                </Typography.Text>
              ) : null}
            </Space>
          </ProCard>
        ))}
        <ProCard className="admin-section-card">
          <Space orientation="vertical" size={8}>
            <Space>
              <CloudOutlined />
              <Typography.Text strong>
                {l("云端目标", "Cloud target")}
              </Typography.Text>
            </Space>
            <Typography.Text type="secondary">
              {overview.settings.objectStorage.configured
                ? overview.settings.objectStorage.bucket
                : l("未配置完整", "Incomplete configuration")}
            </Typography.Text>
            <Tag
              color={
                overview.settings.objectStorage.configured
                  ? "success"
                  : "warning"
              }
            >
              {overview.settings.objectStorage.configured
                ? l("可测试连接", "Ready to test")
                : l("待配置", "Needs configuration")}
            </Tag>
          </Space>
        </ProCard>
      </div>

      {activeRun ? (
        <ProCard
          title={l("当前备份任务", "Current backup task")}
          className="admin-section-card"
        >
          <Space orientation="vertical" size={12} className="backup-full-width">
            <Space wrap>
              <Tag color={statusColor[activeRun.status]}>
                {backupStatusText(activeRun.status, english)}
              </Tag>
              <Typography.Text>{activeRun.archiveName}</Typography.Text>
            </Space>
            <Progress percent={activeRun.progressPercent} />
            <Typography.Text type="secondary">
              {lastItem(activeRun.messages ?? []) ||
                l("等待任务进度", "Waiting for task progress")}
            </Typography.Text>
          </Space>
        </ProCard>
      ) : null}

      <ProCard
        title={l("备份目标", "Backup targets")}
        className="admin-section-card"
        extra={
          <Space wrap>
            <Button
              icon={<ReloadOutlined />}
              loading={testingTarget === "local"}
              onClick={() => handleTestTarget("local")}
            >
              {l("测试本地目录", "Test local directory")}
            </Button>
            <Button
              icon={<CloudOutlined />}
              loading={testingTarget === "object_storage"}
              onClick={() => handleTestTarget("object_storage")}
            >
              {l("测试云端目标", "Test cloud target")}
            </Button>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={handleSave}
            >
              {l("保存配置", "Save configuration")}
            </Button>
          </Space>
        }
      >
        <div className="backup-target-grid">
          <div>
            <Typography.Title level={5}>
              {l("本地备份", "Local backup")}
            </Typography.Title>
            <Form.Item
              name={["local", "directory"]}
              label={l("本地备份目录", "Local backup directory")}
              extra={l(
                "留空时使用业务数据根目录 backups/local/。",
                "Leave empty to use backups/local/ under the application data root.",
              )}
            >
              <Input
                placeholder={l(
                  "留空使用默认目录",
                  "Leave empty to use the default directory",
                )}
              />
            </Form.Item>
          </div>
          <div>
            <Typography.Title level={5}>
              {l("云端对象存储", "Cloud object storage")}
            </Typography.Title>
            <div className="backup-form-grid">
              <Form.Item
                name={["objectStorage", "provider"]}
                label={l("服务类型", "Service type")}
              >
                <Select
                  options={[
                    {
                      label: l(
                        "S3 兼容对象存储",
                        "S3-compatible object storage",
                      ),
                      value: "s3_compatible",
                    },
                  ]}
                />
              </Form.Item>
              <Form.Item name={["objectStorage", "endpoint"]} label="Endpoint">
                <Input placeholder="https://s3.example.com" />
              </Form.Item>
              <Form.Item name={["objectStorage", "region"]} label="Region">
                <Input placeholder="cn-north-1" />
              </Form.Item>
              <Form.Item name={["objectStorage", "bucket"]} label="Bucket">
                <Input placeholder="geomanager-backups" />
              </Form.Item>
              <Form.Item name={["objectStorage", "prefix"]} label="Prefix">
                <Input placeholder="prod/" />
              </Form.Item>
              <Form.Item
                name={["objectStorage", "accessKeyId"]}
                label="Access Key ID"
              >
                <Input />
              </Form.Item>
              <Form.Item
                name={["objectStorage", "secretAccessKey"]}
                label="Secret Access Key"
                extra={
                  overview.settings.objectStorage.secretConfigured
                    ? l(
                        `已配置：${overview.settings.objectStorage.secretPreview}`,
                        `Configured: ${overview.settings.objectStorage.secretPreview}`,
                      )
                    : l("未配置 Secret", "Secret not configured")
                }
              >
                <Input.Password
                  placeholder={l(
                    "不修改时留空",
                    "Leave empty to keep the current secret",
                  )}
                  autoComplete="new-password"
                />
              </Form.Item>
            </div>
          </div>
        </div>
      </ProCard>

      <div className="backup-card-grid">
        {(["research", "platform"] as BackupPlanType[]).map((planType) => (
          <ProCard
            key={planType}
            className="admin-section-card backup-plan-card"
            title={
              <Space size={8}>
                {planMeta[planType].icon}
                <span>{planTitle(planType)}</span>
              </Space>
            }
            extra={
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                loading={startingPlan === planType}
                disabled={Boolean(activeRun) || startingPlan !== null}
                onClick={() => handleStartBackup(planType)}
              >
                {l("立即备份", "Back up now")}
              </Button>
            }
          >
            <Descriptions
              size="small"
              column={1}
              items={[
                {
                  key: "source",
                  label: l("数据来源", "Data source"),
                  children: planSource(planType),
                },
                {
                  key: "scope",
                  label: l("备份范围", "Backup scope"),
                  children: planScope(planType),
                },
              ]}
            />
            <div className="backup-plan-form">
              <Form.Item
                name={["plans", planType, "enabled"]}
                label={l("启用自动备份", "Enable automatic backups")}
                valuePropName="checked"
              >
                <Switch
                  checkedChildren={l("开", "On")}
                  unCheckedChildren={l("关", "Off")}
                />
              </Form.Item>
              <Form.Item
                name={["plans", planType, "dailyAt"]}
                label={l("每日时间", "Daily time")}
                rules={[
                  {
                    pattern: /^([01]\d|2[0-3]):[0-5]\d$/,
                    message: l(
                      "请输入 HH:mm 格式",
                      "Enter a time in HH:mm format",
                    ),
                  },
                ]}
              >
                <Input placeholder="02:00" />
              </Form.Item>
              <Form.Item
                name={["plans", planType, "target"]}
                label={l("备份目标", "Backup target")}
              >
                <Select options={localizedTargetOptions} />
              </Form.Item>
              <Form.Item
                name={["plans", planType, "retentionCount"]}
                label={l("保留份数", "Retention count")}
              >
                <InputNumber
                  min={1}
                  max={365}
                  className="backup-number-input"
                />
              </Form.Item>
              {planType === "platform" ? (
                <Form.Item
                  name={["plans", planType, "includeLogs"]}
                  label={l("包含运行日志", "Include runtime logs")}
                  valuePropName="checked"
                >
                  <Switch
                    checkedChildren={l("是", "Yes")}
                    unCheckedChildren={l("否", "No")}
                  />
                </Form.Item>
              ) : null}
            </div>
          </ProCard>
        ))}
      </div>

      <ProCard
        title={l("备份历史", "Backup history")}
        className="admin-section-card"
      >
        <Table<AdminBackupRun>
          rowKey="id"
          columns={columns}
          dataSource={runs}
          pagination={{ pageSize: 8 }}
          scroll={{ x: 1180 }}
        />
      </ProCard>
    </Form>
  );
}

function settingsToFormValues(settings: AdminBackupSettings): BackupFormValues {
  return {
    plans: settings.plans,
    local: settings.local,
    objectStorage: {
      provider: settings.objectStorage.provider,
      endpoint: settings.objectStorage.endpoint,
      region: settings.objectStorage.region,
      bucket: settings.objectStorage.bucket,
      prefix: settings.objectStorage.prefix,
      accessKeyId: settings.objectStorage.accessKeyId,
      secretAccessKey: "",
    },
  };
}

function formValuesToPayload(
  values: BackupFormValues,
): AdminBackupSettingsUpdate {
  return {
    plans: {
      platform: values.plans.platform,
      research: {
        ...values.plans.research,
        includeLogs: false,
      },
    },
    local: {
      directory: values.local.directory ?? "",
    },
    objectStorage: cleanObjectStoragePayload(values.objectStorage),
  };
}

function cleanObjectStoragePayload(
  value: BackupFormValues["objectStorage"],
): AdminBackupSettingsUpdate["objectStorage"] {
  const payload: NonNullable<AdminBackupSettingsUpdate["objectStorage"]> = {
    provider: value.provider,
    endpoint: value.endpoint ?? "",
    region: value.region ?? "",
    bucket: value.bucket ?? "",
    prefix: value.prefix ?? "",
    accessKeyId: value.accessKeyId ?? "",
  };
  if (value.secretAccessKey?.trim()) {
    payload.secretAccessKey = value.secretAccessKey.trim();
  }
  return payload;
}

function backupRunColumns(
  onDownload: (run: AdminBackupRun) => void,
  english = false,
): ColumnsType<AdminBackupRun> {
  const l = (zh: string, en: string) => localText(english, zh, en);
  return [
    {
      title: l("备份类型", "Backup type"),
      dataIndex: "planType",
      width: 120,
      render: (value: BackupPlanType) =>
        value === "platform"
          ? l("平台数据", "Platform data")
          : l("科研数据", "Research data"),
    },
    {
      title: l("目标", "Target"),
      dataIndex: "targetType",
      width: 120,
      render: (value: BackupTargetType) =>
        value === "local"
          ? l("本地目录", "Local directory")
          : l("云端对象存储", "Cloud object storage"),
    },
    {
      title: l("状态", "Status"),
      dataIndex: "status",
      width: 110,
      render: (value: string) => (
        <Tag color={statusColor[value] ?? "default"}>
          {backupStatusText(value, english)}
        </Tag>
      ),
    },
    {
      title: l("触发方式", "Trigger"),
      dataIndex: "trigger",
      width: 110,
      render: (value: string) =>
        value === "scheduled" ? l("自动", "Scheduled") : l("手动", "Manual"),
    },
    {
      title: l("归档文件", "Archive file"),
      dataIndex: "archiveName",
      width: 260,
      ellipsis: true,
    },
    {
      title: l("大小", "Size"),
      dataIndex: "sizeBytes",
      width: 110,
      render: (value: number) => formatBytes(value),
    },
    {
      title: l("目标路径", "Target path"),
      dataIndex: "objectKey",
      width: 300,
      ellipsis: true,
      render: (_, record) => record.objectKey || record.localPath || "-",
    },
    {
      title: l("创建时间", "Created at"),
      dataIndex: "createdAt",
      width: 190,
      render: (value: string) =>
        new Date(value).toLocaleString(english ? "en-US" : "zh-CN"),
    },
    {
      title: l("操作", "Actions"),
      key: "actions",
      fixed: "right",
      width: 110,
      render: (_, record) =>
        record.targetType === "local" && record.status === "success" ? (
          <Button
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => onDownload(record)}
          >
            {l("下载", "Download")}
          </Button>
        ) : null,
    },
  ];
}

function backupStatusText(status: string, english: boolean) {
  if (!english) return statusText[status] ?? status;
  return (
    (
      {
        queued: "Queued",
        running: "Running",
        success: "Success",
        failed: "Failed",
      } as Record<string, string>
    )[status] ?? status
  );
}

function mergeRun(runs: AdminBackupRun[], run: AdminBackupRun) {
  const next = runs.filter((item) => item.id !== run.id);
  return [run, ...next].sort((left, right) => right.id - left.id);
}

function lastItem(values: string[]) {
  return values.length ? values[values.length - 1] : "";
}

function formatBytes(value: number) {
  if (!value) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}
