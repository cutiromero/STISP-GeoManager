import { Collapse, Tag } from "antd";
import { useEffect, useState } from "react";
import type { AgentWorkflowStep } from "../api/generated/types.gen";
import {
  mainWorkflowSteps,
  modelAttemptRetried,
  workflowStepTitle,
} from "./workflowTimeline";

const stepNames: Record<string, string> = {
  queued: "等待执行",
  waiting: "任务已提交",
  running: "执行中",
  succeeded: "已完成",
  failed: "本步失败",
  waiting_approval: "待审核",
  skipped: "已跳过",
};
const actionNames: Record<string, string> = {
  "raster-ndvi": "计算植被指数",
  "ndvi-change": "提取植被变化与候选区",
  "ecology-priority": "更新调查优先区",
  "geology-check": "检查地质规则与调查证据",
  "vector-geometry-repair": "修复并核验地图几何",
  "geology-edit": "按核实证据修正填图",
  "geology-age-check": "检查地层时代与辞书适用条件",
  "geology-age-edit": "按适用规则修正时代录入",
  search_expert_knowledge: "查阅专家知识",
  "geology-map-check": "检查地质图属性与完整性",
  "geology-map-correct": "按用户批准的建议修正地图",
  finish: "查看分析结果与后续建议",
  request_review: "人工复核",
};
const resultNames: Record<string, string> = {
  ndvi: "植被指数图",
  change: "变化图",
  candidates: "变化候选区",
  priority: "调查优先区",
  statistics: "统计表",
  issues: "复查问题清单",
  issues_map: "问题位置图",
  corrected: "修正后地质图",
  repaired: "几何修复图",
  repair_log: "逐要素修复记录",
  repair_summary: "修复检查汇总",
  changes: "修改与证据记录",
};

export default function WorkflowDecisionTimeline({
  steps,
  taskNames = {},
  concise = false,
}: {
  steps: AgentWorkflowStep[];
  taskNames?: Record<string, string>;
  concise?: boolean;
}) {
  const visible = concise ? mainWorkflowSteps(steps) : steps;
  const [restoredDecisions] = useState(
    () => new Set(steps.filter((step) => step.decision).map((step) => step.id)),
  );
  const activeSteps = visible
    .filter((step) =>
      ["running", "waiting", "waiting_approval", "failed"].includes(
        step.status,
      ),
    )
    .map((step) => String(step.id));
  const activeKey = activeSteps.join(",");
  const [expanded, setExpanded] = useState<string[]>(activeSteps);
  useEffect(() => {
    setExpanded(activeKey ? activeKey.split(",") : []);
  }, [activeKey]);
  if (!steps.length) return null;
  const items = (entries: AgentWorkflowStep[], audit = false) =>
    entries.map((step, index) => {
      const decision = step.decision;
      const modelResponse = record(step.outputRefs.modelResponse);
      const activity = record(step.outputRefs.modelActivity);
      const fresh = Boolean(
        !audit && decision && !restoredDecisions.has(step.id),
      );
      const retried = modelAttemptRetried(step, steps);
      return {
        key: String(step.id),
        label: (
          <div className="agent-decision-step-heading">
            <strong>
              {audit ? step.sequence : index + 1}.{" "}
              {workflowStepTitle(step, taskNames)}
            </strong>
            <Tag color={step.status === "running" ? "processing" : undefined}>
              {retried ? "已重新分析" : (stepNames[step.status] ?? step.status)}
            </Tag>
          </div>
        ),
        forceRender: !audit,
        children: (
          <article
            className={`agent-decision-step${fresh ? " is-new-decision" : ""}`}
            data-step-id={audit ? undefined : step.id}
          >
            {decision ? (
              <>
                <span className="agent-decision-model">
                  {decision.modelMode === "mock"
                    ? "模拟模型"
                    : decision.modelName}
                </span>
                {!!decision.findings.length && (
                  <div className="agent-decision-findings">
                    <span>发现</span>
                    <ul>
                      {decision.findings.map((finding) => (
                        <li key={finding}>{finding}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {decision.judgement && (
                  <p className="agent-decision-judgement">
                    <strong>当前判断</strong>
                    {decision.judgement}
                  </p>
                )}
                {decision.algorithmReason && (
                  <p>
                    <strong>算法与参数依据</strong>
                    {decision.algorithmReason}
                  </p>
                )}
                {decision.resultSummary && (
                  <p className="agent-decision-result">
                    <strong>实际结果</strong>
                    {decision.resultSummary}
                  </p>
                )}
                {!!decision.uncertainties.length && (
                  <div className="agent-decision-uncertainties">
                    <strong>仍待核实</strong>
                    <ul>
                      {decision.uncertainties.map((entry) => (
                        <li key={entry}>{entry}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {decision.nextAction && (
                  <p>
                    <strong>下一步</strong>
                    {actionNames[decision.nextAction] ?? decision.nextAction}
                  </p>
                )}
                {!!decision.evidenceRefs.length && (
                  <div
                    className="agent-decision-evidence"
                    aria-label="本步依据"
                  >
                    {decision.evidenceRefs.map((entry) => (
                      <span key={`${entry.kind}:${entry.id}:${entry.revision}`}>
                        {entry.kind === "output"
                          ? (resultNames[entry.title] ?? entry.title)
                          : entry.title}
                        {entry.revision !== undefined
                          ? ` / 版本 ${entry.revision}`
                          : ""}
                      </span>
                    ))}
                  </div>
                )}
              </>
            ) : Object.keys(activity).length ? (
              <p>
                {activity.status === "complete"
                  ? "模型分析已完成。"
                  : activity.status === "failed"
                    ? "本次模型分析已停止。"
                    : "模型分析进行中。"}
                {typeof activity.thinkingChars === "number" &&
                  `已接收思考 ${activity.thinkingChars} 字符。`}
                {typeof activity.outputChars === "number" &&
                  `已接收响应正文 ${activity.outputChars} 字符。`}
              </p>
            ) : (
              <p>{step.message.trim() || "本条为运行状态记录。"}</p>
            )}
            {step.errorCode && (
              <p className="agent-decision-error">
                本步骤失败：
                {step.message || "请查看任务状态中的原因与下一步操作。"}
              </p>
            )}
            {audit &&
              typeof activity.thinkingText === "string" &&
              activity.thinkingText && (
                <details>
                  <summary>查看本阶段模型思考</summary>
                  {activity.truncated === true && (
                    <p>仅显示已保存的思考尾部。</p>
                  )}
                  <pre
                    style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
                  >
                    {activity.thinkingText}
                  </pre>
                </details>
              )}
            {typeof modelResponse.content === "string" && (
              <details>
                <summary>查看本次模型响应（审计记录）</summary>
                {modelResponse.truncated === true && (
                  <p>响应超过审计体积上限，仅保留截断内容。</p>
                )}
                <pre
                  style={{
                    whiteSpace: "pre-wrap",
                    overflowWrap: "anywhere",
                  }}
                >
                  {modelResponse.content ||
                    "模型未返回正文；请查看本步失败原因。"}
                </pre>
              </details>
            )}
          </article>
        ),
      };
    });
  return (
    <section
      className="agent-decision-timeline"
      aria-label="分析说明与决策依据"
    >
      {visible.length > 0 && (
        <Collapse
          ghost
          size="small"
          activeKey={expanded}
          onChange={(keys) => setExpanded(Array.isArray(keys) ? keys : [keys])}
          className="agent-decision-steps"
          items={items(visible)}
        />
      )}
      {concise && (
        <Collapse
          ghost
          size="small"
          items={[
            {
              key: "audit",
              label: `详细运行记录 / ${steps.length} 条`,
              children: (
                <Collapse
                  ghost
                  size="small"
                  defaultActiveKey={steps
                    .filter(
                      (step) =>
                        ["failed", "running", "waiting"].includes(
                          step.status,
                        ) && !modelAttemptRetried(step, steps),
                    )
                    .map((step) => String(step.id))}
                  items={items(steps, true)}
                />
              ),
            },
          ]}
        />
      )}
    </section>
  );
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

const observationLabels: Record<string, string> = {
  date: "观测日期",
  event_type: "观测事件",
  land_use: "土地用途",
  source: "资料来源",
  confidence: "可信度",
  value: "观测值",
};
const observationValues: Record<string, string> = {
  drought: "干旱",
  harvest: "收获",
  forest: "林地",
  cropland: "农田",
};

export function WorkflowEvidenceUpdate({
  previousAnalysis,
  steps,
}: {
  previousAnalysis: unknown;
  steps: AgentWorkflowStep[];
}) {
  const previous = record(previousAnalysis);
  if (!Object.keys(previous).length) return null;
  const oldDecision = record(previous.oldDecision);
  const oldContext = record(previous.oldContext);
  const newContext = record(previous.newContext);
  const addedEvidence = Array.isArray(previous.addedEvidence)
    ? previous.addedEvidence.map(record)
    : [];
  const decisions = steps
    .map((step) => step.decision)
    .filter((entry) => entry?.judgement);
  const newDecision = decisions[decisions.length - 1];
  return (
    <section
      className="agent-evidence-update"
      aria-label="补充观测后的判断更新"
    >
      <h3>新观测如何改变判断</h3>
      <div className="agent-evidence-comparison">
        <article>
          <strong>原判断</strong>
          <span className="agent-evidence-source">
            {text(oldContext.title)}
          </span>
          <p>
            {text(oldDecision.judgement) ||
              text(oldDecision.resultSummary) ||
              "原分析结果已保留"}
          </p>
          {text(oldDecision.judgement) &&
            text(oldDecision.resultSummary) &&
            text(oldDecision.resultSummary) !== text(oldDecision.judgement) && (
              <p>{text(oldDecision.resultSummary)}</p>
            )}
        </article>
        <article>
          <strong>更新后的判断</strong>
          <span className="agent-evidence-source">
            {text(newContext.title)}
          </span>
          <p>{newDecision?.judgement || "正在结合新增观测更新分析"}</p>
          {newDecision?.resultSummary &&
            newDecision.resultSummary !== newDecision.judgement && (
              <p>{newDecision.resultSummary}</p>
            )}
        </article>
      </div>
      {!!addedEvidence.length && (
        <div className="agent-added-evidence">
          <strong>新增观测证据 / {addedEvidence.length} 条</strong>
          {addedEvidence.map((row) => (
            <dl key={JSON.stringify(row)}>
              {Object.entries(observationLabels).map(([key, label]) => {
                const value = text(row[key]);
                if (!value) return null;
                const percent = key === "confidence" ? Number(value) : NaN;
                return (
                  <div key={key}>
                    <dt>{label}</dt>
                    <dd>
                      {Number.isFinite(percent) && percent >= 0 && percent <= 1
                        ? `${Math.round(percent * 100)}%`
                        : (observationValues[value] ?? value)}
                    </dd>
                  </div>
                );
              })}
            </dl>
          ))}
        </div>
      )}
      <p className="agent-demo-hint">
        沿用已有的影像变化结果，仅用新观测更新调查建议。
      </p>
    </section>
  );
}
