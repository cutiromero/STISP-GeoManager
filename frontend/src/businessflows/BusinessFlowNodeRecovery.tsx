import { Alert, Button, Input, Space } from "antd";
import { useState } from "react";
import type {
  BusinessFlowDecision,
  BusinessFlowNodeState,
} from "../api/generated/types.gen";

type RecoveryOptions = Pick<
  BusinessFlowDecision,
  "decision" | "feedback" | "recoveryInputs" | "recoveryParameters"
>;

export default function BusinessFlowNodeRecovery({
  node,
  busy,
  legacy,
  onDecide,
  onStop,
}: {
  node: BusinessFlowNodeState;
  busy: boolean;
  legacy: boolean;
  onDecide: (options: RecoveryOptions) => void;
  onStop: () => void;
}) {
  const [answer, setAnswer] = useState("");
  const [inputs, setInputs] = useState("{}");
  const [parameters, setParameters] = useState("{}");
  const [error, setError] = useState("");
  const recovery = node.recovery;
  if (!recovery) return null;
  const retry = () => {
    try {
      const replacements: unknown = JSON.parse(inputs);
      const adjustments: unknown = JSON.parse(parameters);
      if (
        !replacements ||
        Array.isArray(replacements) ||
        typeof replacements !== "object" ||
        !adjustments ||
        Array.isArray(adjustments) ||
        typeof adjustments !== "object"
      ) {
        setError("资料与参数必须是 JSON 对象。");
        return;
      }
      setError("");
      onDecide({
        decision: "retry_recovery",
        feedback: answer,
        recoveryInputs: replacements as BusinessFlowDecision["recoveryInputs"],
        recoveryParameters:
          adjustments as BusinessFlowDecision["recoveryParameters"],
      });
    } catch {
      setError('请检查 JSON 格式，例如 {"source":123}。');
    }
  };
  return (
    <section aria-label="节点失败恢复">
      <Alert
        type="warning"
        title="本节点需要处理，已完成节点保留"
        description={recovery.reason}
      />
      {recovery.question && <p>{recovery.question}</p>}
      <h4>已尝试的补救</h4>
      {recovery.attempts.length ? (
        <ul>
          {recovery.attempts.map((attempt) => (
            <li key={attempt}>{attempt}</li>
          ))}
        </ul>
      ) : (
        <p>尚未自动补救。</p>
      )}
      {error && <Alert type="error" title={error} />}
      <Input.TextArea
        aria-label="恢复说明或回答"
        value={answer}
        disabled={busy}
        maxLength={4000}
        placeholder="说明资料含义、回答智能体的问题或调整原因"
        onChange={(event) => setAnswer(event.target.value)}
      />
      {!legacy && (
        <>
          <label>
            更换输入数据（角色 → 当前项目资源编号，JSON）
            <Input
              aria-label="恢复输入数据"
              value={inputs}
              disabled={busy}
              maxLength={4000}
              onChange={(event) => setInputs(event.target.value)}
            />
          </label>
          <label>
            调整参数（JSON；后端仍校验清单）
            <Input
              aria-label="恢复算子参数"
              value={parameters}
              disabled={busy}
              maxLength={4000}
              onChange={(event) => setParameters(event.target.value)}
            />
          </label>
        </>
      )}
      {legacy && (
        <p>专业流程仅重试原阶段；资料、参数与批准范围仍在原专业审核中处理。</p>
      )}
      <Space wrap>
        <Button
          disabled={busy || !recovery.options.includes("retry_recovery")}
          onClick={retry}
        >
          从本节点继续
        </Button>
        {recovery.allowSkip && !legacy && (
          <Button
            disabled={busy}
            onClick={() =>
              onDecide({ decision: "skip_node", feedback: answer })
            }
          >
            跳过本节点
          </Button>
        )}
        <Button danger disabled={busy} onClick={onStop}>
          停止任务
        </Button>
      </Space>
      <p>恢复不批准科研结果，也不重置调用与执行预算。</p>
    </section>
  );
}
