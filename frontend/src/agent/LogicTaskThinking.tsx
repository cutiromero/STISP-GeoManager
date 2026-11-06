import { BulbOutlined, RightOutlined } from "@ant-design/icons";
import { Button } from "antd";
import type { AgentWorkflow } from "../api/generated/types.gen";
import ThinkingStream from "./ThinkingStream";
import { logicRunning } from "./logicTaskPresentation";

export function liveLogicThinking(workflow: AgentWorkflow) {
  return (
    logicRunning(workflow) &&
    workflow.status === "running" &&
    workflow.plan.phase !== "waiting_compute" &&
    Boolean(
      workflow.modelActivity &&
      ["requesting", "thinking", "responding", "validating"].includes(
        workflow.modelActivity.status,
      ),
    )
  );
}

export default function LogicTaskThinking({
  workflow,
  initialThinking,
  onExpand,
}: {
  workflow: AgentWorkflow;
  initialThinking?: string;
  onExpand: () => void;
}) {
  const activity = workflow.modelActivity;
  const live = liveLogicThinking(workflow);
  const text = activity?.thinkingText || initialThinking || "";
  if (!text && !live) return null;
  return (
    <section
      className={`logic-thinking-preview${live ? " is-live" : ""}`}
      aria-label="模型思考预览"
    >
      <div className="logic-thinking-heading">
        <span>
          <BulbOutlined />
          {live ? "模型正在整理依据" : "最近一次模型思考"}
        </span>
        <Button type="link" size="small" onClick={onExpand}>
          查看实际思考 <RightOutlined />
        </Button>
      </div>
      {live &&
        (text ? (
          <ThinkingStream
            text={text.slice(-1200)}
            working={activity?.status === "thinking"}
          />
        ) : (
          <p className="logic-muted">等待模型返回实际内容…</p>
        ))}
      {live && text.length > 1200 && (
        <small className="logic-muted">
          预览最近片段，展开可查看已保存的完整内容。
        </small>
      )}
    </section>
  );
}
