import {
  Alert,
  Button,
  Input,
  InputNumber,
  Popconfirm,
  Select,
  Tag,
} from "antd";
import { useEffect, useRef, useState } from "react";
import { agentApi } from "../api/agent";
import type {
  AgentResearchIntent,
  AgentResearchIntentUpdate,
  AgentRun,
  AgentWorkflow,
} from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";
import WorkflowCard from "./WorkflowCard";
import LiveActivity from "./LiveActivity";
import { runActivity } from "./agentActivity";
import { workflowStatusLabels } from "./workflowFeedback";
import { briefTitle } from "./researchText";
import FieldMappingReview from "./FieldMappingReview";

const active = ["queued", "running", "waiting_compute", "waiting_approval"];
const labels: Record<AgentResearchIntent["status"], [string, string]> = {
  clarifying: ["需要您补充", "Your input is needed"],
  planning: ["正在分析任务", "Planning the task"],
  running: ["正在推进研究", "Research in progress"],
  waiting_approval: ["等待审核", "Review needed"],
  succeeded: ["研究已完成", "Research completed"],
  failed: ["执行失败", "Research failed"],
  cancelled: ["任务已停止", "Research stopped"],
};

export default function ResearchIntentCard({
  run,
  onChanged,
  onWorkflowChange,
  onRestart,
}: {
  run: AgentRun & { researchIntent: AgentResearchIntent };
  onChanged: (next: AgentRun) => void;
  onWorkflowChange?: (next: AgentWorkflow | undefined) => void;
  onRestart?: () => void;
}) {
  const ui = useComputeText();
  const intent = run.researchIntent;
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [answer, setAnswer] = useState("");
  const [workflow, setWorkflow] = useState<AgentWorkflow>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [workflowRevision, setWorkflowRevision] = useState(0);
  const inFlight = useRef(false);
  const onUpdate = useRef(onChanged);
  onUpdate.current = onChanged;
  const onWorkflow = useRef(onWorkflowChange);
  onWorkflow.current = onWorkflowChange;
  const currentIntent = useRef(intent);
  currentIntent.current = intent;
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    const suggested = intent.parameters.roleAnswers;
    setAnswers(
      suggested && typeof suggested === "object"
        ? Object.fromEntries(
            Object.entries(suggested).filter(
              (entry): entry is [string, string] =>
                typeof entry[1] === "string",
            ),
          )
        : {},
    );
    setAnswer("");
    setError("");
  }, [intent.revision]);
  useEffect(() => setWorkflow(undefined), [intent.workflowId]);
  useEffect(() => {
    const id = intent.workflowId;
    if (!id) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    const poll = async () => {
      try {
        const generic = intent.scenario === "geology_generic";
        const [card, prior] = await Promise.all([
          agentApi.workflow(id, { view: "card" }),
          !generic && active.includes(currentIntent.current.status)
            ? agentApi.poll(intent.originRunId)
            : Promise.resolve(undefined),
        ]);
        if (disposed) return;
        const status =
          card.status === "queued"
            ? "planning"
            : ["waiting_compute", "paused"].includes(card.status)
              ? "running"
              : card.status;
        const [next, latest] = await Promise.all([
          generic && card.status === "waiting_approval"
            ? agentApi.workflow(id)
            : Promise.resolve(card),
          generic && status !== currentIntent.current.status
            ? agentApi.poll(intent.originRunId)
            : Promise.resolve(prior),
        ]);
        if (disposed) return;
        setError("");
        failures = 0;
        setWorkflow(next);
        onWorkflow.current?.(next);
        if (
          latest &&
          JSON.stringify(latest.run.researchIntent) !==
            JSON.stringify(currentIntent.current)
        )
          onUpdate.current(latest.run);
        if (
          active.includes(next.status) &&
          !(
            intent.scenario === "geology_generic" &&
            next.status === "waiting_approval"
          )
        )
          timer = setTimeout(poll, document.hidden ? 6000 : 1800);
      } catch (reason) {
        if (disposed) return;
        setError(
          reason instanceof Error
            ? reason.message
            : ui("无法读取研究进度", "Unable to read research progress"),
        );
        if (
          typeof reason === "object" &&
          reason &&
          "status" in reason &&
          [401, 403, 404].includes(Number(reason.status))
        ) {
          setWorkflow(undefined);
          onWorkflow.current?.(undefined);
          return;
        }
        failures++;
        timer = setTimeout(poll, Math.min(15000, failures * 3000));
      }
    };
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
      onWorkflow.current?.(undefined);
    };
  }, [intent.workflowId, run.id, workflowRevision]);
  const confirmMapping = async (
    fieldMapping: Record<string, Record<string, string | null>>,
  ) => {
    if (!workflow || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const next = await agentApi.confirmWorkflow(
        workflow.id,
        workflow.planHash,
        { fieldMapping },
      );
      if (!alive.current) return;
      setWorkflow(next);
      onWorkflow.current?.(next);
      const latest = await agentApi.poll(intent.originRunId);
      if (!alive.current) return;
      onUpdate.current(latest.run);
      setWorkflowRevision((value) => value + 1);
    } catch (reason) {
      if (alive.current)
        setError(
          reason instanceof Error ? reason.message : "字段确认失败，请重试",
        );
    } finally {
      inFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const controlWorkflow = async (action: "pause" | "resume") => {
    if (!workflow || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const next =
        action === "pause"
          ? await agentApi.pauseWorkflow(workflow.id)
          : await agentApi.resumeWorkflow(workflow.id);
      if (!alive.current) return;
      setWorkflow(next);
      onWorkflow.current?.(next);
      if (action === "resume") setWorkflowRevision((value) => value + 1);
    } catch (reason) {
      if (alive.current)
        setError(
          reason instanceof Error ? reason.message : "暂时无法更新任务状态",
        );
    } finally {
      inFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const reviewWorkflow = async (
    decision: "approve" | "reject",
    feedback: string,
    selectedSuggestionIds?: string[],
  ) => {
    if (!workflow || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const next = await agentApi.confirmWorkflow(
        workflow.id,
        workflow.planHash,
        {
          decision,
          feedback,
          ...(selectedSuggestionIds ? { selectedSuggestionIds } : {}),
        },
      );
      if (!alive.current) return;
      setWorkflow(next);
      onWorkflow.current?.(next);
      const latest = await agentApi.poll(intent.originRunId);
      if (!alive.current) return;
      onUpdate.current(latest.run);
      setWorkflowRevision((value) => value + 1);
    } catch (reason) {
      if (alive.current)
        setError(
          reason instanceof Error
            ? reason.message
            : "审核反馈暂未保存，请重试。",
        );
    } finally {
      inFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const update = async (
    action: AgentResearchIntentUpdate["action"],
    explicitAnswer?: string,
  ) => {
    if (inFlight.current) return;
    if (
      action === "answer" &&
      !answer.trim() &&
      intent.questions.some(
        (question) => question.required && !answers[question.key]?.trim(),
      )
    ) {
      setError(
        ui(
          "请回答必填问题，或在补充说明中告诉智能体您的选择。",
          "Answer the required questions or explain your choice below.",
        ),
      );
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const next = await agentApi.updateResearchIntent(intent.originRunId, {
        action,
        revision: intent.revision,
        ...(action === "answer"
          ? intent.scenario === "geology_generic" && answer.trim()
            ? { answer: explicitAnswer ?? answer.trim() }
            : { answers, answer: answer.trim() }
          : {}),
        ...(explicitAnswer ? { answer: explicitAnswer, answers: {} } : {}),
      });
      if (alive.current) {
        onUpdate.current(next);
        if (workflow && intent.scenario === "geology_generic")
          setWorkflowRevision((value) => value + 1);
      }
    } catch (reason) {
      if (alive.current)
        setError(
          reason instanceof Error
            ? reason.message
            : ui("暂时无法继续，请重试", "Unable to continue. Try again."),
        );
    } finally {
      inFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const status = labels[intent.status];
  return (
    <section
      className="agent-research-intent"
      aria-label={ui("科研任务", "Research task")}
    >
      <div className="agent-research-heading">
        <strong title={intent.goal}>{briefTitle(intent.goal)}</strong>
        <Tag color={workflow?.status === "failed" ? "red" : "blue"}>
          {workflow ? workflowStatusLabels[workflow.status] : ui(...status)}
        </Tag>
      </div>
      {briefTitle(intent.goal) !== intent.goal.trim() && (
        <details className="agent-research-goal">
          <summary>{ui("完整需求", "Full request")}</summary>
          <p>{intent.goal}</p>
        </details>
      )}
      {!workflow && <LiveActivity activity={runActivity(run)} />}
      {!!intent.inputSummary.length && (
        <div
          className="agent-research-inputs"
          aria-label={ui("使用的数据", "Selected data")}
        >
          {intent.inputSummary.map((input) => (
            <span key={input.role} title={input.sourceNote}>
              <small>{input.label}</small>
              {input.name}
            </span>
          ))}
        </div>
      )}
      {intent.status === "clarifying" && (
        <div className="agent-research-questions">
          {intent.questions.map((question) => (
            <label key={question.key}>
              <span>
                {question.label}
                {question.required ? " *" : ""}
              </span>
              {question.kind === "choice" || question.kind === "resource" ? (
                <Select
                  aria-label={question.label}
                  value={answers[question.key]}
                  disabled={busy}
                  placeholder={ui("请选择", "Choose an option")}
                  options={question.options}
                  optionRender={(option) => (
                    <div>
                      {option.data.label}
                      {option.data.description && (
                        <small className="agent-question-option-note">
                          {option.data.description}
                        </small>
                      )}
                    </div>
                  )}
                  onChange={(value: string) =>
                    setAnswers((old) => ({ ...old, [question.key]: value }))
                  }
                />
              ) : question.kind === "number" ? (
                <InputNumber
                  aria-label={question.label}
                  disabled={busy}
                  value={
                    answers[question.key] ? Number(answers[question.key]) : null
                  }
                  onChange={(value) =>
                    setAnswers((old) => ({
                      ...old,
                      [question.key]: value === null ? "" : String(value),
                    }))
                  }
                />
              ) : (
                <Input
                  aria-label={question.label}
                  disabled={busy}
                  value={answers[question.key] ?? ""}
                  onChange={(event) =>
                    setAnswers((old) => ({
                      ...old,
                      [question.key]: event.target.value,
                    }))
                  }
                />
              )}
            </label>
          ))}
          <Input.TextArea
            aria-label={ui("补充说明", "Additional explanation")}
            value={answer}
            disabled={busy}
            maxLength={12000}
            autoSize={{ minRows: 2, maxRows: 5 }}
            placeholder={ui(
              "也可以用自己的话回答，或直接在下方聊天框回复",
              "You can also reply in your own words here or in the chat box below",
            )}
            onChange={(event) => setAnswer(event.target.value)}
          />
          <div className="agent-research-actions">
            <Button
              type="primary"
              loading={busy}
              onClick={() => void update("answer")}
            >
              {ui("继续分析", "Continue")}
            </Button>
            <Popconfirm
              title={ui("停止此任务？", "Stop this task?")}
              description={ui(
                "已选资料会保留，任务不再继续分析。",
                "Selected data is preserved; the task will stop.",
              )}
              okText={ui("确认停止", "Stop")}
              cancelText={ui("继续回答", "Keep answering")}
              onConfirm={() => void update("cancel")}
            >
              <Button disabled={busy}>{ui("停止任务", "Stop task")}</Button>
            </Popconfirm>
          </div>
        </div>
      )}
      {error && <Alert type="error" title={error} />}
      {intent.workflowId && !workflow && !error && (
        <p role="status">正在恢复逻辑推理进度…</p>
      )}
      {workflow?.status === "waiting_approval" &&
        workflow.plan.phase === "review_mapping" &&
        workflow.plan.fieldMappingReview && (
          <FieldMappingReview
            compact
            key={`${workflow.id}:${workflow.planHash}`}
            review={workflow.plan.fieldMappingReview}
            busy={busy}
            onConfirm={(mapping) => void confirmMapping(mapping)}
          />
        )}
      {workflow && (
        <>
          {workflow.plan.reusedConfiguration === true && (
            <Alert
              type="info"
              title="沿用上次已确认的角色和字段"
              description="本次仍需确认执行计划，并逐项批准处置。"
              action={
                workflow.status === "waiting_approval" &&
                workflow.plan.phase === "review_plan" ? (
                  <Button
                    disabled={busy}
                    onClick={() => void update("answer", "修改角色和字段")}
                  >
                    修改角色和字段
                  </Button>
                ) : undefined
              }
            />
          )}
          <WorkflowCard
            compact
            workflow={workflow}
            busy={busy}
            onConfirm={
              workflow.plan.phase === "review_mapping"
                ? undefined
                : () => void update("confirm")
            }
            onCancel={() => void update("cancel")}
            onPause={() => void controlWorkflow("pause")}
            onResume={() => void controlWorkflow("resume")}
            onReview={(decision, feedback, selectedSuggestionIds) =>
              void reviewWorkflow(decision, feedback, selectedSuggestionIds)
            }
            onRestart={onRestart}
          />
        </>
      )}
    </section>
  );
}
