import {
  CheckCircleOutlined,
  EnvironmentOutlined,
  DatabaseOutlined,
} from "@ant-design/icons";
import { Alert, Button, Progress, Tag } from "antd";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type {
  AgentComputeTaskTracking,
  ComputeOutput,
  ComputeTask,
} from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";

const activeStates = ["queued", "validating", "running", "cancelling"];
const statusNames: Record<string, [string, string]> = {
  queued: ["排队中", "Queued"],
  validating: ["检查输入", "Checking inputs"],
  running: ["计算中", "Computing"],
  cancelling: ["正在停止", "Stopping"],
  cancelled: ["已停止", "Stopped"],
  succeeded: ["计算完成", "Computed"],
  failed: ["计算失败", "Failed"],
  interrupted: ["已中断", "Interrupted"],
};
const importNames: Record<string, [string, string]> = {
  none: ["待入库", "Not imported"],
  queued: ["等待入库", "Import queued"],
  running: ["正在入库", "Importing"],
  ready: ["已入库", "Imported"],
  failed: ["入库失败", "Import failed"],
};

function shouldPoll(items: AgentComputeTaskTracking[]) {
  return items.some(
    ({ task, trackingStatus }) =>
      activeStates.includes(task.status) ||
      ["waiting_compute", "waiting_import"].includes(trackingStatus) ||
      task.outputs.some((output) =>
        ["queued", "running"].includes(output.importStatus),
      ),
  );
}

function ResultMetadata({ output }: { output: ComputeOutput }) {
  const ui = useComputeText();
  const data = output.metadata;
  const parts: string[] = [];
  if (typeof data.width === "number" && typeof data.height === "number")
    parts.push(`${data.width} × ${data.height}`);
  if (typeof data.bands === "number")
    parts.push(ui(`${data.bands} 波段`, `${data.bands} band(s)`));
  if (typeof data.crs === "string") parts.push(data.crs);
  if (typeof data.features === "number")
    parts.push(ui(`${data.features} 个要素`, `${data.features} features`));
  if (typeof data.rows === "number")
    parts.push(ui(`${data.rows} 行`, `${data.rows} rows`));
  return parts.length ? (
    <span className="agent-compute-muted">{parts.join(" · ")}</span>
  ) : null;
}

function TaskInputs({ task }: { task: ComputeTask }) {
  const ui = useComputeText();
  const names = task.inputs
    .map((input) => String(input.name ?? ""))
    .filter(Boolean);
  const params = task.version.manifest.parameters.flatMap((parameter) => {
    const value = task.parameters[parameter.key];
    return value === undefined
      ? []
      : [
          parameter.type === "band"
            ? `${ui(parameter.label)} ${ui(`第 ${String(value)} 波段`, `Band ${String(value)}`)}`
            : `${ui(parameter.label)} ${String(value)}`,
        ];
  });
  return names.length || params.length ? (
    <p className="agent-compute-input-summary">
      {[...names, ...params].join(" · ")}
    </p>
  ) : null;
}

export default function RunComputeTasks({
  runId,
  refreshKey,
}: {
  runId: number;
  refreshKey: string;
}) {
  const ui = useComputeText();
  const navigate = useNavigate();
  const [items, setItems] = useState<AgentComputeTaskTracking[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number>();
  const [revision, setRevision] = useState(0);
  const alive = useRef(true);
  const importing = useRef(false);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    let disposed = false;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await agentApi.computeTasks(runId);
        if (disposed) return;
        failures = 0;
        setItems(result.items);
        setError("");
        if (shouldPoll(result.items))
          timer = setTimeout(poll, document.hidden ? 6000 : 1800);
      } catch (reason) {
        if (disposed) return;
        setError(reason instanceof Error ? reason.message : "读取任务状态失败");
        if (
          typeof reason === "object" &&
          reason !== null &&
          "status" in reason &&
          [401, 403].includes(Number(reason.status))
        ) {
          setItems([]);
          return;
        }
        failures += 1;
        timer = setTimeout(poll, Math.min(15000, 3000 * failures));
      }
    };
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [runId, refreshKey, revision]);

  const importOutput = async (output: ComputeOutput, task: ComputeTask) => {
    if (importing.current) return;
    importing.current = true;
    setBusy(output.id);
    try {
      await computeApi.importOutput(output.id, { name: task.name });
      if (!alive.current) return;
      setRevision((value) => value + 1);
      setError("");
    } catch (reason) {
      if (alive.current)
        setError(reason instanceof Error ? reason.message : "入库失败");
    } finally {
      importing.current = false;
      if (alive.current) setBusy(undefined);
    }
  };
  if (!items.length)
    return error ? <Alert type="warning" title={error} /> : null;
  return (
    <div
      className="agent-compute-cards"
      aria-label={ui("实时计算任务", "Live compute tasks")}
    >
      {error && (
        <Alert
          type="warning"
          title={error}
          description={ui(
            "正在重新获取最新状态。",
            "Reconnecting for current status.",
          )}
        />
      )}
      {items.map(({ task, autoImport }) => (
        <section
          className="agent-compute-result"
          key={task.id}
          aria-label={task.name}
        >
          <div className="agent-compute-result-heading">
            <div>
              <span className="agent-compute-eyebrow">
                {ui(task.algorithmName)}
              </span>
              <strong>{task.name}</strong>
            </div>
            <Tag
              color={
                task.status === "succeeded"
                  ? "blue"
                  : task.status === "failed"
                    ? "error"
                    : "processing"
              }
            >
              {ui(...(statusNames[task.status] ?? [task.status, task.status]))}
            </Tag>
          </div>
          <TaskInputs task={task} />
          {activeStates.includes(task.status) && (
            <div className="agent-compute-live" role="status">
              <span>{task.stage}</span>
              <Progress
                percent={task.progress}
                size="small"
                strokeColor="#407ca6"
              />
            </div>
          )}
          {task.error && <Alert type="error" title={task.error} showIcon />}
          {task.status === "succeeded" && (
            <p className="agent-compute-complete">
              <CheckCircleOutlined aria-hidden="true" />
              {ui("计算完成，结果已保存。", "Computed and saved.")}
            </p>
          )}
          {task.outputs.map((output) => (
            <div className="agent-compute-output" key={output.id}>
              <div className="agent-compute-output-title">
                <strong>{ui(output.label)}</strong>
                <span>
                  {output.expired
                    ? ui("临时结果已过期", "Temporary result expired")
                    : ui(
                        ...(importNames[output.importStatus] ?? [
                          output.importStatus,
                          output.importStatus,
                        ]),
                      )}
                </span>
              </div>
              <ResultMetadata output={output} />
              {output.importStatus === "ready" && (
                <div className="agent-compute-location">
                  <DatabaseOutlined aria-hidden="true" />
                  <div>
                    <strong>{output.resourceName || task.name}</strong>
                    <span>
                      {output.resourceLocation ||
                        ui(
                          "已存入当前项目的数据资源",
                          "Saved in this project's data resources",
                        )}
                    </span>
                  </div>
                </div>
              )}
              <div className="agent-compute-result-actions">
                {task.status === "succeeded" &&
                  (!output.expired ||
                    Boolean(output.resourceId && output.mapUrl)) &&
                  output.kind === "raster" && (
                    <Button
                      icon={<EnvironmentOutlined aria-hidden="true" />}
                      onClick={() =>
                        navigate(
                          output.mapUrl ||
                            `/map?computeOutputId=${output.id}&projectTagId=${task.projectTagId}`,
                        )
                      }
                    >
                      {ui("在地理工作台查看", "View in map workspace")}
                    </Button>
                  )}
                {output.resourceId ? (
                  <Button
                    onClick={() =>
                      navigate(
                        `/resources/catalog?resourceId=${output.resourceId}`,
                      )
                    }
                  >
                    {ui("打开入库数据", "Open imported data")}
                  </Button>
                ) : task.status === "succeeded" &&
                  !output.expired &&
                  output.kind !== "archive" &&
                  ["none", "failed"].includes(output.importStatus) ? (
                  <Button
                    type="primary"
                    icon={<DatabaseOutlined aria-hidden="true" />}
                    loading={busy === output.id}
                    disabled={busy !== undefined && busy !== output.id}
                    onClick={() => void importOutput(output, task)}
                  >
                    {output.importStatus === "failed"
                      ? ui("重试入库", "Retry import")
                      : ui("将结果入库", "Import result")}
                  </Button>
                ) : null}
              </div>
              {output.importError && (
                <Alert title={output.importError} type="error" showIcon />
              )}
              {!output.resourceId &&
                output.importStatus === "none" &&
                !output.expired && (
                  <span className="agent-compute-muted">
                    {autoImport
                      ? ui("已按您的要求安排入库", "Import was requested")
                      : ui(
                          "可先预览，选择入库后会登记到数据资源。",
                          "Preview first; import when you are ready.",
                        )}
                  </span>
                )}
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
