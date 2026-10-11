import { Alert, Button, Input, InputNumber, Select, Tag } from "antd";
import { useEffect, useRef, useState } from "react";
import { agentApi } from "../api/agent";
import type {
  AgentResearchIntent,
  AgentResearchIntentUpdate,
  AgentRun,
  AgentWorkflow,
} from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";
import WorkflowResults from "./WorkflowResults";

const active = ["queued", "running", "waiting_compute", "waiting_approval"];
const labels: Record<AgentResearchIntent["status"], [string, string]> = {
  clarifying: ["需要您补充", "Your input is needed"],
  planning: ["正在分析任务", "Planning the task"],
  running: ["正在推进研究", "Research in progress"],
  waiting_approval: ["等待审核", "Review needed"],
  succeeded: ["研究已完成", "Research completed"],
  failed: ["任务未完成", "Research incomplete"],
  cancelled: ["任务已停止", "Research stopped"],
};

export default function ResearchIntentCard({
  run,
  onChanged,
}: {
  run: AgentRun & { researchIntent: AgentResearchIntent };
  onChanged: (next: AgentRun) => void;
}) {
  const ui = useComputeText();
  const intent = run.researchIntent;
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [answer, setAnswer] = useState("");
  const [workflow, setWorkflow] = useState<AgentWorkflow>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const onUpdate = useRef(onChanged);
  onUpdate.current = onChanged;
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
    setAnswers({});
    setAnswer("");
    setError("");
  }, [intent.revision]);
  useEffect(() => {
    const id = intent.workflowId;
    if (!id) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    setWorkflow(undefined);
    const poll = async () => {
      try {
        const next = await agentApi.workflow(id);
        if (disposed) return;
        setError("");
        failures = 0;
        const latest = await agentApi.poll(intent.originRunId);
        if (disposed) return;
        setWorkflow(next);
        if (
          JSON.stringify(latest.run.researchIntent) !==
          JSON.stringify(currentIntent.current)
        )
          onUpdate.current(latest.run);
        if (active.includes(next.status))
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
    };
  }, [intent.workflowId, run.id]);
  const update = async (action: AgentResearchIntentUpdate["action"]) => {
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
        ...(action === "answer" ? { answers, answer: answer.trim() } : {}),
      });
      if (alive.current) onUpdate.current(next);
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
        <strong>{intent.goal}</strong>
        <Tag color="blue">{ui(...status)}</Tag>
      </div>
      <p className="agent-research-message" role="status">
        {intent.message}
      </p>
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
            <Button disabled={busy} onClick={() => void update("cancel")}>
              {ui("停止任务", "Stop task")}
            </Button>
          </div>
        </div>
      )}
      {error && <Alert type="error" title={error} />}
      {workflow && (
        <WorkflowResults
          compact
          workflow={workflow}
          busy={busy}
          onConfirm={() => void update("confirm")}
          onCancel={() => void update("cancel")}
        />
      )}
    </section>
  );
}
