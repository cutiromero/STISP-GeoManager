import { Alert, Button, Collapse, Input, Popconfirm, Space, Tag } from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
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
import GeologyReviewStory from "./GeologyReviewStory";
import MultiElementStory from "./MultiElementStory";
import { isMultiElementFamily, multiElementType } from "./multiElementScenario";
import { usesCleanGeologyResults } from "../map/workflowOutputMaps";
import {
  geologyReviewOutcome,
  geologyReviewOriginalMapId,
} from "./geologyReviewOutcome";
import { deletedWorkflowResources } from "./deletedWorkflowResources";
import {
  workflowNextAction,
  workflowExecutionNote,
  workflowStageLabel,
  workflowStatusLabels,
} from "./workflowFeedback";
import { emphasizeNumbers } from "./researchText";
import RuleCards from "./RuleCards";

const active = ["queued", "running", "waiting_compute", "waiting_approval"];
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
export function workflowMapResourceIds(workflow: AgentWorkflow | undefined) {
  if (!workflow) return [];
  const demo =
    [
      "ecology_investigation",
      "geology_correction",
      "geology_age_correction",
      "geology_map_review",
      multiElementType,
    ].includes(workflow.workflowType) ||
    isMultiElementFamily(workflow.workflowType);
  const stages = Array.isArray(workflow.plan.stages)
    ? workflow.plan.stages
    : [];
  const results = demo
    ? stages.flatMap((stage) => {
        const outputs = record(stage).outputs;
        return Array.isArray(outputs)
          ? outputs.flatMap((value) => {
              const output = record(value);
              if (
                isMultiElementFamily(workflow.workflowType) &&
                usesCleanGeologyResults(workflow) &&
                record(stage).name === "apply" &&
                ["faults", "alterations"].includes(String(output.key))
              )
                return [];
              return ["raster", "vector"].includes(String(output.kind))
                ? [output.resourceId]
                : [];
            })
          : [];
      })
    : workflow.resultResourceIds;
  const original = [
    "geology_correction",
    "geology_age_correction",
    "geology_map_review",
  ].includes(workflow.workflowType)
    ? record(workflow.plan.inputs).initial_map
    : undefined;
  const previousChange = demo
    ? record(workflow.plan.previousChange).resourceId
    : undefined;
  const deleted = new Set(
    deletedWorkflowResources(workflow).map((item) => item.id),
  );
  return [
    ...new Set(
      [original, previousChange, ...results].filter(
        (value): value is number =>
          typeof value === "number" &&
          Number.isInteger(value) &&
          value > 0 &&
          !deleted.has(value),
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
  onReview,
  onRestart,
  onEvidenceUpdate,
  compact = false,
}: {
  workflow: AgentWorkflow;
  busy?: boolean;
  onConfirm?: () => void;
  onCancel?: () => void;
  onPause?: () => void;
  onResume?: () => void;
  onReview?: (
    decision: "approve" | "reject",
    feedback: string,
    selectedSuggestionIds?: string[],
  ) => void;
  onRestart?: () => void;
  onEvidenceUpdate?: () => void;
  compact?: boolean;
}) {
  const ui = useComputeText();
  const isActive = active.includes(workflow.status);
  const isMultiElement = isMultiElementFamily(workflow.workflowType);
  const isGeologyReview =
    workflow.workflowType === "geology_map_review" || isMultiElement;
  const inspectionOnly = Boolean(geologyReviewOutcome(workflow));
  const originalMapId = geologyReviewOriginalMapId(workflow);
  const deletedResources = deletedWorkflowResources(workflow);
  const deletedIds = new Set(deletedResources.map((item) => item.id));
  const availableResultIds = workflow.resultResourceIds.filter(
    (id) => !deletedIds.has(id),
  );
  const needsModificationsReview =
    isGeologyReview &&
    workflow.status === "waiting_approval" &&
    workflow.plan.phase === "review_modifications";
  const [reviewFeedback, setReviewFeedback] = useState("");
  const needsReview =
    workflow.status === "waiting_approval" &&
    (workflow.plan.phase === "review_results" ||
      (Array.isArray(workflow.plan.reviewOutputs) &&
        workflow.plan.reviewOutputs.length > 0));
  useEffect(() => setReviewFeedback(""), [workflow.id, workflow.planHash]);
  const stopped = ["failed", "interrupted", "cancelled", "paused"].includes(
    workflow.status,
  );
  const nextAction = workflowNextAction(workflow);
  const lastReview = [...workflow.steps]
    .reverse()
    .find((step) => step.kind === "review_feedback");
  const [processExpanded, setProcessExpanded] = useState(
    isActive && !isGeologyReview,
  );
  useEffect(
    () => setProcessExpanded(isActive && !isGeologyReview),
    [workflow.id, isActive, isGeologyReview],
  );
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
            ...(isMultiElement
              ? {
                  check: "三要素检查与建议",
                  apply: "执行获批操作",
                  recheck: "修正后复核",
                  relations: "重建构造交汇",
                  prospect: "前后远景区比较",
                }
              : isGeologyReview
                ? {
                    check: "检查地质图",
                    edit: "生成修正后地质图",
                    recheck: "复核修正后地质图",
                  }
                : workflow.workflowType === "geology_age_correction"
                  ? {
                      check: ui(
                        "初始时代属性检查",
                        "Initial geologic age check",
                      ),
                      edit: ui("地层时代属性纠偏", "Geologic age correction"),
                      recheck: ui(
                        "最终时代属性复查",
                        "Final geologic age recheck",
                      ),
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
  const primaryStageNames = isMultiElement
    ? ["apply", "relations", "prospect"]
    : workflow.workflowType === "ecology_investigation"
      ? ["change", "priority"]
      : inspectionOnly
        ? ["check"]
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
          {ui(workflowStatusLabels[workflow.status])}
        </Tag>
      </Space>
      {deletedResources.length > 0 && (
        <Alert
          type="info"
          showIcon
          title="部分历史目录数据已删除"
          description={
            <>
              <p>任务、报告和判断记录已保留；再次处理时请重新选择相应数据。</p>
              <ul>
                {deletedResources.map((item) => (
                  <li key={item.id}>
                    <strong>{item.name}</strong> / 已删除
                    {item.deletedAt &&
                      ` / ${new Date(item.deletedAt).toLocaleString()}`}
                    {item.source && (
                      <span>
                        {" "}
                        / 原来源：
                        {item.source.startsWith("compute-output:")
                          ? "平台算法计算"
                          : item.source}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </>
          }
        />
      )}
      {(stopped ||
        workflow.pauseRequested ||
        workflow.status === "waiting_approval") && (
        <Alert
          className="agent-workflow-feedback"
          type={
            workflow.status === "failed"
              ? "error"
              : workflow.status === "interrupted"
                ? "warning"
                : "info"
          }
          showIcon
          title={
            workflow.pauseRequested && workflow.status !== "paused"
              ? "正在保存进度并暂停"
              : workflowStatusLabels[workflow.status]
          }
          description={
            <>
              <p>
                <strong>当前阶段：</strong>
                {workflowStageLabel(workflow)}
              </p>
              <p>{workflow.detail || "当前状态已保存，请按下方操作继续。"}</p>
              {workflowExecutionNote(workflow) && (
                <p>{workflowExecutionNote(workflow)}</p>
              )}
              {nextAction && <p>{nextAction}</p>}
            </>
          }
        />
      )}
      {lastReview &&
        typeof lastReview.action.feedback === "string" &&
        lastReview.action.feedback && (
          <p className="agent-review-saved">
            <strong>已保存的审核意见：</strong>
            {lastReview.action.feedback}
          </p>
        )}
      {isMultiElement && (
        <MultiElementStory
          key={`${workflow.id}:${workflow.modificationReview?.proposalHash ?? "pending"}`}
          workflow={workflow}
          busy={busy}
          onReview={onReview}
        />
      )}
      {isGeologyReview && !isMultiElement && (
        <GeologyReviewStory
          key={`${workflow.id}:${workflow.modificationReview?.proposalHash ?? "pending"}`}
          workflow={workflow}
          busy={busy}
          onReview={onReview}
        />
      )}
      {workflow.planHash &&
        (compact || isGeologyReview ? (
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
                `查看分析过程 / ${workflow.steps.length} 步`,
                `Analysis process / ${workflow.steps.length} steps`,
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
      {isMultiElement && <RuleCards workflow={workflow} />}
      {workflow.status === "succeeded" && finalDecision && (
        <article
          className="agent-workflow-conclusion"
          aria-label={
            isGeologyReview ? "检查结论" : ui("研究结论", "Research conclusion")
          }
        >
          <h3>
            {isGeologyReview
              ? "检查结论"
              : ui("研究结论", "Research conclusion")}
          </h3>
          <p className="agent-workflow-conclusion-main">
            {emphasizeNumbers(finalDecision.judgement)}
          </p>
          {finalDecision.resultSummary &&
            finalDecision.resultSummary !== finalDecision.judgement && (
              <p>{emphasizeNumbers(finalDecision.resultSummary)}</p>
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
          visibleOutputIds={
            isMultiElement && Array.isArray(workflow.plan.stages)
              ? workflow.plan.stages.flatMap((stage) => {
                  const outputs = record(stage).outputs;
                  return Array.isArray(outputs)
                    ? outputs
                        .filter(
                          (output) =>
                            !(
                              usesCleanGeologyResults(workflow) &&
                              record(stage).name === "apply" &&
                              ["faults", "alterations"].includes(
                                String(record(output).key),
                              )
                            ),
                        )
                        .map((output) => Number(record(output).outputId))
                        .filter(Number.isSafeInteger)
                    : [];
                })
              : undefined
          }
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
      {needsReview && onReview ? (
        <section className="agent-workflow-review" aria-label="人工审核反馈">
          <strong>请审核候选结果</strong>
          <p>
            意见会保存到本次任务；确认后智能体继续处理，拒绝则停止后续步骤并保留已有成果。
          </p>
          <Input.TextArea
            aria-label="审核意见"
            placeholder="例如：已核对修改位置，允许继续；或说明需要补充核验的依据。"
            value={reviewFeedback}
            maxLength={4000}
            autoSize={{ minRows: 2, maxRows: 5 }}
            disabled={busy}
            onChange={(event) => setReviewFeedback(event.target.value)}
          />
          <small>不通过需填写具体原因。意见作为审核记录保存。</small>
          <Space wrap>
            <Popconfirm
              title="确认通过本次审核？"
              description="将保存您的审核意见并继续后续处理。"
              okText="确认通过"
              cancelText="返回核对"
              onConfirm={() => onReview("approve", reviewFeedback.trim())}
            >
              <Button type="primary" loading={busy}>
                审核通过并继续
              </Button>
            </Popconfirm>
            <Popconfirm
              title="确认不通过并停止？"
              description="保留候选文件和审核意见，停止后续处理。"
              okText="确认不通过"
              cancelText="返回核对"
              onConfirm={() => onReview("reject", reviewFeedback.trim())}
            >
              <Button disabled={busy || !reviewFeedback.trim()}>
                不通过并停止
              </Button>
            </Popconfirm>
          </Space>
        </section>
      ) : (
        !needsModificationsReview &&
        workflow.status === "waiting_approval" &&
        onConfirm && (
          <Button type="primary" loading={busy} onClick={onConfirm}>
            {Array.isArray(workflow.plan.reviewOutputs) &&
            workflow.plan.reviewOutputs.length
              ? ui("审核并继续", "Review and continue")
              : ui("确认执行", "Confirm execution")}
          </Button>
        )
      )}
      <Space wrap className="agent-workflow-actions">
        {["failed", "interrupted", "cancelled"].includes(workflow.status) &&
          onRestart && (
            <Button onClick={onRestart} disabled={busy}>
              {ui("调整后重新发起", "Start again with revised settings")}
            </Button>
          )}
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
        {workflow.status === "paused" &&
          onResume &&
          !deletedResources.length && (
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
      {!!availableResultIds.length && (
        <div className="agent-workflow-saved">
          <span>
            {ui(
              "成果已保存到本项目的数据资源",
              "Results saved in this project's data resources",
            )}
          </span>
          {mapResourceIds.length &&
          (!inspectionOnly || originalMapId) &&
          !(isGeologyReview && deletedResources.length) ? (
            <Link
              target="_blank"
              rel="noopener"
              to={
                isGeologyReview && !inspectionOnly
                  ? `/map?geologyCompare=${encodeURIComponent(workflow.id)}&projectTagId=${workflow.projectId}`
                  : isGeologyReview
                    ? `/map?resourceId=${originalMapId}&projectTagId=${workflow.projectId}`
                    : `/map?resources=${mapResourceIds.join(",")}&projectTagId=${workflow.projectId}`
              }
            >
              {inspectionOnly
                ? "在地理工作台查看待检查图"
                : ui(
                    "在地理工作台对比成果图层",
                    "Compare result layers in the map workspace",
                  )}
            </Link>
          ) : (
            ui(
              "可在本项目的数据资源中查看成果",
              "View the results in this project's data resources",
            )
          )}
        </div>
      )}
      {isActive &&
        workflow.status !== "waiting_approval" &&
        !workflow.pauseRequested && (
          <LiveActivity activity={workflowActivity(workflow)} />
        )}
    </div>
  );
}
