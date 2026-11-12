import {
  ApartmentOutlined,
  AuditOutlined,
  CheckOutlined,
  DownOutlined,
  ExpandOutlined,
  ExperimentOutlined,
  FileDoneOutlined,
  ReloadOutlined,
  RobotOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Button, Drawer, Progress } from "antd";
import { useId, useState } from "react";
import type { BusinessFlowRun } from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";
import BusinessFlowGraph, { businessFlowLevels } from "./BusinessFlowGraph";
import BusinessFlowNodeTrace from "./BusinessFlowNodeTrace";
import {
  businessFlowProgress,
  businessFlowReturn,
  completedFlowNodes,
  flowStateLabels,
  nodeStageProgress,
  nodeStateLabel,
} from "./businessFlowPresentation";
import "./business-flow-monitor.css";

const icons = {
  agent: <RobotOutlined />,
  operator: <ExperimentOutlined />,
  human: <UserOutlined />,
  result: <FileDoneOutlined />,
};

export default function BusinessFlowMonitor({
  flow,
  onLocate,
  accessBlocked = false,
}: {
  flow: BusinessFlowRun;
  accessBlocked?: boolean;
  onLocate: (nodeId: string) => void;
}) {
  const ui = useComputeText();
  const [open, setOpen] = useState(false);
  const [diagram, setDiagram] = useState(false);
  const [mainTrace, setMainTrace] = useState(false);
  const [selection, setSelection] = useState<{
    flowId: string;
    nodeId: string;
  }>();
  const contentId = `flow-monitor-${useId().replace(/:/g, "")}`;
  const nodes = flow.definitionSnapshot.nodes;
  const current = nodes.find((node) => node.id === flow.currentNode);
  const progress = businessFlowProgress(flow);
  const stateMap = new Map(flow.nodes.map((state) => [state.nodeId, state]));
  const selected = nodes.find(
    (node) =>
      node.id ===
      (selection?.flowId === flow.id ? selection.nodeId : flow.currentNode),
  );
  const selectedState = selected && stateMap.get(selected.id);
  const returned = businessFlowReturn(flow.events, selectedState);
  const halted = ["paused", "cancelled", "failed", "interrupted"].includes(
    flow.status,
  );
  const unavailable =
    accessBlocked ||
    flow.nodes.some(
      (node) =>
        node.executor.status === "unavailable" ||
        node.reviewer.status === "unavailable",
    );
  let levels: ReturnType<typeof businessFlowLevels>;
  try {
    levels = businessFlowLevels(nodes);
  } catch {
    levels = [];
  }
  const stateText = flowStateLabels[flow.status] ?? flow.status;
  return (
    <aside
      className={`business-flow-monitor${open ? " is-open" : ""}`}
      aria-label={ui("业务流实时进度", "Live workflow progress")}
    >
      <header className="flow-monitor-heading">
        <span className="flow-monitor-symbol">
          <ApartmentOutlined />
        </span>
        <div>
          <span>{ui("流程进度", "WORKFLOW")}</span>
          <strong>{flow.name}</strong>
        </div>
        <Button
          className="flow-monitor-diagram-toggle"
          type="text"
          icon={<ExpandOutlined />}
          aria-label={ui("展开流程全图", "Open full diagram")}
          onClick={() => setDiagram(true)}
        />
        <Button
          className="flow-monitor-toggle"
          type="text"
          icon={<DownOutlined rotate={open ? 180 : 0} />}
          aria-label={ui(
            open ? "收起流程进度" : "展开流程进度",
            open ? "Collapse progress" : "Expand progress",
          )}
          aria-expanded={open}
          aria-controls={contentId}
          onClick={() => setOpen((value) => !value)}
        />
      </header>
      {flow.mainAgent && !unavailable && (
        <p className="flow-monitor-live">
          <RobotOutlined />{" "}
          {ui("主执行智能体持续处理", "Continuous main executor")}
          <Button type="link" size="small" onClick={() => setMainTrace(true)}>
            {ui("查看主执行记录", "View main executor trace")}
          </Button>
        </p>
      )}
      <Drawer
        title={ui("主执行智能体 · 完整任务循环", "Main executor · Task loop")}
        open={mainTrace}
        onClose={() => setMainTrace(false)}
        size={720}
        destroyOnHidden
      >
        {mainTrace && !unavailable && (
          <BusinessFlowNodeTrace
            flowId={flow.id}
            nodeId="_main"
            state={stateMap.get(flow.currentNode)}
            progressKey={JSON.stringify([
              flow.status,
              flow.currentNode,
              flow.nodes.map((node) => [
                node.nodeId,
                node.status,
                node.attempt,
                node.toolProgress?.steps,
              ]),
            ])}
          />
        )}
      </Drawer>
      <p
        className={`flow-monitor-live${halted ? " is-halted" : ""}`}
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        <i />
        {stateText}
        {current &&
        !["succeeded", "cancelled", "interrupted"].includes(flow.status)
          ? ` · ${current.title}`
          : ""}
      </p>
      <div className="flow-monitor-content" id={contentId}>
        <div className="flow-monitor-progress">
          <span>{ui("节点完成", "Nodes completed")}</span>
          <strong>
            {progress.completedNodes}
            <small> / {nodes.length}</small>
          </strong>
        </div>
        <Progress
          percent={progress.percent}
          showInfo={false}
          size="small"
          strokeColor="#5c8f85"
          aria-label={ui("流程总进度", "Overall flow progress")}
        />
        <ol className="flow-monitor-nodes">
          {levels.map((level) => (
            <li
              className={`flow-monitor-level${level.length > 1 ? " is-parallel" : ""}`}
              key={level.map((node) => node.id).join("|")}
            >
              {level.length > 1 && (
                <small className="flow-monitor-parallel-label">
                  {ui("并行节点", "Parallel nodes")}
                </small>
              )}
              {level.map((node) => {
                const state = stateMap.get(node.id);
                const done = completedFlowNodes.has(state?.status ?? "");
                const active = flow.currentNode === node.id && !done;
                const revision = businessFlowReturn(flow.events, state);
                const stages = nodeStageProgress(node, state);
                const skipped = state?.status === "skipped";
                const status =
                  active && halted ? stateText : nodeStateLabel(state);
                return (
                  <button
                    type="button"
                    key={node.id}
                    className={`flow-monitor-node${done ? " is-done" : ""}${active ? " is-active" : ""}${selected?.id === node.id ? " is-selected" : ""}${revision && !revision.resolved ? " is-returned" : ""}`}
                    aria-label={`${node.title}，${status}`}
                    aria-pressed={selected?.id === node.id}
                    aria-current={active ? "step" : undefined}
                    onClick={() =>
                      setSelection({ flowId: flow.id, nodeId: node.id })
                    }
                  >
                    <span className="flow-monitor-node-icon">
                      {done ? <CheckOutlined /> : icons[node.kind]}
                    </span>
                    <span className="flow-monitor-node-body">
                      <strong>{node.title}</strong>
                      <small>
                        {status}
                        {state && state.attempt > 1
                          ? ` · 第 ${state.attempt} 次`
                          : ""}
                      </small>
                      {(node.review.ai ||
                        node.review.human ||
                        node.kind === "human" ||
                        state?.human.required) && (
                        <span className="flow-monitor-gates">
                          {node.review.ai && (
                            <span
                              className={
                                stages.reviewDone && !skipped ? "is-done" : ""
                              }
                            >
                              <AuditOutlined />
                              {ui("AI 审核", "AI review")}
                              {stages.reviewDone && !skipped && (
                                <CheckOutlined />
                              )}
                            </span>
                          )}
                          {(node.review.human ||
                            node.kind === "human" ||
                            state?.human.required) && (
                            <span
                              className={
                                stages.humanDone && !skipped
                                  ? "is-done"
                                  : "human-gate"
                              }
                            >
                              <UserOutlined />
                              {ui("人工审批", "Approval")}
                              {stages.humanDone && !skipped && (
                                <CheckOutlined />
                              )}
                            </span>
                          )}
                        </span>
                      )}
                      {revision && (
                        <span
                          className={`flow-monitor-return${revision.resolved ? " is-resolved" : ""}`}
                        >
                          <ReloadOutlined />
                          {ui(...revision.label)}
                        </span>
                      )}
                    </span>
                  </button>
                );
              })}
            </li>
          ))}
        </ol>
        {selected && (
          <section
            className="flow-monitor-detail"
            aria-label={ui("节点状态详情", "Node status details")}
          >
            <span>{ui("节点详情", "NODE DETAILS")}</span>
            <strong>{selected.title}</strong>
            <p>{selected.description}</p>
            {!unavailable && !diagram && selection?.flowId === flow.id && (
              <BusinessFlowNodeTrace
                key={`${flow.id}:${selected.id}`}
                flowId={flow.id}
                nodeId={selected.id}
                state={selectedState}
              />
            )}
            {!unavailable && returned && (
              <div
                className={`flow-monitor-return-detail${returned.resolved ? " is-resolved" : ""}`}
              >
                <strong>
                  <ReloadOutlined />
                  {ui(
                    returned.resolved
                      ? `返工记录 · ${returned.label[0]}`
                      : halted
                        ? `返工${stateText}`
                        : "返工路径",
                    returned.resolved
                      ? returned.label[1]
                      : halted
                        ? `Revision ${stateText}`
                        : "Return path",
                  )}
                </strong>
                <p>
                  {returned.event.actor === "human"
                    ? ui("人工审批", "Human approval")
                    : ui("AI 审核", "AI review")}{" "}
                  → {selected.title} → {ui("再次审核", "Review again")}
                </p>
                <blockquote>{returned.event.message}</blockquote>
              </div>
            )}
            {!unavailable && (
              <Button
                size="small"
                type="link"
                onClick={() => onLocate(selected.id)}
              >
                {ui("查看节点内容", "View node content")}
              </Button>
            )}
          </section>
        )}
      </div>
      <Drawer
        open={diagram}
        onClose={() => setDiagram(false)}
        title={flow.name}
        size={900}
        destroyOnHidden
      >
        <BusinessFlowGraph
          nodes={nodes}
          states={flow.nodes}
          events={unavailable ? [] : flow.events}
          currentNode={flow.currentNode}
          flowStatus={flow.status}
          selectedNode={selected?.id}
          onSelectNode={(node) =>
            setSelection({ flowId: flow.id, nodeId: node.id })
          }
        />
        {selected && (
          <div className="flow-monitor-diagram-detail">
            <strong>{selected.title}</strong>
            <p>{selected.description}</p>
            {!unavailable && selection?.flowId === flow.id && (
              <BusinessFlowNodeTrace
                key={`${flow.id}:${selected.id}`}
                flowId={flow.id}
                nodeId={selected.id}
                state={selectedState}
              />
            )}
          </div>
        )}
      </Drawer>
    </aside>
  );
}
