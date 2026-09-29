import { Alert, Button, Card, Progress, Space, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type { AgentComputeTaskTracking } from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";

const statusNames: Record<string, string> = {
  queued: "排队中",
  validating: "检查输入",
  running: "计算中",
  cancelling: "正在停止",
  cancelled: "已停止",
  succeeded: "计算完成",
  failed: "计算失败",
  interrupted: "已中断",
};
const importNames: Record<string, string> = {
  none: "待入库",
  queued: "等待入库",
  running: "正在入库",
  ready: "已入库",
  failed: "入库失败",
};

export default function RunComputeTasks({
  runId,
  refreshKey,
}: {
  runId: number;
  refreshKey: string;
}) {
  const ui = useComputeText();
  const [items, setItems] = useState<AgentComputeTaskTracking[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number>();
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await agentApi.computeTasks(runId);
        if (disposed) return;
        setItems(result.items);
        setError("");
        if (
          result.items.some(
            ({ task, trackingStatus }) =>
              ["queued", "validating", "running", "cancelling"].includes(
                task.status,
              ) ||
              ["waiting_compute", "waiting_import"].includes(trackingStatus) ||
              task.outputs.some((output) =>
                ["queued", "running"].includes(output.importStatus),
              ),
          )
        ) {
          timer = setTimeout(poll, document.hidden ? 6000 : 1800);
        }
      } catch (e) {
        if (!disposed)
          setError(
            e instanceof Error
              ? e.message
              : ui("读取任务状态失败", "Could not load task status"),
          );
      }
    };
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [runId, refreshKey, revision, ui]);
  const importOutput = async (id: number) => {
    setBusy(id);
    try {
      await computeApi.importOutput(id);
      const result = await agentApi.computeTasks(runId);
      setItems(result.items);
      setRevision((value) => value + 1);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "入库失败");
    } finally {
      setBusy(undefined);
    }
  };
  if (!items.length)
    return error ? <Alert type="warning" title={error} /> : null;
  return (
    <div
      className="agent-compute-cards"
      aria-label={ui("实时计算任务", "Live compute tasks")}
    >
      <Typography.Text type="secondary">
        {ui(
          "以下为平台当前状态，自动更新。",
          "Current platform status, updated automatically.",
        )}
      </Typography.Text>
      {error && <Alert type="warning" title={error} />}
      {items.map(({ task, autoImport, detail }) => (
        <Card
          key={task.id}
          size="small"
          title={task.name}
          extra={
            <Tag
              color={
                task.status === "succeeded"
                  ? "green"
                  : task.status === "failed"
                    ? "red"
                    : "blue"
              }
            >
              {ui(statusNames[task.status] ?? task.status)}
            </Tag>
          }
        >
          <Space direction="vertical" style={{ width: "100%" }}>
            <Typography.Text>{task.stage}</Typography.Text>
            {["queued", "validating", "running"].includes(task.status) && (
              <Progress percent={task.progress} size="small" />
            )}
            <Typography.Text type="secondary">
              {detail}
              {autoImport
                ? ui(" · 完成后自动入库", " · Automatic import enabled")
                : ""}
            </Typography.Text>
            {task.error && <Alert type="error" title={task.error} />}
            {task.outputs.map((output) => (
              <Space key={output.id} wrap>
                <span>{output.label}</span>
                <Tag
                  color={output.importStatus === "ready" ? "green" : undefined}
                >
                  {ui(importNames[output.importStatus] ?? output.importStatus)}
                </Tag>
                {output.resourceId && (
                  <Typography.Text>
                    {ui("数据资源", "Data resource")} #{output.resourceId}
                  </Typography.Text>
                )}
                {task.status === "succeeded" &&
                  !output.expired &&
                  output.kind !== "archive" &&
                  ["none", "failed"].includes(output.importStatus) && (
                    <Button
                      size="small"
                      loading={busy === output.id}
                      onClick={() => void importOutput(output.id)}
                    >
                      {ui("将结果入库", "Import result")}
                    </Button>
                  )}
                {output.importError && (
                  <Typography.Text type="danger">
                    {output.importError}
                  </Typography.Text>
                )}
              </Space>
            ))}
          </Space>
        </Card>
      ))}
    </div>
  );
}
