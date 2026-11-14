import { CheckCircleOutlined } from "@ant-design/icons";
import { Alert, Collapse, Progress, Tag } from "antd";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type {
  AgentComputeTaskTracking,
  ComputeOutput,
  ComputeTask,
} from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";
import type { LiveActivity } from "./agentActivity";
import ComputeQualitySummary from "./ComputeQualitySummary";
import WorkflowDeliverables from "./WorkflowDeliverables";

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

function shouldPoll(items: AgentComputeTaskTracking[]) {
  return items.some(
    (item) =>
      activeStates.includes(item.task.status) ||
      (item.task.status === "succeeded" &&
        item.task.outputs.some((output) =>
          ["queued", "running"].includes(output.importStatus),
        )) ||
      computeTasksActivity([item]).state === "working",
  );
}

export function computeTasksActivity(
  items: AgentComputeTaskTracking[],
  activityTaskId?: string,
): LiveActivity {
  const selected = activityTaskId
    ? items.filter(({ task }) => task.id === activityTaskId)
    : items;
  if (!selected.length)
    return { state: "working", label: "正在读取计算进度", detail: "" };
  const activities = selected.map(
    ({ task, trackingStatus, autoImport, detail }) => {
      if (["failed", "cancelled", "interrupted"].includes(task.status))
        return {
          state: "stopped" as const,
          label: task.status === "failed" ? "计算失败" : "计算已停止",
          detail: task.error || detail,
        };
      if (["blocked", "failed"].includes(trackingStatus))
        return {
          state: "stopped" as const,
          label: "任务需要处理",
          detail,
        };
      if (activeStates.includes(task.status))
        return {
          state: "working" as const,
          label:
            task.status === "queued"
              ? "正在等待计算"
              : task.status === "validating"
                ? "正在检查输入"
                : task.status === "cancelling"
                  ? "正在停止计算"
                  : "算法正在计算",
          detail: task.stage || detail,
        };
      if (task.status !== "succeeded")
        return { state: "working" as const, label: "正在读取计算进度", detail };
      const failedImport = task.outputs.find(
        (output) => output.importStatus === "failed",
      );
      if (failedImport)
        return {
          state: "stopped" as const,
          label: "计算完成，入库失败",
          detail: failedImport.importError || detail,
        };
      if (
        task.outputs.length &&
        task.outputs.every((output) => output.importStatus === "ready")
      )
        return {
          state: "complete" as const,
          label: "计算与入库已完成",
          detail,
        };
      if (
        task.outputs.some((output) =>
          ["queued", "running"].includes(output.importStatus),
        ) ||
        (autoImport &&
          ["waiting_compute", "waiting_import"].includes(trackingStatus))
      )
        return {
          state: "working" as const,
          label: "正在保存计算成果",
          detail,
        };
      return {
        state: "complete" as const,
        label: "计算已完成",
        detail,
      };
    },
  );
  return (
    activities.find(({ state }) => state === "stopped") ??
    activities.find(({ state }) => state === "working") ??
    activities[0]!
  );
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
      {[...names, ...params].join(" / ")}
    </p>
  ) : null;
}

export default function RunComputeTasks({
  runId,
  taskIds,
  autoImport = false,
  refreshKey,
  reviewing = false,
  taskDisplayNames,
  activityTaskId,
  onActivityChange,
  compact = false,
  display = "default",
  terminal = false,
  report,
  primaryTaskIds,
  visibleOutputIds,
  visibleOutputKinds,
}: (
  | {
      runId: number;
      taskIds?: never;
      autoImport?: never;
    }
  | {
      runId?: never;
      taskIds: string[];
      autoImport?: boolean;
    }
) & {
  refreshKey: string;
  reviewing?: boolean;
  taskDisplayNames?: Record<string, string>;
  activityTaskId?: string;
  onActivityChange?: (activity: LiveActivity) => void;
  compact?: boolean;
  display?: "default" | "files" | "tasks";
  terminal?: boolean;
  report?: ReactNode;
  primaryTaskIds?: string[];
  visibleOutputIds?: number[];
  visibleOutputKinds?: string[];
}) {
  const ui = useComputeText();
  const [items, setItems] = useState<AgentComputeTaskTracking[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number>();
  const [revision, setRevision] = useState(0);
  const [tasksExpanded, setTasksExpanded] = useState(true);
  const alive = useRef(true);
  const importing = useRef(false);
  const activityCallback = useRef(onActivityChange);
  activityCallback.current = onActivityChange;
  const taskKey = [...new Set(taskIds ?? [])].join(",");
  const tasksActive = items.some(({ task }) =>
    activeStates.includes(task.status),
  );
  useEffect(() => setTasksExpanded(tasksActive), [tasksActive]);
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
    setItems([]);
    setError("");
    activityCallback.current?.({
      state: "working",
      label: "正在读取计算进度",
      detail: "",
    });
    const poll = async () => {
      try {
        const result =
          runId !== undefined
            ? await agentApi.computeTasks(runId)
            : {
                items: await Promise.all(
                  taskKey
                    .split(",")
                    .filter(Boolean)
                    .map(async (id) => ({
                      task: await computeApi.task(id),
                      autoImport,
                      trackingStatus: "",
                      detail: "",
                    })),
                ),
              };
        if (disposed) return;
        failures = 0;
        setItems(result.items);
        setError("");
        activityCallback.current?.(
          computeTasksActivity(result.items, activityTaskId),
        );
        if (
          (terminal
            ? result.items.some(
                ({ task }) =>
                  activeStates.includes(task.status) ||
                  task.outputs.some((output) =>
                    ["queued", "running"].includes(output.importStatus),
                  ),
              )
            : shouldPoll(result.items)) ||
          (!terminal &&
            activityTaskId &&
            !result.items.some(({ task }) => task.id === activityTaskId))
        )
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
          activityCallback.current?.({
            state: "stopped",
            label: "计算状态不可用",
            detail:
              reason instanceof Error ? reason.message : "无权查看计算任务",
          });
          return;
        }
        activityCallback.current?.({
          state: "working",
          label: "正在重新核对计算状态",
          detail: reason instanceof Error ? reason.message : "读取任务状态失败",
        });
        failures += 1;
        timer = setTimeout(poll, Math.min(15000, 3000 * failures));
      }
    };
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [
    runId,
    taskKey,
    autoImport,
    refreshKey,
    revision,
    activityTaskId,
    terminal,
  ]);

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
  const taskCards = items.map(({ task, autoImport }) => (
    <section
      className="agent-compute-result"
      key={task.id}
      aria-label={taskDisplayNames?.[task.id] ?? task.name}
    >
      <div className="agent-compute-result-heading">
        <div>
          <span className="agent-compute-eyebrow">
            {ui(task.algorithmName)}
          </span>
          <strong>{taskDisplayNames?.[task.id] ?? task.name}</strong>
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
      <ComputeQualitySummary task={task} />
      {!compact && (
        <WorkflowDeliverables
          items={[{ task, autoImport, trackingStatus: "", detail: "" }]}
          busy={busy}
          reviewing={reviewing}
          heading={false}
          taskDisplayNames={taskDisplayNames}
          onImport={(output, current) => void importOutput(output, current)}
        />
      )}
    </section>
  ));
  if (!items.length)
    return error ? (
      <Alert type="warning" title={error} />
    ) : report ? (
      <WorkflowDeliverables items={[]} report={report} onImport={() => {}} />
    ) : null;
  if (display === "tasks")
    return (
      <div className="agent-compute-cards">
        {error && <Alert type="warning" title={error} />} {taskCards}
      </div>
    );
  if (display === "files")
    return (
      <div aria-label={ui("任务成果文件", "Task result files")}>
        {error && <Alert type="warning" title={error} />}
        <WorkflowDeliverables
          items={items}
          report={report}
          taskDisplayNames={taskDisplayNames}
          primaryTaskIds={primaryTaskIds}
          visibleOutputIds={visibleOutputIds}
          visibleOutputKinds={visibleOutputKinds}
          busy={busy}
          reviewing={reviewing}
          onImport={(output, task) => void importOutput(output, task)}
        />
      </div>
    );
  return (
    <div
      className={`agent-compute-cards${compact ? " is-compact" : ""}`}
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
      {compact ? (
        <>
          <Collapse
            ghost
            size="small"
            className="agent-task-history"
            activeKey={tasksExpanded ? ["tasks"] : []}
            onChange={(keys) => setTasksExpanded(keys.includes("tasks"))}
            items={[
              {
                key: "tasks",
                label: ui(
                  `计算任务 / ${items.length} 项${tasksActive ? " / 正在执行" : ""}`,
                  `Compute tasks / ${items.length}${tasksActive ? " / Running" : ""}`,
                ),
                forceRender: true,
                children: taskCards,
              },
            ]}
          />
          <WorkflowDeliverables
            items={items}
            report={report}
            taskDisplayNames={taskDisplayNames}
            primaryTaskIds={primaryTaskIds}
            visibleOutputIds={visibleOutputIds}
            visibleOutputKinds={visibleOutputKinds}
            busy={busy}
            reviewing={reviewing}
            onImport={(output, task) => void importOutput(output, task)}
          />
        </>
      ) : (
        taskCards
      )}
    </div>
  );
}
