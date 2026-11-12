import {
  AuditOutlined,
  ReloadOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import { Alert, Button, Collapse, Spin, Tag } from "antd";
import { useEffect, useRef, useState } from "react";
import type {
  BusinessFlowNodeState,
  BusinessFlowNodeTrace as NodeTrace,
} from "../api/generated/types.gen";
import { businessFlowsApi } from "../api/businessFlows";
import { useComputeText } from "../compute/ui";
import ThinkingStream from "../agent/ThinkingStream";
import "./business-flow-node-trace.css";

const strengths: Record<string, string> = {
  low: "轻量",
  medium: "标准",
  xhigh: "深度",
};
const statuses: Record<string, string> = {
  requesting: "等待模型",
  thinking: "思考中",
  responding: "响应中",
  validating: "校验中",
  complete: "已完成",
  failed: "未完成",
  succeeded: "已完成",
  accepted: "审核通过",
  rejected: "要求返修",
  changes_requested: "要求返修",
};

export default function BusinessFlowNodeTrace({
  flowId,
  nodeId,
  state,
}: {
  flowId: string;
  nodeId: string;
  state?: BusinessFlowNodeState;
}) {
  const ui = useComputeText();
  const [trace, setTrace] = useState<NodeTrace>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const request = useRef<AbortController | null>(null);
  const latest = useRef({ flowId, nodeId });
  latest.current = { flowId, nodeId };
  async function read(offset = 0) {
    request.current?.abort();
    const pending = new AbortController();
    request.current = pending;
    setBusy(true);
    setError("");
    try {
      const value = await businessFlowsApi.nodeTrace(flowId, nodeId, {
        offset,
        signal: pending.signal,
      });
      if (
        pending.signal.aborted ||
        latest.current.flowId !== flowId ||
        latest.current.nodeId !== nodeId
      )
        return;
      setTrace((previous) =>
        offset && previous
          ? {
              ...value,
              requests: [
                ...previous.requests,
                ...value.requests.filter(
                  (row) => !previous.requests.some((old) => old.id === row.id),
                ),
              ],
            }
          : value,
      );
    } catch (reason) {
      if (pending.signal.aborted) return;
      setTrace(undefined);
      setError(
        reason instanceof Error ? reason.message : "暂时无法读取节点记录",
      );
    } finally {
      if (request.current === pending) setBusy(false);
    }
  }
  useEffect(() => {
    void read();
    return () => request.current?.abort();
    // Per-token updates use the existing stream; read full records only at node boundaries.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flowId, nodeId, state?.status, state?.attempt, revision]);
  const actors = [
    {
      role: "executor",
      label: ui("执行智能体", "Executor"),
      value: state?.executor,
    },
    {
      role: "reviewer",
      label: ui("审核智能体", "Reviewer"),
      value: state?.reviewer,
    },
  ];
  return (
    <section
      className="flow-node-trace"
      aria-label={ui(
        "节点思考、响应与行动",
        "Node thinking, responses and actions",
      )}
    >
      <header>
        <strong>{ui("模型与行动记录", "Model and action records")}</strong>
        <Button
          size="small"
          type="text"
          icon={<ReloadOutlined />}
          loading={busy}
          aria-label={ui("读取最新节点记录", "Refresh node records")}
          onClick={() => setRevision((value) => value + 1)}
        />
      </header>
      {error && <Alert type="warning" title={error} showIcon />}
      {busy && !trace && <Spin size="small" />}
      {actors
        .filter(
          (actor) =>
            typeof actor.value?.thinking === "string" &&
            [
              "running",
              "requesting",
              "thinking",
              "responding",
              "validating",
            ].includes(actor.value.status),
        )
        .map((actor) => (
          <details className="flow-node-live-thinking" key={actor.role}>
            <summary>
              {actor.label} ·{" "}
              {ui("本节点实时思考预览", "Live node thinking preview")}
            </summary>
            <ThinkingStream
              text={String(actor.value?.thinking ?? "")}
              working
            />
          </details>
        ))}
      {trace?.historical && (
        <p className="flow-node-trace-note">
          {ui(
            "历史任务仅显示已保存内容；未保存的原始响应不会补造。",
            "Historical tasks show saved content only; missing original replies are not reconstructed.",
          )}
        </p>
      )}
      {trace && trace.requests.length === 0 && (
        <p className="flow-node-trace-note">
          {ui(
            "该节点尚无可读取的模型请求。系统规则汇总和人工决定不产生模型思考。",
            "No readable model requests yet. Rule aggregation and human decisions do not generate model thinking.",
          )}
        </p>
      )}
      <Collapse
        key={trace ? "ready" : "loading"}
        size="small"
        defaultActiveKey={trace?.requests[0]?.id}
        items={trace?.requests.map((row) => ({
          key: row.id,
          label: (
            <span className="flow-node-request-label">
              {row.role === "reviewer" ? <AuditOutlined /> : <RobotOutlined />}
              {row.role === "reviewer"
                ? ui("审核智能体", "Reviewer")
                : ui("执行智能体", "Executor")}
              <small>{statuses[row.status] ?? row.status}</small>
            </span>
          ),
          children: (
            <div className="flow-node-request-body">
              <div className="flow-node-request-meta">
                <span>{row.model}</span>
                <Tag>
                  {row.thinkingEnabled
                    ? `${ui("思考强度", "Thinking effort")} ${strengths[row.reasoningEffort] ?? row.reasoningEffort}`
                    : ui("未启用思考", "Thinking disabled")}
                </Tag>
                <span>
                  {ui(`第 ${row.attempt} 次处理`, `Attempt ${row.attempt}`)}
                </span>
              </div>
              <details open>
                <summary>
                  {ui("实际思考", "Actual thinking")}
                  {row.thinkingChars
                    ? ` · ${row.thinkingChars} ${ui("字", "characters")}`
                    : ""}
                </summary>
                {row.thinkingText ? (
                  <ThinkingStream text={row.thinkingText} working={false} />
                ) : (
                  <p>{ui("没有保存的思考文本。", "No saved thinking text.")}</p>
                )}
                {row.thinkingTruncated && (
                  <small>
                    {ui(
                      "此处为保存的末段，完整接收字数见上方。",
                      "This is the saved tail; the received character count is shown above.",
                    )}
                  </small>
                )}
              </details>
              <details>
                <summary>{ui("实际响应", "Actual response")}</summary>
                {row.response ? (
                  <>
                    <pre>
                      {row.response.content ||
                        ui(
                          "模型未返回结果正文。",
                          "The model returned no response body.",
                        )}
                    </pre>
                    {row.response.truncated && (
                      <small>
                        {ui(
                          "正文达到已有审计体积保护，显示已保存部分。",
                          "The response reached the audit size limit; the saved portion is shown.",
                        )}
                      </small>
                    )}
                  </>
                ) : (
                  <p>
                    {trace?.historical
                      ? ui(
                          "本次历史记录未保存原始响应。",
                          "The original response was not saved in this historical record.",
                        )
                      : ui(
                          "尚无可展示的结果正文。",
                          "No response body is available yet.",
                        )}
                  </p>
                )}
              </details>
              {row.structuredResult && (
                <details>
                  <summary>
                    {ui("已保存的结构化结果", "Saved structured result")}
                  </summary>
                  <pre>{JSON.stringify(row.structuredResult, null, 2)}</pre>
                </details>
              )}
            </div>
          ),
        }))}
      />
      {trace?.nextOffset !== null && trace?.nextOffset !== undefined && (
        <Button
          size="small"
          loading={busy}
          onClick={() => void read(trace.nextOffset!)}
        >
          {ui("读取更早请求", "Load earlier requests")}
        </Button>
      )}
      {!!trace?.actions.length && (
        <section
          className="flow-node-actions"
          aria-label={ui("本节点实际行动", "Actual node actions")}
        >
          <strong>{ui("实际行动", "Actual actions")}</strong>
          {trace.actions.map((action, index) => (
            <details key={`${String(action.step)}:${String(action.action)}`}>
              <summary>
                {typeof action.summary === "string"
                  ? action.summary
                  : `${index + 1}. ${String(action.action ?? "")}`}
              </summary>
              <pre>{JSON.stringify(action, null, 2)}</pre>
            </details>
          ))}
        </section>
      )}
    </section>
  );
}
