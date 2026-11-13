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
      ? "本轮请求已发出，等待模型响应"
      : activity?.status === "responding"
        ? "正在输出行动与结果"
        : activity?.status === "validating"
          ? "正在核验本轮响应"
          : activity?.status === "complete"
            ? "本轮响应已完成"
            : activity?.status === "failed"
              ? "本轮请求未通过，查看记录中的诊断"
              : "模型正在整理依据";
  if (!text && !live) return null;
  return (
    <section
      className={`logic-thinking-preview${live ? " is-live" : ""}`}
      aria-label="模型思考预览"
    >
      <div className="logic-thinking-heading">
        <span>
          <BulbOutlined />
          {writing
            ? "模型正在组织结果"
            : live
              ? stateLabel
              : "最近一次模型调用"}
        </span>
        <Button type="link" size="small" onClick={onExpand}>
          查看实际思考 <RightOutlined />
        </Button>
      </div>
      {activity && (
        <small className="logic-muted">
          {activity.actor === "reviewer" ? "独立审核" : "主执行智能体"}
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
        <p className="logic-muted">等待模型返回实际内容…</p>
      )}
      {text.length > 1200 && (
        <small className="logic-muted">
          预览本轮最近 1200 字，展开查看已保存记录；后续调用按工具结果继续。
        </small>
      )}
    </section>
  );
}
