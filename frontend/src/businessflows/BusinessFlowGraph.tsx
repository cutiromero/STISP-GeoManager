import { Alert } from "antd";
import {
  AuditOutlined,
  CheckOutlined,
  DeploymentUnitOutlined,
  ExperimentOutlined,
  FileDoneOutlined,
  ReloadOutlined,
  RobotOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import type {
  BusinessFlowNode,
  BusinessFlowNodeState,
} from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";
import "./business-flows.css";

const kinds = {
  agent: { label: "智能体处理", icon: <RobotOutlined /> },
  operator: { label: "算子计算", icon: <ExperimentOutlined /> },
  human: { label: "人工决定", icon: <UserOutlined /> },
  result: { label: "成果交付", icon: <FileDoneOutlined /> },
};
const stateLabels: Record<string, string> = {
  pending: "尚未开始",
  queued: "等待执行",
  running: "执行中",
  executing: "执行中",
  reviewing: "独立审核中",
  waiting_review: "独立审核中",
  waiting_human: "等待您决定",
  waiting_approval: "等待您决定",
  repairing: "返修中",
  revising: "返修中",
  succeeded: "已完成",
  completed: "已完成",
  approved: "已通过",
  failed: "未完成",
  rejected: "需要返修",
  skipped: "已跳过",
  cancelled: "已停止",
  paused: "已暂停",
};

/** Stable dependency layers; the graph never invents an execution sequence. */
export function businessFlowLevels(nodes: readonly BusinessFlowNode[]) {
  const identities = new Set(nodes.map((node) => node.id));
  if (identities.size !== nodes.length || nodes.length > 64)
    throw new Error("流程节点标识重复或超出上限");
  for (const node of nodes)
    if (node.dependsOn.some((id) => !identities.has(id) || id === node.id))
      throw new Error("流程包含无效的节点依赖");
  const visited = new Set<string>();
  const levels: BusinessFlowNode[][] = [];
  while (visited.size < nodes.length) {
    const level = nodes.filter(
      (node) =>
        !visited.has(node.id) && node.dependsOn.every((id) => visited.has(id)),
    );
    if (!level.length) throw new Error("流程依赖形成循环，无法展示执行顺序");
    levels.push(level);
    level.forEach((node) => visited.add(node.id));
  }
  return levels;
}

type EdgePosition = { key: string; path: string; complete: boolean };
export default function BusinessFlowGraph({
  nodes,
  states = [],
  selectedNode,
  onSelectNode,
  compact = false,
}: {
  nodes: readonly BusinessFlowNode[];
  states?: readonly BusinessFlowNodeState[];
  selectedNode?: string;
  onSelectNode?: (node: BusinessFlowNode) => void;
  compact?: boolean;
}) {
  const ui = useComputeText();
  const board = useRef<HTMLDivElement>(null);
  const marker = `flow-arrow-${useId().replace(/:/g, "")}`;
  const [geometry, setGeometry] = useState<{
    width: number;
    height: number;
    edges: EdgePosition[];
  }>({ width: 1, height: 1, edges: [] });
  const layout = useMemo(() => {
    try {
      return { levels: businessFlowLevels(nodes), error: "" };
    } catch (error) {
      return {
        levels: [],
        error: error instanceof Error ? error.message : "流程无法展示",
      };
    }
  }, [nodes]);
  const stateMap = new Map(states.map((state) => [state.nodeId, state]));
  const identity = nodes
    .map((node) => `${node.id}:${node.dependsOn.join(",")}`)
    .join("|");
  const completion = states
    .filter((state) =>
      ["succeeded", "completed", "approved"].includes(state.status),
    )
    .map((state) => state.nodeId)
    .join("|");
  useLayoutEffect(() => {
    const root = board.current;
    if (!root || layout.error) return;
    let frame = 0;
    const draw = () => {
      const box = root.getBoundingClientRect();
      const positions = new Map(
        Array.from(root.querySelectorAll<HTMLElement>("[data-flow-node]")).map(
          (element) => [
            element.dataset.flowNode!,
            element.getBoundingClientRect(),
          ],
        ),
      );
      const complete = new Set(completion.split("|"));
      const edges = nodes.flatMap((node) =>
        node.dependsOn.flatMap((parent) => {
          const from = positions.get(parent),
            to = positions.get(node.id);
          if (!from || !to) return [];
          const x1 = from.left + from.width / 2 - box.left,
            y1 = from.bottom - box.top;
          const x2 = to.left + to.width / 2 - box.left,
            y2 = to.top - box.top - 5;
          const middle = (y1 + y2) / 2;
          return [
            {
              key: `${parent}:${node.id}`,
              path: `M${x1},${y1} C${x1},${middle} ${x2},${middle} ${x2},${y2}`,
              complete: complete.has(parent),
            },
          ];
        }),
      );
      setGeometry((previous) => {
        const next = { width: box.width, height: box.height, edges };
        return JSON.stringify(previous) === JSON.stringify(next)
          ? previous
          : next;
      });
    };
    const resize = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(draw);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(root);
    root
      .querySelectorAll("[data-flow-node]")
      .forEach((element) => observer.observe(element));
    draw();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
    // Measurements change with dependency identity, size or completion, not live message tokens.
  }, [identity, completion, compact, layout.error]);
  if (layout.error)
    return (
      <Alert
        type="error"
        showIcon
        title={ui("流程图暂不可用", "Flow diagram unavailable")}
        description={layout.error}
      />
    );
  return (
    <div
      className={`business-flow-graph${compact ? " is-compact" : ""}${states.length ? "" : " is-blueprint"}`}
    >
      <div
        className="business-flow-graph-legend"
        aria-label={ui("流程图图例", "Flow legend")}
      >
        <span>
          <RobotOutlined />
          {ui("执行", "Execute")}
        </span>
        {nodes.some((node) => node.review.ai) && (
          <span>
            <AuditOutlined />
            {ui("独立 AI 审核", "Independent AI review")}
          </span>
        )}
        {nodes.some(
          (node) =>
            node.review.human ||
            node.kind === "human" ||
            stateMap.get(node.id)?.human.required,
        ) && (
          <span className="human-legend">
            <UserOutlined />
            {ui("人工决定", "Human decision")}
          </span>
        )}
        {nodes.some(
          (node) =>
            (node.review.ai || node.review.human || node.kind === "human") &&
            node.review.maxRevisions > 0,
        ) && (
          <span>
            <ReloadOutlined />
            {ui("限次返修", "Bounded revision")}
          </span>
        )}
      </div>
      <div className="business-flow-graph-board" ref={board}>
        <svg
          className="business-flow-graph-links"
          width="100%"
          height="100%"
          viewBox={`0 0 ${geometry.width} ${geometry.height}`}
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <defs>
            <marker
              id={marker}
              markerWidth="7"
              markerHeight="7"
              refX="6"
              refY="3.5"
              orient="auto"
              markerUnits="userSpaceOnUse"
            >
              <path d="M0,0 L7,3.5 L0,7" />
            </marker>
          </defs>
          {geometry.edges.map((edge) => (
            <path
              key={edge.key}
              d={edge.path}
              className={edge.complete ? "is-complete" : ""}
              markerEnd={`url(#${marker})`}
            />
          ))}
        </svg>
        {layout.levels.map((level) => (
          <div
            className="business-flow-graph-level"
            key={level.map((node) => node.id).join("|")}
          >
            {level.map((node) => {
              const state = stateMap.get(node.id);
              const label = kinds[node.kind] ?? {
                label: "流程节点",
                icon: <DeploymentUnitOutlined />,
              };
              const status = state
                ? (stateLabels[state.status] ?? state.status)
                : label.label;
              return (
                <button
                  type="button"
                  key={node.id}
                  data-flow-node={node.id}
                  className={`business-flow-node node-${node.kind}${selectedNode === node.id ? " is-selected" : ""}${state ? ` state-${state.status}` : ""}`}
                  aria-pressed={selectedNode === node.id}
                  aria-label={`${node.title}，${status}`}
                  onClick={() => onSelectNode?.(node)}
                >
                  <span className="business-flow-node-icon">
                    {state &&
                    ["succeeded", "completed", "approved"].includes(
                      state.status,
                    ) ? (
                      <CheckOutlined />
                    ) : (
                      label.icon
                    )}
                  </span>
                  <span className="business-flow-node-body">
                    <span className="business-flow-node-eyebrow">
                      {status}
                      {state && state.attempt > 1
                        ? ` · 第 ${state.attempt} 次处理`
                        : ""}
                    </span>
                    <strong>{node.title}</strong>
                    {!compact && (
                      <span className="business-flow-node-description">
                        {node.description}
                      </span>
                    )}
                    {(node.review.ai ||
                      node.review.human ||
                      node.kind === "human") && (
                      <span className="business-flow-node-guards">
                        {node.review.ai && (
                          <span>
                            <AuditOutlined />
                            {ui("独立审核", "AI review")}
                          </span>
                        )}
                        {(node.review.human ||
                          node.kind === "human" ||
                          stateMap.get(node.id)?.human.required) && (
                          <span className="human-guard">
                            <UserOutlined />
                            {ui("您决定", "Your decision")}
                          </span>
                        )}
                        {(node.review.ai ||
                          node.review.human ||
                          node.kind === "human") &&
                          node.review.maxRevisions > 0 && (
                            <span className="revision-guard">
                              <ReloadOutlined />
                              {ui(
                                `最多返修 ${node.review.maxRevisions} 次`,
                                `Up to ${node.review.maxRevisions} revisions`,
                              )}
                            </span>
                          )}
                      </span>
                    )}
                  </span>
                  {state?.human?.required &&
                    state.human.status === "pending" && (
                      <span
                        className="business-flow-node-attention"
                        aria-label={ui(
                          "需要人工决定",
                          "Human decision required",
                        )}
                      />
                    )}
                </button>
              );
            })}
          </div>
        ))}
      </div>
      {!nodes.length && (
        <p className="business-flow-empty">
          {ui(
            "此版本尚未登记流程节点。",
            "No nodes are registered for this version.",
          )}
        </p>
      )}
    </div>
  );
}
