import { Alert, Button, Input, Space } from "antd";
import { useState } from "react";
import type {
  BusinessFlowDecision,
  BusinessFlowNodeState,
} from "../api/generated/types.gen";

export default function BusinessFlowContextRecovery({
  node,
  busy,
  onRetry,
  onStop,
  legacy = false,
}: {
  node: BusinessFlowNodeState;
  busy: boolean;
  onRetry: (
    options: Pick<
      BusinessFlowDecision,
      "skipEvidenceIds" | "contextScope" | "feedback"
    >,
  ) => void;
  onStop: () => void;
  legacy?: boolean;
}) {
  const [skipped, setSkipped] = useState("");
  const recovery = node.contextRecovery;
  if (!recovery) return null;
  const identities = skipped.split(/[,，\s]+/).filter(Boolean);
  const callLimit = recovery.kind === "model_call_limit";
  const operatorLimit = recovery.kind === "operator_call_limit";
  const quotaWait = callLimit || operatorLimit;
  const protocolFailure = recovery.kind === "model_protocol_error";
  const nodeLimit = quotaWait && recovery.budgetScope === "node";
  return (
    <section aria-label="节点上下文等待">
      <Alert
        type="warning"
        title={
          protocolFailure
            ? `节点 ${node.nodeId} 审核响应需要重试`
            : quotaWait
              ? `节点 ${node.nodeId} ${operatorLimit ? "算子调用" : "模型请求"}额度不足`
              : `节点 ${node.nodeId} 输入整理至第${recovery.level}档仍无法发送`
        }
        description={
          protocolFailure
            ? "执行结果已保留，可重新请求本次审核；不会重新执行已完成的计算。"
            : nodeLimit
              ? "已达到本节点执行保护上限，请调整执行配置或任务范围后重新发起；当前成果保留。"
              : quotaWait
                ? "已完成成果和计数保留。管理员提高允许额度后可继续，重复点击不会重置计数。"
                : legacy
                  ? "专业流程保留完整科学事实与批准范围，不能在这里跳过或截减；可在调整允许预算后重试。"
                  : "已完成节点保留。重试只处理当前节点，不批准科研结果；必需、直接依赖和指令点名证据不能跳过。"
        }
      />
      {typeof recovery.reason === "string" && <p>{recovery.reason}</p>}
      {callLimit &&
        typeof recovery.usedRequests === "number" &&
        typeof recovery.limit === "number" && (
          <p>
            已用 {recovery.usedRequests}/{recovery.limit} 次模型请求。
          </p>
        )}
      <ul>
        {operatorLimit &&
          typeof recovery.usedOperatorCalls === "number" &&
          typeof recovery.limit === "number" && (
            <li>
              已用 {recovery.usedOperatorCalls}/{recovery.limit} 次算子调用。
            </li>
          )}
        {recovery.evidence.map((row) => (
          <li key={row.id}>
            {row.title}（{row.id}，{row.bytes} 字节，
            {row.required ? "不可跳过" : "可跳过"}）
          </li>
        ))}
      </ul>
      {!legacy && !quotaWait && !protocolFailure && (
        <Input
          aria-label="跳过的非必需证据编号"
          value={skipped}
          maxLength={4000}
          disabled={busy}
          placeholder="填写可跳过的证据编号，以逗号分隔"
          onChange={(event) => setSkipped(event.target.value)}
        />
      )}
      <Space wrap>
        <Button
          disabled={busy || nodeLimit}
          onClick={() => onRetry({ feedback: "" })}
        >
          {protocolFailure
            ? "重试本次审核"
            : quotaWait
              ? "额度更新后继续"
              : "重试当前节点"}
        </Button>
        {!legacy && !quotaWait && !protocolFailure && (
          <>
            <Button
              disabled={busy}
              onClick={() =>
                onRetry({
                  feedback: "只提供每组首项样本及最多250字符文本",
                  contextScope: { maxItems: 1, maxTextCharacters: 250 },
                })
              }
            >
              缩小范围并重试
            </Button>
            <Button
              disabled={busy || !identities.length}
              onClick={() =>
                onRetry({
                  feedback: "跳过指定的非必需证据",
                  skipEvidenceIds: identities,
                })
              }
            >
              跳过所填证据并重试
            </Button>
          </>
        )}
        <Button danger disabled={busy} onClick={onStop}>
          停止任务
        </Button>
      </Space>
    </section>
  );
}
