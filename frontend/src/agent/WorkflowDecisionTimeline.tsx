import { Collapse, Tag } from "antd";
import { useEffect, useState } from "react";
import type { AgentWorkflowStep } from "../api/generated/types.gen";

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
}: {
  steps: AgentWorkflowStep[];
}) {
  const [restoredDecisions] = useState(
    () => new Set(steps.filter((step) => step.decision).map((step) => step.id)),
  );
  const activeSteps = steps
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
  return (
    <section
      className="agent-decision-timeline"
      aria-label="分析说明与决策依据"
    >
      <Collapse
        ghost
        size="small"
        activeKey={expanded}
        onChange={(keys) => setExpanded(Array.isArray(keys) ? keys : [keys])}
        className="agent-decision-steps"
        items={steps.map((step) => {
          const decision = step.decision;
          const modelResponse = record(step.outputRefs.modelResponse);
          const fresh = Boolean(decision && !restoredDecisions.has(step.id));
          return {
            key: String(step.id),
            label: (
              <div className="agent-decision-step-heading">
                <strong>
                  {step.sequence}. {decision?.problem || step.message}
                </strong>
                <Tag
                  color={step.status === "running" ? "processing" : undefined}
                >
                  {stepNames[step.status] ?? step.status}
                </Tag>
              </div>
            ),
            forceRender: true,
            children: (
              <article
                className={`agent-decision-step${fresh ? " is-new-decision" : ""}`}
                data-step-id={step.id}
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
                        {actionNames[decision.nextAction] ??
                          decision.nextAction}
                      </p>
                    )}
                    {!!decision.evidenceRefs.length && (
                      <div
                        className="agent-decision-evidence"
                        aria-label="本步依据"
                      >
                        {decision.evidenceRefs.map((entry) => (
                          <span
                            key={`${entry.kind}:${entry.id}:${entry.revision}`}
                          >
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
                ) : (
                  <p>{step.message}</p>
                )}
                {step.errorCode && (
                  <p className="agent-decision-error">
                    本步骤失败：
                    {step.message || "请查看任务状态中的原因与下一步操作。"}
                  </p>
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
        })}
      />
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
