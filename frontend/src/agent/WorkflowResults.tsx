import { Alert, Button, Collapse, Space, Tag } from "antd";
import type { AgentWorkflow } from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";
import WorkflowDecisionTimeline, {
  WorkflowEvidenceUpdate,
} from "./WorkflowDecisionTimeline";
import RunComputeTasks from "./RunComputeTasks";
import WorkflowKnowledgeReferences from "./WorkflowKnowledgeReferences";
import LiveActivity from "./LiveActivity";
import { workflowActivity } from "./agentActivity";

const active = ["queued", "running", "waiting_compute", "waiting_approval"];
const labels: Record<string, string> = {
  queued: "等待处理",
  running: "准备计划",
  waiting_compute: "执行与入库",
  waiting_approval: "等待确认",
  succeeded: "已完成",
  failed: "未完成",
  cancelled: "已停止",
  interrupted: "已中断",
};
function workflowMapResourceIds(workflow: AgentWorkflow | undefined) {
  if (!workflow) return [];
  const record = (value: unknown): Record<string, unknown> =>
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  const demo = [
    "ecology_investigation",
    "geology_correction",
    "geology_age_correction",
  ].includes(workflow.workflowType);
  const stages = Array.isArray(workflow.plan.stages)
    ? workflow.plan.stages
    : [];
  const results = demo
    ? stages.flatMap((stage) => {
        const outputs = record(stage).outputs;
        return Array.isArray(outputs)
          ? outputs.flatMap((value) => {
              const output = record(value);
              return ["raster", "vector"].includes(String(output.kind))
                ? [output.resourceId]
                : [];
            })
          : [];
      })
    : workflow.resultResourceIds;
  const original = ["geology_correction", "geology_age_correction"].includes(
    workflow.workflowType,
  )
    ? record(workflow.plan.inputs).initial_map
    : undefined;
  const previousChange = demo
    ? record(workflow.plan.previousChange).resourceId
    : undefined;
  return [
    ...new Set(
      [original, previousChange, ...results].filter(
        (value): value is number =>
          typeof value === "number" && Number.isInteger(value) && value > 0,
      ),
    ),
  ];
}

export default function WorkflowResults({
  workflow,
  busy = false,
  onConfirm,
  onCancel,
  onEvidenceUpdate,
  compact = false,
}: {
  workflow: AgentWorkflow;
  busy?: boolean;
  onConfirm?: () => void;
  onCancel?: () => void;
  onEvidenceUpdate?: () => void;
  compact?: boolean;
}) {
  const ui = useComputeText();
  const fields = (value: unknown) =>
    value && typeof value === "object" && !Array.isArray(value)
      ? Object.entries(value)
      : [];
  const mapResourceIds = workflowMapResourceIds(workflow);
  const taskDisplayNames =
    workflow.workflowType === "geology_age_correction" &&
    Array.isArray(workflow.plan.stages)
      ? Object.fromEntries(
          workflow.plan.stages.flatMap((stage) => {
            if (!stage || typeof stage !== "object" || Array.isArray(stage))
              return [];
            const data = stage as Record<string, unknown>;
            const stageName = String(data.name);
            const stageLabels: Record<string, string> = {
              check: ui("初始时代属性检查", "Initial geologic age check"),
              edit: ui("地层时代属性纠偏", "Geologic age correction"),
              recheck: ui("最终时代属性复查", "Final geologic age recheck"),
            };
            return typeof data.taskId === "string" && stageLabels[stageName]
              ? [[data.taskId, stageLabels[stageName]]]
              : [];
          }),
        )
      : undefined;
  const settingsSummary = (
    <dl className="agent-plan-summary">
      <dt>{ui("算法", "Algorithm")}</dt>
      <dd>
        {workflow.plan.algorithm
          ? String(workflow.plan.algorithm)
          : fields(workflow.plan.algorithms).map(([key, value]) => (
              <div key={key}>
                {value && typeof value === "object" && "name" in value
                  ? String(value.name)
                  : key}
              </div>
            ))}
      </dd>
      <dt>{ui("输入数据", "Input data")}</dt>
      <dd>
        {fields(workflow.plan.inputNames).map(([key, value]) => (
          <div key={key}>{String(value)}</div>
        ))}
      </dd>
      <dt>{ui("执行参数", "Parameters")}</dt>
      <dd>
        {fields(workflow.plan.parameters ?? workflow.parameters).map(
          ([key, value]) => (
            <div key={key}>
              {key}：{String(value)}
            </div>
          ),
        )}
      </dd>
      <dt>{ui("知识依据", "Knowledge references")}</dt>
      <dd>
        {workflow.evidence.length ? (
          <WorkflowKnowledgeReferences items={workflow.evidence} />
        ) : (
          ui(
            "未匹配到相关知识规则，将保留算法原始结果",
            "No matching rules; the original calculation will be preserved",
          )
        )}
      </dd>
    </dl>
  );
  return (
    <div className="agent-workflow-status">
      <Space wrap className="agent-workflow-meta">
        <Tag
          color={
            workflow.status === "succeeded"
              ? "green"
              : workflow.status === "failed"
                ? "red"
                : "blue"
          }
        >
          {ui(labels[workflow.status] ?? workflow.status)}
        </Tag>
      </Space>
      {workflow.planHash &&
        (compact ? (
          <Collapse
            size="small"
            className="agent-research-settings"
            items={[
              {
                key: "settings",
                label: ui("本次采用的资料与设置", "Data and settings used"),
                children: settingsSummary,
              },
            ]}
          />
        ) : (
          settingsSummary
        ))}
      <WorkflowEvidenceUpdate
        previousAnalysis={workflow.plan.previousAnalysis}
        steps={workflow.steps}
      />
      <WorkflowDecisionTimeline key={workflow.id} steps={workflow.steps} />
      {workflow.workflowType === "ecology_investigation" &&
        workflow.status === "succeeded" &&
        onEvidenceUpdate && (
          <Button onClick={onEvidenceUpdate}>补充观测后更新判断</Button>
        )}
      {workflow.steps.some((step) => step.computeTaskId) && (
        <RunComputeTasks
          taskIds={workflow.steps
            .map((step) => step.computeTaskId)
            .filter(Boolean)}
          autoImport={workflow.importResults}
          reviewing={
            workflow.status === "waiting_approval" &&
            Array.isArray(workflow.plan.reviewOutputs) &&
            workflow.plan.reviewOutputs.length > 0
          }
          refreshKey={`${workflow.id}:${workflow.status}`}
          taskDisplayNames={taskDisplayNames}
        />
      )}
      {workflow.status === "waiting_approval" && onConfirm && (
        <Button type="primary" loading={busy} onClick={onConfirm}>
          {Array.isArray(workflow.plan.reviewOutputs) &&
          workflow.plan.reviewOutputs.length
            ? ui("审核并继续", "Review and continue")
            : ui("确认执行", "Confirm execution")}
        </Button>
      )}
      {active.includes(workflow.status) && onCancel && (
        <Button loading={busy} onClick={onCancel}>
          {ui("停止此工作流", "Stop workflow")}
        </Button>
      )}
      {!!workflow.resultResourceIds.length && (
        <Alert
          type="success"
          title={ui(
            "成果已保存到本项目的数据资源",
            "Results saved in this project's data resources",
          )}
          description={
            mapResourceIds.length ? (
              <a
                href={`/map?resources=${mapResourceIds.join(",")}&projectTagId=${workflow.projectId}`}
              >
                {ui(
                  "在地理工作台对比成果图层",
                  "Compare result layers in the map workspace",
                )}
              </a>
            ) : (
              ui(
                "可在本项目的数据资源中查看成果",
                "View the results in this project's data resources",
              )
            )
          }
        />
      )}
      <LiveActivity activity={workflowActivity(workflow)} />
    </div>
  );
}
