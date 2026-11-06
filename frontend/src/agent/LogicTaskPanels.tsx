import { CheckCircleOutlined, ClockCircleOutlined } from "@ant-design/icons";
import { Alert, Button, Input, Popconfirm, Space } from "antd";
import { useState } from "react";
import type { AgentWorkflow } from "../api/generated/types.gen";
import { record } from "../map/geologyReviewData";
import WorkflowKnowledgeReferences from "./WorkflowKnowledgeReferences";
import {
  logicPhases,
  logicPhase,
  logicStageNames,
} from "./logicTaskPresentation";
import type { LogicTaskProps } from "./logicTaskTypes";

export function LogicTaskProcess({
  workflow,
  onRecords,
  onEvidence,
}: {
  workflow: AgentWorkflow;
  onRecords: () => void;
  onEvidence: () => void;
}) {
  const summary = workflow.taskSummary;
  const current = logicPhase(workflow);
  const descriptions = [
    current > 0
      ? "资料、字段与本次执行范围已经确认。"
      : "核对资料角色、字段和本次执行范围。",
    summary?.initialIssueCount != null
      ? `初检返回 ${summary.initialIssueCount} 条实际问题记录。`
      : current === 1
        ? "正在读取实际测量和检查结果。"
        : "检查结果尚未生成。",
    summary?.executedDispositionCount != null
      ? `已执行 ${summary.executedDispositionCount} 项处置。${summary.remainingIssueCount != null ? `复查剩余 ${summary.remainingIssueCount} 条记录。` : "复查尚未完成。"}`
      : current === 2
        ? "按本次授权处理，随后复查和比较实际结果。"
        : "处理与复查尚未完成。",
    workflow.status === "succeeded"
      ? "结论与实际结果已保存，可查看对比或获取报告。"
      : current === 3
        ? "计算完成，正在整理结论与报告。"
        : "成果将随实际计算完成后保存。",
  ];
  return (
    <section aria-label="分析阶段与依据" className="logic-process-list">
      {logicPhases.map((label, index) => (
        <div className="logic-process-item" key={label}>
          <span>
            {index < current ? (
              <CheckCircleOutlined />
            ) : (
              <ClockCircleOutlined />
            )}
          </span>
          <div>
            <strong>{label}</strong>
            <p>{descriptions[index]}</p>
          </div>
          <Button type="link" size="small" onClick={onEvidence}>
            依据
          </Button>
        </div>
      ))}
      <div className="logic-process-footer">
        <Button onClick={onRecords}>查看完整运行记录与模型交互</Button>
        <span>计算校验与重试按原顺序保留，不计作新的研究阶段。</span>
      </div>
    </section>
  );
}

export function LogicTaskSettings({
  workflow,
  inputs = [],
}: {
  workflow: AgentWorkflow;
  inputs?: LogicTaskProps["inputSummary"];
}) {
  const names = Object.entries(record(workflow.plan.inputNames));
  const algorithms = record(workflow.plan.algorithms);
  return (
    <div className="logic-settings">
      <section>
        <h4>本次要求</h4>
        <p>{workflow.goal}</p>
      </section>
      <section>
        <h4>实际采用的资料</h4>
        {inputs.length ? (
          <ul>
            {inputs.map((input) => (
              <li key={`${input.role}:${input.resourceId}`}>
                <strong>{input.label}</strong>
                <span>{input.name}</span>
              </li>
            ))}
          </ul>
        ) : names.length ? (
          <ul>
            {names.map(([key, name]) => (
              <li key={key}>{String(name)}</li>
            ))}
          </ul>
        ) : workflow.plan.fieldMappingReview ? (
          <ul>
            {workflow.plan.fieldMappingReview.roles.map((role) => (
              <li key={role.role}>
                {role.label} · {role.fileName}
              </li>
            ))}
          </ul>
        ) : (
          <p>本次资料详情尚未返回。</p>
        )}
      </section>
      <section>
        <h4>执行范围</h4>
        <p>
          按照本次确认的资料和处置范围执行，原始资料保持。历史确认不自动授权新的修改。
        </p>
      </section>
      {Object.keys(algorithms).length > 0 && (
        <section>
          <h4>本次算法版本</h4>
          <ul>
            {Object.entries(algorithms).map(([key, data]) => (
              <li key={key}>
                {String(record(data).name ?? key)} ·{" "}
                {String(record(record(data).manifest).version ?? "已冻结版本")}
              </li>
            ))}
          </ul>
        </section>
      )}
      {Object.keys(workflow.parameters).length > 0 && (
        <section>
          <h4>实际参数</h4>
          <ul>
            {Object.entries(workflow.parameters).map(([key, value]) => (
              <li key={key}>
                {key}：{String(value)}
              </li>
            ))}
          </ul>
        </section>
      )}
      {workflow.evidence.length > 0 && (
        <section>
          <h4>知识与规则来源</h4>
          <WorkflowKnowledgeReferences items={workflow.evidence} />
        </section>
      )}
    </div>
  );
}

export function LogicResultReview({
  workflow,
  busy,
  onReview,
  reviewError,
}: {
  workflow: AgentWorkflow;
  busy?: boolean;
  onReview: LogicTaskProps["onReview"];
  reviewError?: string;
}) {
  const [feedback, setFeedback] = useState("");
  if (!onReview) return null;
  return (
    <section className="logic-result-review" aria-label="人工审核反馈">
      <p>
        请先核对实际候选成果和当前原因。审核意见会保存，未通过时停止后续处理并保留已有文件。
      </p>
      <Alert type="info" title={workflow.detail} />
      <label>
        审核意见
        <Input.TextArea
          aria-label="审核意见"
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          maxLength={4000}
          disabled={busy}
          autoSize={{ minRows: 2, maxRows: 5 }}
        />
      </label>
      {reviewError && <Alert type="error" title={reviewError} />}
      <Space wrap>
        <Button
          type="primary"
          loading={busy}
          onClick={() => onReview("approve", feedback.trim())}
        >
          审核通过并继续
        </Button>
        <Popconfirm
          title="不通过并停止本次任务？"
          description="候选文件和审核意见将保留。"
          onConfirm={() => onReview("reject", feedback.trim())}
          okText="不通过并停止"
          cancelText="返回核对"
        >
          <Button disabled={busy || !feedback.trim()}>不通过并停止</Button>
        </Popconfirm>
      </Space>
    </section>
  );
}

export function LogicTaskCalculationList({
  workflow,
}: {
  workflow: AgentWorkflow;
}) {
  const names = logicStageNames(workflow);
  return (
    <div className="logic-calculation-summary">
      {(Array.isArray(workflow.plan.stages)
        ? workflow.plan.stages.map(record)
        : []
      )
        .filter((s) => s.taskId)
        .map((stage) => (
          <div key={String(stage.taskId)}>
            <strong>{names[String(stage.taskId)] ?? String(stage.name)}</strong>
            <span>
              {stage.status === "completed"
                ? "已完成"
                : stage.status === "waiting_compute"
                  ? "计算或保存中"
                  : "已提交"}
            </span>
          </div>
        ))}
    </div>
  );
}
