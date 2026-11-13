import { Alert, Button, Space } from "antd";
import {
  AuditOutlined,
  MinusOutlined,
  PlusOutlined,
  CompressOutlined,
  PlayCircleOutlined,
  ExportOutlined,
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
  BusinessFlowEvent,
  BusinessFlowNode,
  BusinessFlowNodeState,
} from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";
import {
  businessFlowReturn,
  completedFlowNodes,
  nodeStateLabel,
} from "./businessFlowPresentation";
import BusinessFlowReviewHub, {
  reviewGateState,
} from "./BusinessFlowReviewHub";
import "./business-flows.css";
import "./business-flow-graph.css";

const kinds = {
  agent: { label: "智能体处理", icon: <RobotOutlined /> },
  operator: { label: "算子计算", icon: <ExperimentOutlined /> },
  human: { label: "人工决定", icon: <UserOutlined /> },
  result: { label: "成果交付", icon: <FileDoneOutlined /> },
};

/** Stable dependency layers; parallel nodes never become a false sequence. */
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

type EdgePosition = {
  key: string;
  path: string;
  tone: string;
  kind: "main" | "gate" | "return";
  junction?: { x: number; y: number };
};

export default function BusinessFlowGraph({
  nodes,
  states = [],
  events = [],
  selectedNode,
  currentNode,
  onSelectNode,
  compact = false,
  flowStatus,
}: {
  nodes: readonly BusinessFlowNode[];
  states?: readonly BusinessFlowNodeState[];
  events?: readonly BusinessFlowEvent[];
  selectedNode?: string;
  currentNode?: string;
  flowStatus?: string;
  onSelectNode?: (node: BusinessFlowNode) => void;
  compact?: boolean;
}) {
  const ui = useComputeText();
  const board = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const [availableWidth, setAvailableWidth] = useState(0);
  const [zoom, setZoom] = useState(1);
  const marker = `flow-arrow-${useId().replace(/:/g, "")}`;
  const [geometry, setGeometry] = useState({
    width: 1,
    height: 1,
    edges: [] as EdgePosition[],
    hubs: {} as Partial<Record<"ai" | "human", number>>,
  });
  const startId = `presentation:start:${marker}`,
    endId = `presentation:end:${marker}`;
  const startLabel = ui("开始", "Start"),
    endLabel = ui("输出", "Output");
  const displayNodes = useMemo(() => {
    if (!nodes.length) return [];
    const terminal = (
      id: string,
      title: string,
      dependsOn: string[],
    ): BusinessFlowNode => ({
      id,
      title,
      dependsOn,
      kind: "result",
      description: "",
      instruction: "",
      dataRoles: [],
      review: { ai: false, human: false, maxRevisions: 0 },
    });
    const parents = new Set(nodes.flatMap((node) => node.dependsOn));
    return [
      terminal(startId, startLabel, []),
      ...nodes.map((node) => ({
        ...node,
        dependsOn: node.dependsOn.length ? node.dependsOn : [startId],
      })),
      terminal(
        endId,
        endLabel,
        nodes.filter((node) => !parents.has(node.id)).map((node) => node.id),
      ),
    ];
  }, [nodes, startId, endId, startLabel, endLabel]);
  const layout = useMemo(() => {
    try {
      const levels = businessFlowLevels(nodes);
      const displayed = new Map(displayNodes.map((node) => [node.id, node]));
      return {
        levels: nodes.length
          ? [
              [displayed.get(startId)!],
              ...levels.map((level) =>
                level.map((node) => displayed.get(node.id)!),
              ),
              [displayed.get(endId)!],
            ]
          : [],
        error: "",
      };
    } catch (error) {
      return {
        levels: [],
        error: error instanceof Error ? error.message : "流程无法展示",
      };
    }
  }, [nodes, displayNodes, startId, endId]);
  useLayoutEffect(() => {
    const box = scroller.current;
    if (!box) return;
    const resize = () => setAvailableWidth(Math.max(1, box.clientWidth - 24));
    const observer = new ResizeObserver(resize);
    observer.observe(box);
    resize();
    return () => observer.disconnect();
  }, []);
  const fit = Math.min(
    1,
    availableWidth ? availableWidth / geometry.width : 1,
    (compact ? 360 : 480) / geometry.height,
  );
  const scale = Math.min(2, fit * zoom);
  const stateMap = new Map(states.map((state) => [state.nodeId, state]));
  const identity = nodes
    .map(
      (node) =>
        `${node.id}:${node.dependsOn.join(",")}:${node.review.ai}:${node.review.human}`,
    )
    .join("|");
  const statusIdentity = states
    .map(
      (state) =>
        `${state.nodeId}:${state.status}:${state.human.required}:${state.reviewer.status}:${state.human.status}`,
    )
    .join("|");
  const returnIdentity = events
    .filter((event) =>
      [
        "request_changes",
        "review_rejected",
        "review_accepted",
        "review_passed",
        "approve",
        "human_approved",
      ].includes(event.kind),
    )
    .map((event) => `${event.id}:${event.nodeId}:${event.kind}`)
    .join("|");

  useLayoutEffect(() => {
    const root = board.current;
    if (!root || layout.error) return;
    let frame = 0;
    const draw = () => {
      const bounds = root.getBoundingClientRect();
      const factor = bounds.width / root.offsetWidth || 1;
      const box = {
        left: 0,
        top: 0,
        width: root.offsetWidth,
        height: root.offsetHeight,
      };
      const rect = (element: HTMLElement) => {
        const value = element.getBoundingClientRect();
        return {
          left: (value.left - bounds.left) / factor,
          right: (value.right - bounds.left) / factor,
          top: (value.top - bounds.top) / factor,
          bottom: (value.bottom - bounds.top) / factor,
          width: value.width / factor,
          height: value.height / factor,
        };
      };
      const positions = new Map(
        Array.from(
          root.querySelectorAll<HTMLElement>("[data-flow-anchor]"),
        ).map((element) => [element.dataset.flowAnchor!, rect(element)]),
      );
      const edges: EdgePosition[] = [];
      for (const node of displayNodes) {
        const anchor = positions.get(node.id);
        if (!anchor) continue;
        const y = anchor.top + anchor.height / 2 - box.top;
        for (const parent of node.dependsOn) {
          const from = positions.get(parent);
          if (!from) continue;
          const x1 = from.right - box.left + 4,
            y1 = from.top + from.height / 2 - box.top;
          const x2 = anchor.left - box.left - 8,
            stub = Math.min(x1 + 56, x2 - 12),
            middle = (stub + x2) / 2;
          edges.push({
            key: `${parent}:${node.id}`,
            path: `M${x1},${y1} H${stub} C${middle},${y1} ${middle},${y} ${x2},${y}`,
            kind: "main",
            tone: (
              parent === startId
                ? states.length > 0
                : completedFlowNodes.has(stateMap.get(parent)?.status ?? "")
            )
              ? "is-complete"
              : "",
          });
        }
      }
      const hubs: Partial<Record<"ai" | "human", number>> = {};
      for (const role of ["ai", "human"] as const) {
        const members = nodes.filter((node) =>
          role === "ai"
            ? node.review.ai
            : node.review.human ||
              node.kind === "human" ||
              stateMap.get(node.id)?.human.required,
        );
        const gate = root.querySelector<HTMLElement>(
          `[data-flow-gate="${role}"]`,
        );
        if (!gate || !members.length) continue;
        const gateBox = rect(gate);
        const junctions = members.flatMap((node) => {
          const anchor = positions.get(node.id);
          return anchor
            ? [
                {
                  node,
                  anchor,
                  x: anchor.right - box.left + (role === "ai" ? 18 : 50),
                },
              ]
            : [];
        });
        if (!junctions.length) continue;
        const gx = Math.min(
          box.width - gateBox.width / 2 - 12,
          Math.max(
            gateBox.width / 2 + 12,
            (Math.min(...junctions.map((item) => item.x)) +
              Math.max(...junctions.map((item) => item.x))) /
              2,
          ),
        );
        hubs[role] = gx;
        const gy = (role === "ai" ? gateBox.bottom : gateBox.top) - box.top;
        const bus = role === "ai" ? gy + 24 : gy - 24;
        const xs = [gx, ...junctions.map((item) => item.x)];
        edges.push({
          key: `${role}:bus`,
          kind: "gate",
          tone: `role-${role}`,
          path: `M${gx},${gy} V${bus} M${Math.min(...xs)},${bus} H${Math.max(...xs)}`,
        });
        for (const { node, anchor, x } of junctions) {
          const state = stateMap.get(node.id);
          const y = anchor.top + anchor.height / 2 - box.top;
          const presentation = reviewGateState(
            node,
            state,
            role,
            events,
            flowStatus,
          );
          edges.push({
            key: `${node.id}:${role}`,
            path: `M${x},${bus} V${y}`,
            kind: "gate",
            tone: `role-${role}${presentation.done ? " is-complete" : ""}`,
            junction: { x, y },
          });
          const returned = businessFlowReturn(events, state);
          if (
            returned &&
            !returned.resolved &&
            returned.event.actor === (role === "ai" ? "reviewer" : "human")
          ) {
            const rx = anchor.left + anchor.width / 2 - box.left;
            const ry =
              (role === "ai" ? anchor.top - 5 : anchor.bottom + 5) - box.top;
            const turn = role === "ai" ? bus + 18 : bus - 18;
            const sx = gx + 24,
              direction = rx >= sx ? 1 : -1;
            const radius = Math.min(8, Math.abs(rx - sx) / 2);
            const startDirection = Math.sign(turn - gy),
              endDirection = Math.sign(ry - turn);
            edges.push({
              key: `${node.id}:return`,
              path: `M${sx},${gy} V${turn - startDirection * radius} Q${sx},${turn} ${sx + direction * radius},${turn} H${rx - direction * radius} Q${rx},${turn} ${rx},${turn + endDirection * radius} V${ry}`,
              kind: "return",
              tone: `role-${role} is-returned`,
              junction: { x: rx, y: ry },
            });
          }
        }
      }
      const next = { width: box.width, height: box.height, edges, hubs };
      setGeometry((previous) =>
        JSON.stringify(previous) === JSON.stringify(next) ? previous : next,
      );
    };
    const resize = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(draw);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(root);
    root
      .querySelectorAll("[data-flow-node], [data-flow-gate]")
      .forEach((element) => observer.observe(element));
    draw();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
    // Public token deltas do not trigger graph measurement.
  }, [
    identity,
    statusIdentity,
    displayNodes,
    startId,
    returnIdentity,
    compact,
    layout.error,
    flowStatus,
  ]);

  useLayoutEffect(() => {
    const target = Array.from(
      board.current?.querySelectorAll<HTMLElement>("[data-flow-node]") ?? [],
    ).find((element) => element.dataset.flowNode === currentNode);
    const box = scroller.current;
    if (target && box && zoom > 1)
      box.scrollLeft +=
        target.getBoundingClientRect().left -
        box.getBoundingClientRect().left -
        box.clientWidth / 3;
  }, [currentNode, identity, zoom]);

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
          <i className="flow-legend-dot" />
          {ui("业务节点", "Task nodes")}
        </span>
        {nodes.some((node) => node.review.ai) && (
          <span>
            <AuditOutlined />
            {ui("独立审核", "Independent review")}
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
        {nodes.some((node) => {
          const returned = businessFlowReturn(events, stateMap.get(node.id));
          return returned && !returned.resolved;
        }) && (
          <span className="flow-return-legend">
            <ReloadOutlined />
            {ui("圆角回路为退回路径", "Rounded paths show returns")}
          </span>
        )}
      </div>
      <div className="business-flow-graph-controls">
        <Space size={4}>
          <Button
            size="small"
            type="text"
            icon={<MinusOutlined />}
            aria-label={ui("缩小流程图", "Zoom out")}
            onClick={() => setZoom((value) => Math.max(0.25, value / 1.25))}
          />
          <output aria-label={ui("流程图缩放比例", "Diagram zoom")}>
            {Math.round(scale * 100)}%
          </output>
          <Button
            size="small"
            type="text"
            icon={<PlusOutlined />}
            aria-label={ui("放大流程图", "Zoom in")}
            onClick={() => setZoom((value) => Math.min(8, value * 1.25))}
          />
          <Button
            size="small"
            type="text"
            icon={<CompressOutlined />}
            onClick={() => {
              setZoom(1);
              if (scroller.current) {
                scroller.current.scrollLeft = 0;
                scroller.current.scrollTop = 0;
              }
            }}
          >
            {ui("适应窗口", "Fit to view")}
          </Button>
        </Space>
      </div>
      <div
        className="business-flow-graph-scroller"
        ref={scroller}
        tabIndex={0}
        role="region"
        aria-label={ui("业务流程图，可缩放", "Workflow diagram, zoomable")}
      >
        <div
          className="business-flow-graph-canvas"
          style={{
            width: geometry.width * scale,
            height: geometry.height * scale,
          }}
        >
          <div
            className="business-flow-graph-board"
            ref={board}
            style={{ transform: `scale(${scale})` }}
          >
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
                  <path d="M0,0 L7,3.5 L0,7" fill="context-stroke" />
                </marker>
              </defs>
              {geometry.edges
                .filter((edge) => edge.kind === "main")
                .map((edge) => (
                  <path
                    key={edge.key}
                    data-flow-edge={edge.key}
                    d={edge.path}
                    className={edge.tone}
                    markerEnd={`url(#${marker})`}
                  />
                ))}
              <g className="flow-gate-links">
                {geometry.edges
                  .filter((edge) => edge.kind === "gate")
                  .map((edge) => (
                    <path
                      key={edge.key}
                      data-flow-review={edge.key}
                      d={edge.path}
                      className={edge.tone}
                    />
                  ))}
              </g>
              <g className="flow-return-links">
                {geometry.edges
                  .filter((edge) => edge.kind === "return")
                  .map((edge) => (
                    <path key={edge.key} d={edge.path} className={edge.tone} />
                  ))}
              </g>
              <g className="flow-review-junctions">
                {geometry.edges
                  .filter((edge) => edge.junction)
                  .map((edge) => (
                    <circle
                      key={edge.key}
                      data-flow-review-junction={edge.key}
                      cx={edge.junction!.x}
                      cy={edge.junction!.y}
                      r={3.5}
                      className={edge.tone}
                    />
                  ))}
              </g>
            </svg>
            {(["ai", "human"] as const).map((role) => (
              <BusinessFlowReviewHub
                key={role}
                role={role}
                nodes={nodes.filter((node) =>
                  role === "ai"
                    ? node.review.ai
                    : node.review.human ||
                      node.kind === "human" ||
                      stateMap.get(node.id)?.human.required,
                )}
                states={stateMap}
                events={events}
                flowStatus={flowStatus}
                left={geometry.hubs[role]}
                onSelect={onSelectNode}
              />
            ))}
            {layout.levels.map((level) => (
              <div
                className="business-flow-graph-level"
                key={level.map((node) => node.id).join("|")}
              >
                {level.map((node) => {
                  const terminal =
                    node.id === startId
                      ? "start"
                      : node.id === endId
                        ? "end"
                        : "";
                  const state = stateMap.get(node.id);
                  const kind = kinds[node.kind] ?? {
                    label: "流程节点",
                    icon: <DeploymentUnitOutlined />,
                  };
                  const returned = businessFlowReturn(events, state);
                  const status = state ? nodeStateLabel(state) : kind.label;
                  const activeReturn = returned && !returned.resolved;
                  return (
                    <div
                      className={`flow-node-station${terminal ? " flow-terminal-station" : ""}`}
                      key={node.id}
                    >
                      <button
                        type="button"
                        data-flow-node={node.id}
                        className={`business-flow-node node-${node.kind}${terminal ? ` flow-terminal terminal-${terminal}` : ""}${selectedNode === node.id ? " is-selected" : ""}${currentNode === node.id ? " is-current" : ""}${state ? ` state-${state.status}` : ""}${activeReturn ? " is-returned" : ""}`}
                        aria-pressed={selectedNode === node.id}
                        aria-current={
                          currentNode === node.id ? "step" : undefined
                        }
                        aria-label={
                          terminal ? node.title : `${node.title}，${status}`
                        }
                        aria-disabled={terminal ? true : undefined}
                        onClick={() => !terminal && onSelectNode?.(node)}
                      >
                        <span
                          className="business-flow-node-icon"
                          data-flow-anchor={node.id}
                        >
                          {terminal === "start" ? (
                            <PlayCircleOutlined />
                          ) : terminal === "end" ? (
                            <ExportOutlined />
                          ) : state && completedFlowNodes.has(state.status) ? (
                            <CheckOutlined />
                          ) : (
                            kind.icon
                          )}
                        </span>
                        <span className="business-flow-node-body">
                          <strong>{node.title}</strong>
                          <span className="business-flow-node-eyebrow">
                            {terminal
                              ? terminal === "end"
                                ? ui("成果交付", "Delivery")
                                : ui("流程入口", "Entry")
                              : status}
                            {state && state.attempt > 1
                              ? ` · 第 ${state.attempt} 次处理`
                              : ""}
                          </span>
                          {returned && (
                            <span
                              className={`flow-return-badge${returned.resolved ? " is-resolved" : ""}`}
                            >
                              <ReloadOutlined />
                              {ui(...returned.label)}
                            </span>
                          )}
                        </span>
                      </button>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
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
