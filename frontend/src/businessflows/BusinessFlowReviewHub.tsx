import { AuditOutlined, CheckOutlined, UserOutlined } from "@ant-design/icons";
import { Popover } from "antd";
import type {
  BusinessFlowEvent,
  BusinessFlowNode,
  BusinessFlowNodeState,
} from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";
import {
  businessFlowReturn,
  nodeStageProgress,
} from "./businessFlowPresentation";

export function reviewGateState(
  node: BusinessFlowNode,
  state: BusinessFlowNodeState | undefined,
  role: "ai" | "human",
  events: readonly BusinessFlowEvent[],
  flowStatus?: string,
) {
  const progress = nodeStageProgress(node, state);
  const skipped = state?.status === "skipped";
  const done =
    !skipped && (role === "ai" ? progress.reviewDone : progress.humanDone);
  const returned = businessFlowReturn(events, state);
  const rejection =
    returned &&
    !returned.resolved &&
    returned.event.actor === (role === "ai" ? "reviewer" : "human");
  const reviewing =
    role === "ai"
      ? ["reviewing", "waiting_review"].includes(state?.status ?? "")
      : ["waiting_human", "waiting_approval"].includes(state?.status ?? "");
  const halted = ["paused", "cancelled", "failed", "interrupted"].includes(
    flowStatus ?? "",
  );
  return {
    done,
    tone: done
      ? "done"
      : halted
        ? "pending"
        : reviewing
          ? "active"
          : rejection
            ? "returned"
            : "pending",
    label: !state
      ? role === "ai"
        ? "独立校核"
        : "由您确认"
      : skipped
        ? "已跳过"
        : done
          ? "已通过"
          : halted
            ? "未通过"
            : reviewing
              ? role === "ai"
                ? "审核中"
                : "待您确认"
              : rejection
                ? "已退回"
                : "待进入",
  };
}

/** One actor hub can review several nodes; each decision remains node-scoped. */
export default function BusinessFlowReviewHub({
  nodes,
  states,
  events,
  role,
  flowStatus,
  onSelect,
  left,
}: {
  nodes: readonly BusinessFlowNode[];
  states: ReadonlyMap<string, BusinessFlowNodeState>;
  events: readonly BusinessFlowEvent[];
  role: "ai" | "human";
  flowStatus?: string;
  onSelect?: (node: BusinessFlowNode) => void;
  left?: number;
}) {
  const ui = useComputeText();
  if (!nodes.length) return null;
  const gates = nodes.map((node) => ({
    node,
    ...reviewGateState(node, states.get(node.id), role, events, flowStatus),
  }));
  const done = gates.filter((gate) => gate.done).length;
  const active = gates.some((gate) => gate.tone === "active");
  const returned = gates.some((gate) => gate.tone === "returned");
  const tone =
    done === nodes.length
      ? "done"
      : active
        ? "active"
        : returned
          ? "returned"
          : "pending";
  const label =
    role === "ai"
      ? ui("结果审核", "Result review")
      : ui("人工审批", "Human approval");
  const status =
    nodes.length === 1
      ? gates[0]!.label
      : states.size
        ? `${done}/${nodes.length} 已通过${active ? " · 待审核" : returned ? " · 有退回" : ""}`
        : `${nodes.length} 个审核点`;
  return (
    <Popover
      trigger="click"
      placement={role === "ai" ? "bottom" : "top"}
      title={`${label} · ${nodes.length} ${ui("个节点", "nodes")}`}
      content={
        <div className="flow-hub-members">
          {gates.map((gate) => (
            <button
              type="button"
              key={gate.node.id}
              aria-label={`${gate.node.title}，${gate.label}`}
              onClick={() => onSelect?.(gate.node)}
            >
              <strong>{gate.node.title}</strong>
              <span className={`tone-${gate.tone}`}>{gate.label}</span>
            </button>
          ))}
        </div>
      }
    >
      <button
        type="button"
        className={`flow-review-gate gate-${role} tone-${tone}`}
        data-flow-gate={role}
        style={left === undefined ? undefined : { left }}
        aria-label={`${label}：${nodes.length === 1 ? `${nodes[0]!.title}，${status}` : `${nodes.length} 个节点，${status}`}`}
      >
        <span className="flow-gate-icon">
          {done === nodes.length ? (
            <CheckOutlined />
          ) : role === "ai" ? (
            <AuditOutlined />
          ) : (
            <UserOutlined />
          )}
        </span>
        <span>
          <strong>{label}</strong>
          <small>{status}</small>
        </span>
      </button>
    </Popover>
  );
}
