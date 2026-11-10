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
}) {
  const [skipped, setSkipped] = useState("");
  const recovery = node.contextRecovery;
  if (!recovery) return null;
  const identities = skipped.split(/[,，\s]+/).filter(Boolean);
  return (
    <section aria-label="节点上下文等待">
      <Alert
        type="warning"
        title={`节点 ${node.nodeId} 输入整理至第${recovery.level}档仍无法发送`}
        description="已完成节点保留。重试只处理当前节点，不批准科研结果；必需、直接依赖和指令点名证据不能跳过。"
      />
      {typeof recovery.reason === "string" && <p>{recovery.reason}</p>}
      <ul>
        {recovery.evidence.map((row) => (
          <li key={row.id}>
            {row.title}（{row.id}，{row.bytes} 字节，
            {row.required ? "不可跳过" : "可跳过"}）
          </li>
        ))}
      </ul>
      <Input
        aria-label="跳过的非必需证据编号"
        value={skipped}
        maxLength={4000}
        disabled={busy}
        placeholder="填写可跳过的证据编号，以逗号分隔"
        onChange={(event) => setSkipped(event.target.value)}
      />
      <Space wrap>
        <Button disabled={busy} onClick={() => onRetry({ feedback: "" })}>
          重试当前节点
        </Button>
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
        <Button danger disabled={busy} onClick={onStop}>
          停止任务
        </Button>
      </Space>
    </section>
  );
}
