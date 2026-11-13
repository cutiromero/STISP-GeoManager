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
  const writing = live && activity?.thinkingEnabled === false;
  const text = writing ? "" : activity?.thinkingText || initialThinking || "";
  const requestKey =
    activity?.requestId || `${activity?.stage}:${activity?.attempt}`;
  const stateLabel =
    activity?.status === "requesting"
      ? "正在准备分析"
      : activity?.status === "responding"
        ? "正在整理结果"
        : activity?.status === "validating"
          ? "正在核对分析结果"
          : activity?.status === "complete"
            ? "本轮分析完成"
            : activity?.status === "failed"
              ? "分析未完成，请查看问题详情"
              : "正在整理依据";
  if (!text && !live) return null;
  return (
    <section
      className={`logic-thinking-preview${live ? " is-live" : ""}`}
      aria-label="模型思考预览"
    >
      <div className="logic-thinking-heading">
        <span>
          <BulbOutlined />
          {writing ? "正在整理结果" : live ? stateLabel : "最近一次分析"}
        </span>
        <Button type="link" size="small" onClick={onExpand}>
          查看分析过程 <RightOutlined />
        </Button>
      </div>
      {activity && (
        <small className="logic-muted">
          {activity.actor === "reviewer" ? "独立审核" : "任务执行"}
          {` · ${activity.stage} · 第 ${activity.attempt} 轮 · ${stateLabel}`}
        </small>
      )}
      {writing ? (
        <p className="logic-muted">
          正在结合实际计算成果生成报告
          {activity?.outputChars ? `（已接收 ${activity.outputChars} 字）` : ""}
          …
        </p>
      ) : text ? (
        <ThinkingStream
          key={`${workflow.id}:${requestKey}`}
          text={text.slice(-1200)}
          working={live && activity?.status === "thinking"}
        />
      ) : (
        <p className="logic-muted">正在分析…</p>
      )}
      {text.length > 1200 && (
        <small className="logic-muted">
          预览本轮最近 1200 字，展开查看已保存记录；后续调用按工具结果继续。
        </small>
      )}
    </section>
  );
}
