import {
  App,
  Alert,
  Button,
  Descriptions,
  Drawer,
  Modal,
  Progress,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  computeApi,
  downloadComputeFile,
  type ComputeOutput,
  type ComputeRuntimeStatus,
  type ComputeTask,
} from "../api/compute";
import type { ComputePreview } from "../api/generated/types.gen";
import { createUuid } from "../utils/uuid";
import { importStatusLabels, statusText, useComputeText } from "./ui";

export function OutputTable({
  outputs,
  permissions,
  onChanged,
}: {
  outputs: ComputeOutput[];
  permissions: ComputeRuntimeStatus["permissions"];
  onChanged: () => void;
}) {
  const ui = useComputeText();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [preview, setPreview] = useState<ComputePreview | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const previewRows = useMemo(
    () =>
      preview?.rows.map((row) => ({
        _row: createUuid(),
        ...Object.fromEntries(
          preview.columns.map((field, c) => [field, row[c]]),
        ),
      })) ?? [],
    [preview],
  );
  const perform = async (id: number, fn: () => Promise<unknown>) => {
    setBusy(id);
    try {
      await fn();
      if (alive.current) onChanged();
    } catch (e) {
      if (alive.current && e instanceof Error) message.error(e.message);
    } finally {
      if (alive.current) setBusy(null);
    }
  };
  return (
    <>
      <Table
        rowKey="id"
        size="small"
        dataSource={outputs}
        pagination={false}
        scroll={{ x: 720 }}
        columns={[
          {
            title: ui("结果", "Result"),
            key: "name",
            render: (_, output) => (
              <Space orientation="vertical" size={0}>
                <Typography.Text strong>{ui(output.label)}</Typography.Text>
                <Typography.Text type="secondary">
                  {output.fileName} / {(output.sizeBytes / 1024).toFixed(1)} KiB
                </Typography.Text>
              </Space>
            ),
          },
          { title: ui("类型", "Type"), dataIndex: "kind" },
          {
            title: ui("状态", "Status"),
            key: "status",
            render: (_, output) => (
              <Space orientation="vertical" size={0}>
                <Tag
                  color={
                    output.expired || output.importStatus === "deleted"
                      ? "default"
                      : output.importStatus === "ready"
                        ? "success"
                        : "processing"
                  }
                >
                  {output.expired
                    ? ui("临时文件已过期", "Temporary file expired")
                    : statusText(ui, output.importStatus, importStatusLabels)}
                </Tag>
                {output.importError && (
                  <Typography.Text type="danger">
                    {output.importError}
                  </Typography.Text>
                )}
              </Space>
            ),
          },
          {
            title: ui("操作", "Actions"),
            key: "actions",
            render: (_, output) => (
              <Space wrap>
                <Button
                  size="small"
                  disabled={output.expired}
                  loading={busy === output.id}
                  onClick={() =>
                    perform(output.id, async () => {
                      const data = await computeApi.preview(output.id);
                      if (alive.current) setPreview(data);
                    })
                  }
                >
                  {ui("预览", "Preview")}
                </Button>
                <Button
                  size="small"
                  disabled={output.expired || !permissions.download_outputs}
                  onClick={() =>
                    perform(output.id, () =>
                      downloadComputeFile(output.downloadUrl, output.fileName),
                    )
                  }
                >
                  {ui("下载", "Download")}
                </Button>
                {output.resourceId ? (
                  <Button
                    size="small"
                    onClick={() =>
                      navigate(
                        `/resources/catalog?resourceId=${output.resourceId}`,
                      )
                    }
                  >
                    {ui("查看已入库数据", "Open imported data")}
                  </Button>
                ) : (
                  <Button
                    size="small"
                    disabled={
                      output.expired ||
                      output.kind === "archive" ||
                      !permissions.import_outputs ||
                      output.importStatus === "deleted" ||
                      ["queued", "running"].includes(output.importStatus)
                    }
                    loading={busy === output.id}
                    onClick={() =>
                      perform(output.id, () =>
                        computeApi.importOutput(output.id),
                      )
                    }
                  >
                    {output.importStatus === "failed"
                      ? ui("重试入库", "Retry import")
                      : ui("存入数据资源", "Import into data resources")}
                  </Button>
                )}
              </Space>
            ),
          },
        ]}
      />
      <Modal
        open={!!preview}
        title={ui("结果预览（最多100行）", "Result preview (up to 100 rows)")}
        width={960}
        footer={null}
        onCancel={() => setPreview(null)}
      >
        {preview && (
          <>
            <Descriptions
              size="small"
              column={2}
              items={Object.entries(preview.metadata).map(([key, value]) => ({
                key,
                label: key,
                children:
                  typeof value === "object"
                    ? JSON.stringify(value)
                    : String(value),
              }))}
            />
            {preview.columns.length > 0 ? (
              <Table
                size="small"
                rowKey="_row"
                scroll={{ x: true }}
                pagination={{ pageSize: 10 }}
                columns={preview.columns.map((field) => ({
                  key: field,
                  title: field,
                  dataIndex: field,
                  render: (value) => <span>{String(value ?? "")}</span>,
                }))}
                dataSource={previewRows}
              />
            ) : (
              <Alert
                type="info"
                title={ui(
                  "地理结果入库后可加载到工作台；图件及报告可下载查看。",
                  "Import geographic results to view them in the map workspace. Download images or reports to view them.",
                )}
                style={{ marginTop: 16 }}
              />
            )}
          </>
        )}
      </Modal>
    </>
  );
}

export default function ComputeTaskDetail({
  id,
  permissions,
  onClose,
  onCopy,
}: {
  id: string;
  permissions: ComputeRuntimeStatus["permissions"];
  onClose: () => void;
  onCopy: (task: ComputeTask) => void;
}) {
  const ui = useComputeText();
  const { message } = App.useApp();
  const [task, setTask] = useState<ComputeTask | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const next = await computeApi.task(id);
        if (live) {
          setTask(next);
          setError("");
        }
      } catch (e) {
        if (live && e instanceof Error) setError(e.message);
      } finally {
        if (live) timer = setTimeout(refresh, 4000);
      }
    };
    void refresh();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [id, revision]);
  const action = async (value: "cancel" | "retry") => {
    try {
      await computeApi.action(id, value);
      message.success(ui("操作已提交", "Action submitted"));
      setRevision((r) => r + 1);
    } catch (e) {
      if (e instanceof Error) message.error(e.message);
    }
  };
  return (
    <Drawer
      open
      width={900}
      title={task?.name ?? ui("任务详情", "Task details")}
      onClose={onClose}
    >
      {error && <Alert title={error} type="error" />}
      {task && (
        <Space orientation="vertical" size={20} style={{ width: "100%" }}>
          <Space wrap>
            <Tag
              color={
                task.status === "succeeded"
                  ? "success"
                  : task.status === "failed"
                    ? "error"
                    : "processing"
              }
            >
              {statusText(ui, task.status)}
            </Tag>
            <Typography.Text>{task.stage}</Typography.Text>
            {task.trial && <Tag>{ui("试运行", "Trial")}</Tag>}
          </Space>
          <Progress
            percent={task.progress}
            status={
              task.status === "failed"
                ? "exception"
                : task.status === "succeeded"
                  ? "success"
                  : "active"
            }
          />
          {task.error && <Alert type="error" title={task.error} />}
          <Descriptions
            column={2}
            items={[
              {
                key: "id",
                label: ui("任务编号", "Task ID"),
                children: task.id,
              },
              {
                key: "algorithm",
                label: ui("算法版本", "Algorithm version"),
                children: ui(task.algorithmName) + " " + task.version.version,
              },
              {
                key: "owner",
                label: ui("提交人", "Owner"),
                children: task.ownerName,
              },
              {
                key: "created",
                label: ui("提交时间", "Created"),
                children: new Date(task.createdAt).toLocaleString(),
              },
              {
                key: "attempts",
                label: ui("执行次数", "Attempts"),
                children: task.attemptCount,
              },
              {
                key: "params",
                label: ui("参数", "Parameters"),
                children: JSON.stringify(task.parameters),
              },
            ]}
          />
          <Space>
            {["queued", "running", "validating"].includes(task.status) &&
              permissions.cancel_own_task && (
                <Button danger onClick={() => action("cancel")}>
                  {ui("取消任务", "Cancel task")}
                </Button>
              )}
            {["failed", "cancelled", "interrupted"].includes(task.status) &&
              permissions.submit_task && (
                <Button onClick={() => action("retry")}>
                  {ui("重新排队", "Retry")}
                </Button>
              )}
            <Button onClick={() => onCopy(task)}>
              {ui("复制参数新建任务", "Create task with these parameters")}
            </Button>
          </Space>
          <Typography.Title level={5}>
            {ui("输入来源", "Input provenance")}
          </Typography.Title>
          {task.inputs.map((input) => (
            <div key={String(input.key)}>
              <Typography.Text strong>
                {String(input.name ?? input.key)}
              </Typography.Text>
              {input.resourceId === null && (
                <Tag>
                  {ui(
                    "原目录数据已删除，请重新选择输入",
                    "Catalog data deleted; select a new input",
                  )}
                </Tag>
              )}
              <Typography.Paragraph
                type="secondary"
                copyable={!!input.checksum}
              >
                {String(
                  input.checksum ||
                    ui(
                      "开始执行时固定输入摘要",
                      "Input checksum is fixed when execution starts",
                    ),
                )}
              </Typography.Paragraph>
            </div>
          ))}
          <Typography.Title level={5}>
            {ui("计算结果", "Outputs")}
          </Typography.Title>
          <OutputTable
            outputs={task.outputs}
            permissions={permissions}
            onChanged={() => setRevision((r) => r + 1)}
          />
        </Space>
      )}
    </Drawer>
  );
}
