import { Button, Collapse, Popconfirm, Space, Tag } from "antd";
import { useEffect, useState } from "react";
import type { AgentWorkflow } from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";
import WorkflowDecisionTimeline, {
  WorkflowEvidenceUpdate,
} from "./WorkflowDecisionTimeline";
import RunComputeTasks from "./RunComputeTasks";
import WorkflowKnowledgeReferences from "./WorkflowKnowledgeReferences";
import LiveActivity from "./LiveActivity";
import { workflowActivity } from "./agentActivity";
import WorkflowReportFile from "./WorkflowReportFile";
import WorkflowDeliverables from "./WorkflowDeliverables";

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
  paused: "已暂停",
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
  onPause,
  onResume,
  onEvidenceUpdate,
  compact = false,
}: {
  workflow: AgentWorkflow;
  busy?: boolean;
  onConfirm?: () => void;
  onCancel?: () => void;
  onPause?: () => void;
  onResume?: () => void;
  onEvidenceUpdate?: () => void;
  compact?: boolean;
}) {
  const ui = useComputeText();
  const isActive = active.includes(workflow.status);
  const [processExpanded, setProcessExpanded] = useState(isActive);
  useEffect(() => setProcessExpanded(isActive), [workflow.id, isActive]);
  const finalDecision = [...workflow.steps]
    .reverse()
    .find((step) => step.decision?.nextAction === "finish")?.decision;
  const report =
    workflow.status === "succeeded" ? (
      <WorkflowReportFile
        key={workflow.id}
        workflowId={workflow.id}
        projectId={workflow.projectId}
      />
    ) : undefined;
  const fields = (value: unknown) =>
    value && typeof value === "object" && !Array.isArray(value)
      ? Object.entries(value)
      : [];
  const mapResourceIds = workflowMapResourceIds(workflow);
  const taskDisplayNames = Array.isArray(workflow.plan.stages)
    ? Object.fromEntries(
        workflow.plan.stages.flatMap((stage) => {
          if (!stage || typeof stage !== "object" || Array.isArray(stage))
            return [];
          const data = stage as Record<string, unknown>;
          const stageName = String(data.name);
          const stageLabels: Record<string, string> = {
            early_ndvi: ui("前期植被指数", "Earlier vegetation index"),
            late_ndvi: ui("后期植被指数", "Later vegetation index"),
            change: ui("植被变化检测", "Vegetation change detection"),
            priority: ui("调查顺序分析", "Investigation priorities"),
            initial_check: ui("初始填图检查", "Initial map check"),
            geometry: ui("几何修复", "Geometry repair"),
            ...(workflow.workflowType === "geology_age_correction"
              ? {
                  check: ui("初始时代属性检查", "Initial geologic age check"),
                  edit: ui("地层时代属性纠偏", "Geologic age correction"),
                  recheck: ui("最终时代属性复查", "Final geologic age recheck"),
                }
              : workflow.workflowType === "geology_correction"
                ? {
                    check: ui("修复后检查", "Check after repair"),
                    edit: ui(
                      "调查证据属性编辑",
                      "Evidence-based attribute editing",
                    ),
                    recheck: ui("最终填图复查", "Final map recheck"),
                  }
                : {}),
          };
          return typeof data.taskId === "string" && stageLabels[stageName]
            ? [[data.taskId, stageLabels[stageName]]]
            : [];
        }),
      )
    : undefined;
  const primaryStageNames =
    workflow.workflowType === "ecology_investigation"
      ? ["change", "priority"]
      : ["edit", "recheck"];
  const primaryTaskIds =
    workflow.status === "succeeded" && Array.isArray(workflow.plan.stages)
      ? workflow.plan.stages.flatMap((stage) => {
          if (!stage || typeof stage !== "object" || Array.isArray(stage))
            return [];
          const data = stage as Record<string, unknown>;
          return primaryStageNames.includes(String(data.name)) &&
            typeof data.taskId === "string"
            ? [data.taskId]
            : [];
        })
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
      {workflow.steps.length > 0 && (
        <Collapse
          ghost
          className="agent-workflow-process"
          activeKey={processExpanded ? ["process"] : []}
          onChange={(keys) => setProcessExpanded(keys.includes("process"))}
          items={[
            {
              key: "process",
              label: ui(
                `查看分析过程 · ${workflow.steps.length} 步`,
                `Analysis process · ${workflow.steps.length} steps`,
              ),
              children: (
                <>
                  <WorkflowEvidenceUpdate
                    previousAnalysis={workflow.plan.previousAnalysis}
                    steps={workflow.steps}
                  />
                  <WorkflowDecisionTimeline
                    key={workflow.id}
                    steps={workflow.steps}
                  />
                </>
              ),
            },
          ]}
        />
      )}
      {workflow.status === "succeeded" && finalDecision && (
        <article
          className="agent-workflow-conclusion"
          aria-label={ui("研究结论", "Research conclusion")}
        >
          <h3>{ui("研究结论", "Research conclusion")}</h3>
          <p>{finalDecision.judgement}</p>
          {finalDecision.resultSummary &&
            finalDecision.resultSummary !== finalDecision.judgement && (
              <p>{finalDecision.resultSummary}</p>
            )}
        </article>
      )}
      {workflow.workflowType === "ecology_investigation" &&
        workflow.status === "succeeded" &&
        onEvidenceUpdate && (
          <Button onClick={onEvidenceUpdate}>补充观测后更新判断</Button>
        )}
      {workflow.steps.some((step) => step.computeTaskId) && (
        <RunComputeTasks
          compact
          report={report}
          primaryTaskIds={primaryTaskIds}
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
      {!workflow.steps.some((step) => step.computeTaskId) && report && (
        <WorkflowDeliverables items={[]} report={report} onImport={() => {}} />
      )}
      {workflow.status === "waiting_approval" && onConfirm && (
        <Button type="primary" loading={busy} onClick={onConfirm}>
          {Array.isArray(workflow.plan.reviewOutputs) &&
          workflow.plan.reviewOutputs.length
            ? ui("审核并继续", "Review and continue")
            : ui("确认执行", "Confirm execution")}
        </Button>
      )}
      <Space wrap className="agent-workflow-actions">
        {isActive && onPause && (
          <Popconfirm
            title={ui("暂停此工作流？", "Pause this workflow?")}
            description={ui(
              "已提交计算可继续完成，后续步骤等待您继续。",
              "Submitted calculations can finish; later steps wait for you to resume.",
            )}
            okText={ui("确认暂停", "Pause")}
            cancelText={ui("继续工作", "Keep working")}
            onConfirm={onPause}
          >
            <Button loading={busy} disabled={workflow.pauseRequested}>
              {workflow.pauseRequested
                ? ui("正在暂停", "Pausing")
                : ui("暂停任务", "Pause task")}
            </Button>
          </Popconfirm>
        )}
        {workflow.status === "paused" && onResume && (
          <Button type="primary" loading={busy} onClick={onResume}>
            {ui("继续任务", "Resume task")}
          </Button>
        )}
        {(isActive || workflow.status === "paused") && onCancel && (
          <Popconfirm
            title={ui("停止此工作流？", "Stop this workflow?")}
            description={ui(
              "停止后续步骤，已提交计算可继续完成。",
              "Stop subsequent steps; submitted calculations can finish.",
            )}
            okText={ui("确认停止", "Stop")}
            cancelText={ui("继续工作", "Keep working")}
            onConfirm={onCancel}
          >
            <Button loading={busy}>
              {ui("停止此工作流", "Stop workflow")}
            </Button>
          </Popconfirm>
        )}
      </Space>
      {!!workflow.resultResourceIds.length && (
        <div className="agent-workflow-saved">
          <span>
            {ui(
              "成果已保存到本项目的数据资源",
              "Results saved in this project's data resources",
            )}
          </span>
          {mapResourceIds.length ? (
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
          )}
        </div>
      )}
      {(isActive || workflow.status === "paused") && (
        <LiveActivity activity={workflowActivity(workflow)} />
      )}
    </div>
  );
}
