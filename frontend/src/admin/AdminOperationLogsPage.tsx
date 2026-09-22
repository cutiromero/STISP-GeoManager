import { DownloadOutlined, ReloadOutlined } from "@ant-design/icons";
import type {
  ActionType,
  ProColumns,
  ProFormInstance,
} from "@ant-design/pro-components";
import { ProTable } from "@ant-design/pro-components";
import {
  App,
  AutoComplete,
  Button,
  Card,
  Empty,
  Select,
  Space,
  Spin,
  Tabs,
  Tag,
  Typography,
} from "antd";
import type { TabsProps } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAppContext } from "../contexts/AppContext";
import type {
  AdminOperationLog,
  AdminOperationLogQuery,
  AdminSystemLog,
} from "../types";
import { downloadTextFile } from "../utils/download";
import { operationLogsToCsv } from "./data";

interface OperationLogTableQuery extends AdminOperationLogQuery {
  occurredAt?: unknown[];
}

interface OperationLogHints {
  operators: string[];
  modules: string[];
}

const resultText: Record<string, string> = {
  success: "成功",
  warning: "告警",
  failed: "失败",
};

const resultColor: Record<string, string> = {
  success: "success",
  warning: "warning",
  failed: "error",
};

export default function AdminOperationLogsPage() {
  const actionRef = useRef<ActionType>(null);
  const formRef = useRef<ProFormInstance | undefined>(undefined);
  const { message } = App.useApp();
  const { user } = useAppContext();
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const [exporting, setExporting] = useState(false);
  const [hints, setHints] = useState<OperationLogHints>({
    operators: [],
    modules: [],
  });
  const columns = useMemo(() => buildColumns(hints, english), [english, hints]);

  useEffect(() => {
    let mounted = true;
    api
      .adminOperationLogs({ current: 1, pageSize: 500 })
      .then((result) => {
        if (!mounted) return;
        setHints({
          operators: uniqueValues(result.items.map((item) => item.operator)),
          modules: uniqueValues(result.items.map((item) => item.module)),
        });
      })
      .catch(() => {
        if (!mounted) return;
        setHints({ operators: [], modules: [] });
      });
    return () => {
      mounted = false;
    };
  }, []);

  async function exportLogs() {
    setExporting(true);
    try {
      const query = buildLogQuery(
        (formRef.current?.getFieldsValue() ?? {}) as OperationLogTableQuery,
      );
      const firstPage = await api.adminOperationLogs({
        ...query,
        current: 1,
        pageSize: 1,
      });
      const result =
        firstPage.total <= firstPage.items.length
          ? firstPage
          : await api.adminOperationLogs({
              ...query,
              current: 1,
              pageSize: firstPage.total,
            });
      downloadTextFile(operationLogsToCsv(result.items), "operation-logs.csv");
      message.success(
        english ? "Operation-log export generated" : "已生成操作日志导出文件",
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to export operation logs"
            : "操作日志导出失败",
      );
    } finally {
      setExporting(false);
    }
  }

  const operationLogTable = (
    <ProTable<AdminOperationLog, OperationLogTableQuery>
      className="admin-table"
      actionRef={actionRef}
      formRef={formRef}
      rowKey="id"
      columns={columns}
      cardBordered
      options={false}
      search={{
        labelWidth: 92,
        span: { xs: 24, sm: 12, md: 8, lg: 8, xl: 6, xxl: 6 },
      }}
      pagination={{
        pageSize: 5,
        showSizeChanger: false,
      }}
      scroll={{ x: 1200 }}
      request={async (params) => {
        const result = await api.adminOperationLogs(buildLogQuery(params));
        return {
          data: result.items,
          total: result.total,
          success: true,
        };
      }}
      headerTitle={english ? "Log entries" : "日志列表"}
      toolBarRender={() => [
        <Button
          key="reload"
          icon={<ReloadOutlined />}
          onClick={() => actionRef.current?.reload()}
        >
          {english ? "Refresh" : "刷新"}
        </Button>,
        <Button
          key="export"
          type="primary"
          icon={<DownloadOutlined />}
          loading={exporting}
          onClick={exportLogs}
        >
          {english ? "Export logs" : "导出日志"}
        </Button>,
      ]}
      tableAlertRender={({ selectedRowKeys }) => (
        <Space size={12}>
          {english ? "Selected" : "已选择"}{" "}
          <strong>{selectedRowKeys.length}</strong>{" "}
          {english ? "log entries" : "条日志"}
        </Space>
      )}
      rowSelection={{}}
    />
  );

  const tabItems: TabsProps["items"] = [
    {
      key: "operations",
      label: english ? "Operation logs" : "操作日志",
      children: operationLogTable,
    },
  ];
  if (user?.permissions.canViewSystemLogs) {
    tabItems.push({
      key: "system",
      label: english ? "System logs" : "系统日志",
      children: <AdminSystemLogsPanel />,
    });
  }

  return <Tabs className="admin-logs-tabs" items={tabItems} />;
}

function AdminSystemLogsPanel() {
  const { message } = App.useApp();
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const [log, setLog] = useState<AdminSystemLog | null>(null);
  const [selectedFile, setSelectedFile] = useState("");
  const [lineCount, setLineCount] = useState(500);
  const [loading, setLoading] = useState(false);

  const loadSystemLogs = useCallback(
    async (file: string, lines: number) => {
      setLoading(true);
      try {
        const result = await api.adminSystemLogs({
          file: file || undefined,
          lines,
        });
        setLog(result);
        setSelectedFile(result.selectedFile);
      } catch (error) {
        message.error(
          error instanceof Error
            ? error.message
            : english
              ? "Failed to load system logs"
              : "系统日志加载失败",
        );
      } finally {
        setLoading(false);
      }
    },
    [english, message],
  );

  useEffect(() => {
    void loadSystemLogs(selectedFile, lineCount);
  }, [lineCount, loadSystemLogs, selectedFile]);

  const fileOptions = (log?.files ?? []).map((file) => ({
    label: english
      ? `${file.name} (${formatBytes(file.sizeBytes)})`
      : `${file.name}（${formatBytes(file.sizeBytes)}）`,
    value: file.name,
  }));

  return (
    <Card
      className="system-log-card"
      title={english ? "Backend runtime logs" : "后台运行日志"}
      extra={
        <Space wrap>
          <Select
            value={selectedFile || undefined}
            options={fileOptions}
            placeholder={english ? "Select log file" : "选择日志文件"}
            style={{ width: 260 }}
            disabled={!fileOptions.length}
            onChange={setSelectedFile}
          />
          <Select
            value={lineCount}
            style={{ width: 120 }}
            options={[
              { label: english ? "200 lines" : "200 行", value: 200 },
              { label: english ? "500 lines" : "500 行", value: 500 },
              { label: english ? "1000 lines" : "1000 行", value: 1000 },
              { label: english ? "2000 lines" : "2000 行", value: 2000 },
            ]}
            onChange={setLineCount}
          />
          <Button
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={() => loadSystemLogs(selectedFile, lineCount)}
          >
            {english ? "Refresh" : "刷新"}
          </Button>
        </Space>
      }
    >
      <Spin spinning={loading}>
        {!log?.files.length ? (
          <Empty
            description={english ? "No system log files" : "暂无系统日志文件"}
          />
        ) : (
          <div className="system-log-viewer">
            <Typography.Text type="secondary">
              {english ? "Current file" : "当前文件"}：
              {log.selectedFile || (english ? "None selected" : "未选择")}
              {english
                ? `; latest ${log.lines} lines`
                : `，最近 ${log.lines} 行`}
            </Typography.Text>
            <pre>
              {log.content ||
                (english
                  ? "The current log file has no displayable content"
                  : "当前日志文件没有可显示内容")}
            </pre>
          </div>
        )}
      </Spin>
    </Card>
  );
}

function buildColumns(
  hints: OperationLogHints,
  english = false,
): ProColumns<AdminOperationLog>[] {
  return [
    {
      title: english ? "Time" : "操作时间",
      dataIndex: "occurredAt",
      valueType: "dateTimeRange",
      width: 190,
      sorter: (a, b) => a.occurredAt.localeCompare(b.occurredAt),
      render: (_, record) => record.occurredAt,
    },
    {
      title: english ? "Operator" : "操作用户",
      dataIndex: "operator",
      width: 140,
      ellipsis: true,
      formItemRender: (_schema, config) => (
        <AutoComplete
          allowClear
          value={config.value}
          onChange={config.onChange}
          options={toOptions(hints.operators)}
          placeholder={english ? "Enter or select user" : "输入或选择用户"}
          filterOption={filterOption}
        />
      ),
    },
    {
      title: english ? "Module" : "模块",
      dataIndex: "module",
      width: 130,
      ellipsis: true,
      formItemRender: (_schema, config) => (
        <AutoComplete
          allowClear
          value={config.value}
          onChange={config.onChange}
          options={toOptions(hints.modules)}
          placeholder={english ? "Enter or select module" : "输入或选择模块"}
          filterOption={filterOption}
        />
      ),
    },
    {
      title: english ? "Action" : "动作",
      dataIndex: "action",
      width: 150,
      ellipsis: true,
    },
    {
      title: english ? "Result" : "结果",
      dataIndex: "result",
      width: 110,
      valueType: "select",
      valueEnum: {
        success: { text: english ? "Success" : "成功", status: "Success" },
        warning: { text: english ? "Warning" : "告警", status: "Warning" },
        failed: { text: english ? "Failed" : "失败", status: "Error" },
      },
      render: (_, record) => (
        <Tag color={resultColor[record.result] ?? "default"}>
          {english
            ? ({ success: "Success", warning: "Warning", failed: "Failed" }[
                record.result
              ] ?? record.result)
            : (resultText[record.result] ?? record.result)}
        </Tag>
      ),
    },
    {
      title: english ? "IP address" : "IP 地址",
      dataIndex: "ipAddress",
      width: 140,
      search: false,
    },
    {
      title: english ? "Keyword" : "关键词",
      dataIndex: "keyword",
      hideInTable: true,
    },
    {
      title: english ? "Summary" : "摘要",
      dataIndex: "summary",
      width: 360,
      search: false,
      ellipsis: true,
    },
  ];
}

function buildLogQuery(params: OperationLogTableQuery): AdminOperationLogQuery {
  const [startTime, endTime] = params.occurredAt ?? [];
  return {
    current: params.current,
    pageSize: params.pageSize,
    operator: params.operator,
    module: params.module,
    action: params.action,
    result: params.result,
    keyword: params.keyword,
    startTime: formatQueryDate(startTime),
    endTime: formatQueryDate(endTime),
  };
}

function formatQueryDate(value: unknown): string | undefined {
  if (!value) return undefined;
  if (
    typeof value === "object" &&
    "format" in value &&
    typeof value.format === "function"
  ) {
    return value.format("YYYY-MM-DD HH:mm:ss");
  }
  return String(value);
}

function uniqueValues(values: string[]) {
  return Array.from(
    new Set(values.map((value) => value.trim()).filter(Boolean)),
  ).sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
}

function toOptions(values: string[]) {
  return values.map((value) => ({ value }));
}

function filterOption(inputValue: string, option?: { value?: string }) {
  return (option?.value ?? "").toLowerCase().includes(inputValue.toLowerCase());
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
