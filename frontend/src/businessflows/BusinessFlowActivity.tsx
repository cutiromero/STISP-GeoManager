import {
  ApartmentOutlined,
  AuditOutlined,
  CheckOutlined,
  DownOutlined,
  FileTextOutlined,
  PauseOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  RobotOutlined,
  StopOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Alert, Button, Input, Progress, Space, Spin, Tag } from "antd";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type {
  AgentWorkflow,
  AgentWorkflowConfirmation,
  BusinessFlowActorState,
  BusinessFlowEvent,
  BusinessFlowRun,
  AgentWorkflowModelActivity,
  BusinessFlowDecision,
} from "../api/generated/types.gen";
import { businessFlowsApi } from "../api/businessFlows";
import { ApiError } from "../api/client";
import { agentApi } from "../api/agent";
import { approvalSelection } from "../agent/approvalSelection";
import { requestScope } from "../projects/session";
import { useComputeText } from "../compute/ui";
import { createUuid } from "../utils/uuid";
import ThinkingStream from "../agent/ThinkingStream";
import SafeMarkdown from "../agent/SafeMarkdown";
import FieldMappingReview from "../agent/FieldMappingReview";
import BusinessFlowNodeOutputs from "./BusinessFlowNodeOutputs";
import BusinessFlowInputPreparation from "./BusinessFlowInputPreparation";
import BusinessFlowContextRecovery from "./BusinessFlowContextRecovery";
import BusinessFlowNodeRecovery from "./BusinessFlowNodeRecovery";
import BusinessFlowGraph from "./BusinessFlowGraph";
import {
  businessFlowProgress,
  nodeStageProgress,
} from "./businessFlowPresentation";
export { businessFlowProgress } from "./businessFlowPresentation";
import "./business-flows.css";

const WorkflowCard = lazy(() => import("../agent/WorkflowCard"));
const WorkflowReportFile = lazy(() => import("../agent/WorkflowReportFile"));
const terminal = new Set(["succeeded", "failed", "cancelled", "interrupted"]);
const finished = new Set(["succeeded", "completed", "skipped"]);
const nodeActive = new Set([
  "running",
  "executing",
  "executed",
  "reviewing",
  "revising",
  "repairing",
  "waiting_human",
  "waiting_approval",
  "waiting_compute",
  "waiting_context",
  "waiting_recovery",
]);
const statusLabels: Record<string, string> = {
  pending: "尚未开始",
  preparing: "准备中",
  requesting: "等待模型响应",
  responding: "模型输出中",
  validating: "核对输出",
  queued: "等待执行",
  running: "处理中",
  executing: "处理中",
  executed: "处理完成",
  reviewing: "独立审核中",
  revising: "返修中",
  repairing: "返修中",
  waiting_human: "等待您决定",
  waiting_approval: "等待您决定",
  waiting_compute: "算子计算中",
  waiting_context: "等待整理输入",
  waiting_recovery: "等待恢复本节点",
  context_waiting: "等待整理输入",
  succeeded: "已完成",
  completed: "已完成",
  passed: "审核通过",
  accept: "审核通过",
  rejected: "需要返修",
  request_changes: "需要返修",
  changes_requested: "要求修改",
  approved: "已批准",
  skipped: "已跳过",
  not_required: "无需审核",
  failed: "未完成",
  cancelled: "已停止",
  paused: "已暂停",
  interrupted: "已中断",
  unavailable: "结果不可用",
};
const actorLabels = {
  executor: "执行智能体",
  reviewer: "审核智能体",
  human: "您",
  system: "流程",
};
const actorIcons = {
  executor: <RobotOutlined />,
  reviewer: <AuditOutlined />,
  human: <UserOutlined />,
  system: <CheckOutlined />,
};
export function readableBusinessFlowEvents(
  events: readonly BusinessFlowEvent[],
) {
  const result: BusinessFlowEvent[] = [];
  for (const event of events) {
    if (
      !event.message.trim() ||
      [
        "heartbeat",
        "thinking",
        "answer_delta",
        "answer_preview",
        "token",
        "preparing",
        "requesting",
        "responding",
        "validating",
        "completed",
        "accepted",
        "changes_requested",
        "progress",
      ].includes(event.kind)
    )
      continue;
    const previous = result[result.length - 1];
    if (
      previous &&
      event.kind !== "node_tool_step" &&
      previous.nodeId === event.nodeId &&
      previous.actor === event.actor &&
      previous.kind === event.kind &&
      previous.status === event.status
    )
      result[result.length - 1] = event;
    else result.push(event);
  }
  return result;
}
export default function BusinessFlowActivity({
  flow,
  onChanged,
  inspectNode,
  onAccessBlocked,
  modelActivity,
}: {
  flow: BusinessFlowRun;
  onChanged: (flow: BusinessFlowRun) => void;
  inspectNode?: { nodeId: string; request: number };
  onAccessBlocked?: () => void;
  modelActivity?: AgentWorkflowModelActivity;
}) {
  const ui = useComputeText();
  const latest = useRef(flow);
  latest.current = flow;
  const changed = useRef(onChanged);
  changed.current = onChanged;
  const alive = useRef(true);
  const sequence = useRef(0);
  const inFlight = useRef(false);
  const [accessBlocked, setAccessBlocked] = useState(false);
  useEffect(() => {
    if (accessBlocked) onAccessBlocked?.();
  }, [accessBlocked, onAccessBlocked]);
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [selected, setSelected] = useState<string>();
  useEffect(() => {
    if (inspectNode) {
      setSelected(inspectNode.nodeId);
      setExpanded(true);
    }
  }, [inspectNode]);
  const [reportOpen, setReportOpen] = useState(false);
  const [legacyOpen, setLegacyOpen] = useState(false);
  const [legacy, setLegacy] = useState<AgentWorkflow>();
  const [legacyError, setLegacyError] = useState("");
  const [legacyAttempt, setLegacyAttempt] = useState(0);
  const decisionKey = useRef<{ fingerprint: string; key: string } | null>(null);
  const definition = flow.definitionSnapshot;
  const current =
    flow.nodes.find((node) => node.nodeId === flow.currentNode) ??
    flow.nodes.find((node) => nodeActive.has(node.status)) ??
    (flow.status === "succeeded"
      ? flow.nodes[flow.nodes.length - 1]
      : flow.nodes.find((node) => !finished.has(node.status)));
  const currentDefinition = definition.nodes.find(
    (node) => node.id === current?.nodeId,
  );
  const selectedState = selected
    ? flow.nodes.find((node) => node.nodeId === selected)
    : undefined;
  const selectedDefinition = definition.nodes.find(
    (node) => node.id === selectedState?.nodeId,
  );
  const progress = businessFlowProgress(flow);
  const complete = progress.completedNodes;
  const currentStages = currentDefinition
    ? nodeStageProgress(currentDefinition, current)
    : undefined;
  const completedCurrentStages = currentStages
    ? [
        currentStages.executionDone ? ui("执行", "execution") : "",
        currentStages.reviewDone ? ui("独立审核", "independent review") : "",
        currentStages.humanDone ? ui("人工批准", "human approval") : "",
      ].filter(Boolean)
    : [];
  const isTerminal = terminal.has(flow.status);
  const isLegacy = definition.adapter === "geology_generic";
  const controlOnly = flow.nodes.some(
    (node) =>
      node.executor.status === "unavailable" ||
      node.reviewer.status === "unavailable",
  );
  const unavailable = controlOnly || accessBlocked;
  const preparationQuestion =
    flow.inputPreparation?.items.some(
      (item) => item.status === "needs_clarification",
    ) ?? false;
  const preparingInputs =
    flow.inputPreparation &&
    !flow.inputPreparation.ready &&
    flow.inputPreparation.items.some(
      (item) => !["direct", "ready"].includes(item.status),
    );
  const needsHuman = Boolean(
    !preparationQuestion &&
    flow.status !== "paused" &&
    current?.human.required &&
    current.human.status === "pending" &&
    ["waiting_human", "waiting_approval"].includes(current.status) &&
    !isTerminal,
  );
  const events = readableBusinessFlowEvents(flow.events);
  const visibleEvents = expanded ? events.slice(-30) : events.slice(-3);
  const legacyKey = `${flow.id}:${flow.status}:${flow.currentNode}:${current?.human.status ?? ""}`;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      sequence.current++;
    };
  }, []);
  useEffect(() => {
    sequence.current++;
    inFlight.current = false;
    setBusy(undefined);
    setError("");
    setFeedback("");
    setExpanded(false);
    setLegacyOpen(false);
    setLegacy(undefined);
    setReportOpen(false);
    setAccessBlocked(false);
    decisionKey.current = null;
  }, [flow.id]);
  useEffect(() => {
    setFeedback("");
  }, [current?.nodeId, current?.attempt]);
  useEffect(() => {
    if (unavailable) {
      setLegacy(undefined);
      setLegacyOpen(false);
      setReportOpen(false);
    }
  }, [unavailable]);
  useEffect(() => {
    if (!isLegacy || !legacyOpen || unavailable) return;
    const controller = new AbortController();
    setLegacyError("");
    void agentApi
      .workflow(flow.id, { view: "card", signal: controller.signal })
      .then((next) => {
        if (!controller.signal.aborted) setLegacy(next);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) {
          if (
            reason instanceof ApiError &&
            [401, 403, 404].includes(reason.status)
          ) {
            setAccessBlocked(true);
            setError(reason.message);
          }
          setLegacyError(
            reason instanceof Error ? reason.message : "暂时无法打开专业审核",
          );
        }
      });
    return () => controller.abort();
  }, [legacyOpen, isLegacy, unavailable, legacyKey, legacyAttempt]);
  const accept = (next: BusinessFlowRun) => {
    if (!alive.current || next.id !== latest.current.id) return;
    if (next.revision < latest.current.revision) return;
    if (
      next.revision === latest.current.revision &&
      Date.parse(next.updatedAt) < Date.parse(latest.current.updatedAt)
    )
      return;
    setAccessBlocked(false);
    latest.current = next;
    changed.current(next);
  };
  const perform = async (
    action: string,
    request: () => Promise<BusinessFlowRun>,
  ) => {
    if (inFlight.current) return;
    inFlight.current = true;
    const owned = ++sequence.current;
    const id = flow.id;
    const scope = requestScope();
    setBusy(action);
    setError("");
    try {
      const next = await request();
      scope();
      if (
        alive.current &&
        sequence.current === owned &&
        latest.current.id === id
      )
        accept(next);
    } catch (reason) {
      if (
        alive.current &&
        sequence.current === owned &&
        !(reason instanceof Error && reason.name === "AbortError")
      ) {
        if (
          reason instanceof ApiError &&
          [401, 403, 404].includes(reason.status)
        )
          setAccessBlocked(true);
        setError(
          reason instanceof Error ? reason.message : "暂时无法更新业务流",
        );
      }
    } finally {
      if (alive.current && sequence.current === owned) {
        inFlight.current = false;
        setBusy(undefined);
      }
    }
  };
  const decide = (decision: "approve" | "request_changes") => {
    if (!current || !needsHuman || isLegacy) return;
    if (decision === "request_changes" && !feedback.trim()) {
      setError("请说明需要返修的原因，执行智能体才能有针对性地修改。");
      return;
    }
    const value = {
      nodeId: current.nodeId,
      revision: flow.revision,
      decision,
      feedback: feedback.trim(),
    };
    const fingerprint = JSON.stringify([flow.id, value]);
    if (decisionKey.current?.fingerprint !== fingerprint)
      decisionKey.current = { fingerprint, key: createUuid() };
    void perform(decision, () =>
      businessFlowsApi.decide(flow.id, {
        ...value,
        idempotencyKey: decisionKey.current!.key,
      }),
    );
  };
  const legacyAction = async (request: () => Promise<AgentWorkflow>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    const owned = ++sequence.current;
    const id = flow.id;
    const scope = requestScope();
    setBusy("legacy");
    setError("");
    setLegacyError("");
    try {
      const next = await request();
      scope();
      if (
        !alive.current ||
        sequence.current !== owned ||
        latest.current.id !== id
      )
        return;
      setLegacy(next);
      const state = await businessFlowsApi.run(id);
      scope();
      if (alive.current && sequence.current === owned) accept(state);
    } catch (reason) {
      if (
        alive.current &&
        sequence.current === owned &&
        !(reason instanceof Error && reason.name === "AbortError")
      ) {
        if (
          reason instanceof ApiError &&
          [401, 403, 404].includes(reason.status)
        ) {
          setAccessBlocked(true);
          setError(reason.message);
        }
        setLegacyError(
          reason instanceof Error ? reason.message : "专业审核暂未保存，请重试",
        );
      }
    } finally {
      if (alive.current && sequence.current === owned) {
        inFlight.current = false;
        setBusy(undefined);
      }
    }
  };
  const confirmLegacy = (
    review?: Omit<AgentWorkflowConfirmation, "planHash">,
  ) => {
    if (legacy)
      void legacyAction(() =>
        agentApi.confirmWorkflow(legacy.id, legacy.planHash, review),
      );
  };
  return (
    <section
      className={`business-flow-activity${needsHuman ? " needs-human" : ""}`}
      data-business-flow-id={flow.id}
      aria-label={ui("业务流工作状态", "Business flow activity")}
    >
      <header className="business-flow-activity-header">
        <span className="business-flow-activity-symbol">
          <ApartmentOutlined />
        </span>
        <div>
          <span className="business-flow-activity-eyebrow">
            {ui("业务流", "BUSINESS FLOW")} ·{" "}
            {ui("版本已固定", "Version fixed")}
          </span>
          <strong>{flow.name}</strong>
        </div>
        <Tag
          variant="filled"
          color={
            needsHuman
              ? "gold"
              : flow.status === "succeeded"
                ? "success"
                : flow.status === "failed"
                  ? "error"
                  : undefined
          }
        >
          {preparationQuestion
            ? ui("需要补充资料说明", "Input clarification needed")
            : (statusLabels[flow.status] ?? flow.status)}
        </Tag>
      </header>
      <div className="business-flow-activity-progress">
        <Progress
          percent={progress.percent}
          aria-label={ui("业务流阶段进度", "Business flow stage progress")}
          size="small"
          showInfo={false}
          status={
            flow.status === "failed"
              ? "exception"
              : flow.status === "succeeded"
                ? "success"
                : "normal"
          }
        />
        <span>
          {complete}/{definition.nodes.length}{" "}
          {ui("节点已完成", "nodes complete")}
        </span>
      </div>
      {error && (
        <Alert
          type="error"
          showIcon
          title={error}
          action={
            <Button
              size="small"
              aria-label={ui("刷新业务流状态", "Refresh flow state")}
              onClick={() =>
                void perform("refresh", () => businessFlowsApi.run(flow.id))
              }
            >
              {ui("刷新状态", "Refresh")}
            </Button>
          }
        />
      )}
      {!unavailable && (
        <BusinessFlowInputPreparation
          flow={flow}
          onChanged={accept}
          onAccessBlocked={() => setAccessBlocked(true)}
        />
      )}
      {!unavailable && current && !preparingInputs && (
        <div className="business-flow-activity-current">
          <div className="business-flow-current-title">
            <span>
              {ui(
                `当前第 ${Math.max(1, definition.nodes.findIndex((node) => node.id === current.nodeId) + 1)}/${definition.nodes.length} 节点`,
                `Node ${Math.max(1, definition.nodes.findIndex((node) => node.id === current.nodeId) + 1)} of ${definition.nodes.length}`,
              )}
            </span>
            <strong>{currentDefinition?.title ?? current.nodeId}</strong>
            {completedCurrentStages.length > 0 && (
              <small className="business-flow-stage-complete">
                {ui(
                  `已完成${completedCurrentStages.join("与")}`,
                  `Completed ${completedCurrentStages.join(" and ")}`,
                )}
              </small>
            )}
            {current.attempt > 1 && (
              <small>
                {ui(
                  `第 ${current.attempt} 次处理`,
                  `Attempt ${current.attempt}`,
                )}
              </small>
            )}
          </div>
          <div className="business-flow-actors">
            <Actor
              key={`${current.nodeId}:executor`}
              name="executor"
              value={current.executor}
              flowStatus={flow.status}
            />
            {currentDefinition?.review.ai && (
              <Actor
                key={`${current.nodeId}:reviewer`}
                name="reviewer"
                value={current.reviewer}
                flowStatus={flow.status}
              />
            )}
          </div>
          <BusinessFlowNodeOutputs
            node={current}
            title={currentDefinition?.title ?? current.nodeId}
            revision={flow.revision}
          />
        </div>
      )}
      {unavailable && (
        <p className="business-flow-activity-note">
          {accessBlocked
            ? ui(
                "访问权限已变化，处理内容已隐藏。",
                "Access has changed; processing content is hidden.",
              )
            : ui(
                "任务已停止。此前的处理正文不再在此处展示。",
                "The task has stopped. Previous processing content is no longer displayed here.",
              )}
        </p>
      )}
      {!unavailable &&
        current?.contextManagement &&
        current.contextManagement.level > 0 && (
          <section aria-label="本节点输入整理说明">
            <Alert
              type="info"
              title={`本节点输入已整理 · 第${current.contextManagement.level}档`}
            />
            {Boolean(current.contextManagement.noticeSummary?.length) && (
              <details>
                <summary>查看输入省略范围</summary>
                <ul>
                  {current.contextManagement.noticeSummary?.map((notice) => (
                    <li key={notice}>{notice}</li>
                  ))}
                </ul>
              </details>
            )}
          </section>
        )}
      {!unavailable && currentDefinition?.contract && (
        <section aria-label="节点执行合同">
          <strong>节点目标：{currentDefinition.contract.goal}</strong>
          <p>验收条件：{currentDefinition.contract.acceptance.join("；")}</p>
          <p>
            必需输出：
            {currentDefinition.contract.requiredOutputs
              .map((output) => `${output.name}（${output.semanticType}）`)
              .join("、")}
          </p>
          <p>允许工具：{currentDefinition.contract.tools.join("、")}</p>
          <p>
            步数 {current?.toolProgress?.steps ?? 0}/
            {currentDefinition.contract.maxSteps ?? 32}；模型调用{" "}
            {current?.toolProgress?.modelCalls ?? 0}/
            {currentDefinition.contract.maxModelCalls ?? 32}；算子调用{" "}
            {current?.toolProgress?.operatorCalls ?? 0}/
            {currentDefinition.contract.maxOperatorCalls ?? 6}
          </p>
        </section>
      )}
      {!unavailable &&
        !isTerminal &&
        flow.status === "waiting_approval" &&
        current?.recovery && (
          <BusinessFlowNodeRecovery
            key={`${flow.id}:${current.nodeId}:${flow.revision}`}
            node={current}
            busy={Boolean(busy)}
            legacy={isLegacy}
            onDecide={(options) => {
              const value = {
                nodeId: current.nodeId,
                revision: flow.revision,
                ...options,
              };
              const fingerprint = JSON.stringify([flow.id, value]);
              if (decisionKey.current?.fingerprint !== fingerprint)
                decisionKey.current = { fingerprint, key: createUuid() };
              void perform(options.decision, () =>
                businessFlowsApi.decide(flow.id, {
                  ...value,
                  idempotencyKey: decisionKey.current!.key,
                }),
              );
            }}
            onStop={() =>
              void perform("cancel", () => businessFlowsApi.cancel(flow.id))
            }
          />
        )}
      {!unavailable &&
        !isTerminal &&
        flow.status === "waiting_approval" &&
        current?.contextRecovery && (
          <BusinessFlowContextRecovery
            key={`${flow.id}:${current.nodeId}:${flow.revision}`}
            node={current}
            busy={Boolean(busy)}
            legacy={isLegacy}
            onRetry={(
              options: Pick<
                BusinessFlowDecision,
                "skipEvidenceIds" | "contextScope" | "feedback"
              >,
            ) => {
              const value = {
                nodeId: current.nodeId,
                revision: flow.revision,
                decision: "retry_context" as const,
                ...options,
              };
              const fingerprint = JSON.stringify([flow.id, value]);
              if (decisionKey.current?.fingerprint !== fingerprint)
                decisionKey.current = { fingerprint, key: createUuid() };
              void perform("retry_context", () =>
                businessFlowsApi.decide(flow.id, {
                  ...value,
                  idempotencyKey: decisionKey.current!.key,
                }),
              );
            }}
            onStop={() =>
              void perform("cancel", () => businessFlowsApi.cancel(flow.id))
            }
          />
        )}
      {!unavailable &&
        needsHuman &&
        (isLegacy ? (
          <div className="business-flow-human-decision">
            <UserOutlined />
            <div>
              <strong>
                {ui("这一步需要您亲自确认", "Your decision is required")}
              </strong>
              <p>
                {ui(
                  "请在专业审核区核对资料、字段或处置范围。AI 审核通过不等于您的批准。",
                  "Check data, fields or disposition choices in the professional review. AI acceptance is not your approval.",
                )}
              </p>
            </div>
            <Button type="primary" onClick={() => setLegacyOpen(true)}>
              {ui("打开专业审核", "Open professional review")}
            </Button>
          </div>
        ) : (
          <section
            className="business-flow-human-review"
            aria-label={ui("人工决定", "Human decision")}
          >
            <div className="business-flow-human-heading">
              <UserOutlined />
              <strong>{ui("等待您的决定", "Waiting for your decision")}</strong>
            </div>
            <p>
              {current?.human.reason ||
                ui(
                  "独立审核不会替代人工批准，请明确选择通过或返修。",
                  "Independent review cannot grant human approval. Choose approval or revision explicitly.",
                )}
            </p>
            <Input.TextArea
              aria-label={ui("审核反馈", "Review feedback")}
              value={feedback}
              maxLength={4000}
              autoSize={{ minRows: 2, maxRows: 5 }}
              disabled={Boolean(busy)}
              onChange={(event) => setFeedback(event.target.value)}
              placeholder={ui(
                "如需返修，请写明原因或补充要求。",
                "For a revision, explain the reason or additional requirements.",
              )}
            />
            <Space wrap>
              <Button
                type="primary"
                icon={<CheckOutlined />}
                aria-label={ui("批准当前节点", "Approve current node")}
                loading={busy === "approve"}
                disabled={Boolean(busy)}
                onClick={() => decide("approve")}
              >
                {ui("批准并继续", "Approve and continue")}
              </Button>
              <Button
                icon={<ReloadOutlined />}
                aria-label={ui("要求返修", "Request revision")}
                title={
                  current &&
                  current.attempt >
                    (definition.nodes.find((node) => node.id === current.nodeId)
                      ?.review.maxRevisions ?? 0)
                    ? ui(
                        "已到返修上限，可停止后调整流程重新发起",
                        "Revision limit reached; start an adjusted flow",
                      )
                    : undefined
                }
                loading={busy === "request_changes"}
                disabled={
                  Boolean(busy) ||
                  Boolean(
                    current &&
                    current.attempt >
                      (definition.nodes.find(
                        (node) => node.id === current.nodeId,
                      )?.review.maxRevisions ?? 0),
                  )
                }
                onClick={() => decide("request_changes")}
              >
                {ui("退回返修", "Request revision")}
              </Button>
            </Space>
          </section>
        ))}
      {!unavailable && visibleEvents.length > 0 && (
        <ol
          className="business-flow-activity-events"
          aria-label={ui("执行与审核交互", "Execution and review activity")}
        >
          {visibleEvents.map((event) => (
            <li key={event.id} className={`actor-${event.actor}`}>
              <span className="business-flow-event-symbol">
                {actorIcons[event.actor]}
              </span>
              <div>
                <span>{actorLabels[event.actor]}</span>
                <p>{event.message}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
      {expanded && !unavailable && (
        <div className="business-flow-activity-diagram">
          <BusinessFlowGraph
            nodes={definition.nodes}
            states={flow.nodes}
            events={flow.events}
            currentNode={flow.currentNode}
            flowStatus={flow.status}
            compact
            selectedNode={selected ?? current?.nodeId}
            onSelectNode={(node) => setSelected(node.id)}
          />
          {selectedState && selectedState.nodeId !== current?.nodeId && (
            <section
              className="business-flow-selected-node"
              aria-label={ui("所选节点结果", "Selected node results")}
            >
              <h4>{selectedDefinition?.title ?? selectedState.nodeId}</h4>
              <p className="business-flow-activity-note">
                {selectedDefinition?.description}
              </p>
              <div className="business-flow-actors">
                <Actor
                  name="executor"
                  value={selectedState.executor}
                  flowStatus={
                    finished.has(selectedState.status)
                      ? "succeeded"
                      : flow.status
                  }
                />
                {selectedDefinition?.review.ai && (
                  <Actor
                    name="reviewer"
                    value={selectedState.reviewer}
                    flowStatus={
                      finished.has(selectedState.status)
                        ? "succeeded"
                        : flow.status
                    }
                  />
                )}
              </div>
              <BusinessFlowNodeOutputs
                node={selectedState}
                title={selectedDefinition?.title ?? selectedState.nodeId}
                revision={flow.revision}
              />
            </section>
          )}
        </div>
      )}
      <footer className="business-flow-activity-actions">
        <Space wrap align="center" size={8}>
          <Button
            type="text"
            size="small"
            icon={<DownOutlined rotate={expanded ? 180 : 0} />}
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded
              ? ui("收起流程记录", "Hide flow details")
              : ui("查看流程与记录", "View flow and history")}
          </Button>
          {!isTerminal && flow.status !== "paused" && (
            <Button
              type="text"
              size="small"
              icon={<PauseOutlined />}
              aria-label={ui("暂停业务流", "Pause flow")}
              disabled={Boolean(busy)}
              loading={busy === "pause"}
              onClick={() =>
                void perform("pause", () => businessFlowsApi.pause(flow.id))
              }
            >
              {ui("暂停", "Pause")}
            </Button>
          )}
          {flow.status === "paused" && (
            <Button
              size="small"
              icon={<PlayCircleOutlined />}
              aria-label={ui("继续业务流", "Resume flow")}
              disabled={Boolean(busy)}
              loading={busy === "resume"}
              onClick={() =>
                void perform("resume", () => businessFlowsApi.resume(flow.id))
              }
            >
              {ui("继续业务流", "Resume flow")}
            </Button>
          )}
          {!isTerminal && (
            <Button
              type="text"
              size="small"
              danger
              icon={<StopOutlined />}
              aria-label={ui("停止业务流", "Stop flow")}
              disabled={Boolean(busy)}
              loading={busy === "cancel"}
              onClick={() =>
                void perform("cancel", () => businessFlowsApi.cancel(flow.id))
              }
            >
              {ui("停止", "Stop")}
            </Button>
          )}
          {isLegacy && !needsHuman && !unavailable && (
            <Button
              type="text"
              size="small"
              icon={<FileTextOutlined />}
              onClick={() => setLegacyOpen((value) => !value)}
            >
              {legacyOpen
                ? ui("收起专业详情", "Hide professional details")
                : isTerminal
                  ? ui("查看专业成果", "View professional results")
                  : ui("打开专业审核", "Open professional review")}
            </Button>
          )}
          {flow.status === "succeeded" && !unavailable && !legacyOpen && (
            <Button
              size="small"
              icon={<FileTextOutlined />}
              aria-label={ui("报告与成果", "Report and results")}
              onClick={() => setReportOpen((value) => !value)}
            >
              {ui("报告与成果", "Report and results")}
            </Button>
          )}
        </Space>
      </footer>
      {legacyOpen && isLegacy && !unavailable && (
        <div className="business-flow-legacy-review">
          {legacyError && (
            <Alert
              type="error"
              showIcon
              title={legacyError}
              action={
                <Button
                  size="small"
                  onClick={() => setLegacyAttempt((value) => value + 1)}
                >
                  {ui("重试", "Retry")}
                </Button>
              }
            />
          )}
          <Suspense fallback={<Spin />}>
            {legacy ? (
              <WorkflowCard
                workflow={modelActivity ? { ...legacy, modelActivity } : legacy}
                compact
                busy={Boolean(busy)}
                reviewError={legacyError}
                onConfirm={() => confirmLegacy()}
                onCancel={() =>
                  void perform("cancel", () => businessFlowsApi.cancel(flow.id))
                }
                onPause={() =>
                  void perform("pause", () => businessFlowsApi.pause(flow.id))
                }
                onResume={() =>
                  void perform("resume", () => businessFlowsApi.resume(flow.id))
                }
                onReview={(decision, value, ids, actions) =>
                  void legacyAction(async () =>
                    agentApi.confirmWorkflow(legacy.id, legacy.planHash, {
                      decision,
                      feedback: value,
                      ...(await approvalSelection(legacy, ids)),
                      ...(actions ? { alterationActions: actions } : {}),
                    }),
                  )
                }
                onReviewRetained={() =>
                  void legacyAction(() =>
                    agentApi.reviewRetainedWorkflow(legacy.id, legacy.planHash),
                  )
                }
                onRetryImports={() =>
                  void legacyAction(() =>
                    agentApi.retryWorkflowImports(legacy.id, legacy.planHash),
                  )
                }
                inputReview={
                  legacy.plan.phase === "review_mapping" &&
                  legacy.plan.fieldMappingReview ? (
                    <FieldMappingReview
                      workspace
                      startAnalysis
                      compact
                      key={`${legacy.id}:${legacy.planHash}`}
                      review={legacy.plan.fieldMappingReview}
                      busy={Boolean(busy)}
                      onConfirm={(mapping, automatic) =>
                        confirmLegacy({
                          fieldMapping: mapping,
                          executeAfterMapping: true,
                          applyRuleSuggestions: automatic,
                        })
                      }
                    />
                  ) : undefined
                }
              />
            ) : !legacyError ? (
              <Spin />
            ) : null}
          </Suspense>
        </div>
      )}
      {reportOpen &&
        flow.status === "succeeded" &&
        !unavailable &&
        !legacyOpen && (
          <div className="business-flow-report">
            <Suspense fallback={<Spin />}>
              <WorkflowReportFile
                workflowId={flow.id}
                projectId={flow.projectId}
              />
            </Suspense>
          </div>
        )}
    </section>
  );
}
function Actor({
  name,
  value,
  flowStatus,
}: {
  name: "executor" | "reviewer";
  value: BusinessFlowActorState;
  flowStatus: string;
}) {
  const ui = useComputeText();
  const [answerExpanded, setAnswerExpanded] = useState(false);
  const interrupted =
    ["paused", "cancelled", "failed", "interrupted"].includes(flowStatus) &&
    [
      "preparing",
      "requesting",
      "responding",
      "validating",
      "running",
      "reviewing",
    ].includes(value.status);
  const audit = value.audit;
  const readableModel =
    audit &&
    typeof audit === "object" &&
    !Array.isArray(audit) &&
    typeof (audit as Record<string, unknown>).modelName === "string" &&
    String((audit as Record<string, unknown>).modelName).trim()
      ? String((audit as Record<string, unknown>).modelName)
      : value.model;
  const thinking = typeof value.thinking === "string" ? value.thinking : "";
  const repair =
    typeof value.repairInstructions === "string" &&
    ["rejected", "request_changes"].includes(value.status)
      ? value.repairInstructions
      : "";
  return (
    <section
      className={`business-flow-actor actor-${name}`}
      aria-label={actorLabels[name]}
    >
      <span className="business-flow-actor-icon">{actorIcons[name]}</span>
      <div>
        <div className="business-flow-actor-heading">
          <strong>{actorLabels[name]}</strong>
          <span>
            {statusLabels[interrupted ? flowStatus : value.status] ??
              value.status}
          </span>
        </div>
        {readableModel && <small>{readableModel}</small>}
        {thinking && (
          <details className="business-flow-actor-thinking">
            <summary>{ui("查看模型思考", "View model thinking")}</summary>
            <ThinkingStream
              text={thinking}
              working={
                !interrupted &&
                [
                  "preparing",
                  "requesting",
                  "responding",
                  "validating",
                  "running",
                  "reviewing",
                ].includes(value.status)
              }
            />
          </details>
        )}
        {value.answer && (
          <div className="business-flow-actor-answer">
            <SafeMarkdown
              text={
                !answerExpanded && value.answer.length > 600
                  ? value.answer.slice(0, 420) + "…"
                  : value.answer
              }
            />
            {value.answer.length > 600 && (
              <Button
                type="link"
                size="small"
                aria-expanded={answerExpanded}
                onClick={() => setAnswerExpanded((value) => !value)}
              >
                {answerExpanded
                  ? ui("收起分析", "Collapse analysis")
                  : ui("展开完整分析", "Read full analysis")}
              </Button>
            )}
          </div>
        )}
        {(value.reason || value.feedback) && (
          <p
            className={
              name === "reviewer" && value.status === "rejected"
                ? "is-rejection"
                : ""
            }
          >
            {value.feedback || value.reason}
          </p>
        )}
        {repair && (
          <p className="is-rejection">
            <strong>{ui("返修要求：", "Revision request: ")}</strong>
            {repair}
          </p>
        )}
        {!value.answer && !value.reason && !value.feedback && !repair && (
          <p>
            {name === "executor"
              ? ui(
                  "按冻结的流程规范处理资料与任务。",
                  "Processing data and tasks under the frozen flow definition.",
                )
              : ui(
                  "只审核实际结果与依据，不代替人工批准。",
                  "Reviewing actual results and evidence without granting human approval.",
                )}
          </p>
        )}
      </div>
    </section>
  );
}
