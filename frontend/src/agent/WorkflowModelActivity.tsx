import { Collapse } from "antd";
import type { AgentWorkflow } from "../api/generated/types.gen";
import ThinkingStream from "./ThinkingStream";
import LiveActivity from "./LiveActivity";

const labels = {
  requesting: "模型请求已发出，等待响应",
  thinking: "模型正在思考",
  responding: "正在接收模型响应",
  validating: "正在校验模型响应",
  complete: "本阶段模型分析已完成",
  failed: "本阶段模型请求失败",
};

export default function WorkflowModelActivity({
  workflow,
}: {
  workflow: AgentWorkflow;
}) {
  const activity = workflow.modelActivity;
  if (!activity) return null;
  const computing =
    workflow.status === "waiting_compute" ||
    workflow.plan.phase === "waiting_compute";
  const stopped = ["failed", "cancelled", "interrupted"].includes(
    workflow.status,
  );
  const waiting =
    workflow.pauseRequested ||
    ["paused", "waiting_approval"].includes(workflow.status);
  const working =
    workflow.status === "running" &&
    !computing &&
    !waiting &&
    !["complete", "failed"].includes(activity.status);
  const label = stopped
    ? `${workflow.status === "failed" ? "任务失败" : workflow.status === "cancelled" ? "任务已停止" : "任务已中断"}，保留已接收的模型活动`
    : workflow.status === "succeeded"
      ? "模型分析已完成"
      : waiting
        ? workflow.status === "waiting_approval"
          ? "等待您确认，保留已接收的模型活动"
          : "模型活动已暂停，保留已接收内容"
        : computing
          ? "已接收的模型活动；当前正在进行算子计算"
          : labels[activity.status];
  return (
    <section className="agent-model-activity" aria-label="工作流模型活动">
      <LiveActivity
        title={activity.stage}
        activity={{
          state: stopped
            ? "stopped"
            : workflow.status === "succeeded"
              ? "complete"
              : waiting || computing
                ? "waiting"
                : activity.status === "failed"
                  ? "stopped"
                  : working
                    ? "working"
                    : "complete",
          label,
          detail: `第 ${activity.attempt} 次请求${activity.modelName ? ` · ${activity.modelName}` : ""} · 已接收响应正文 ${activity.outputChars} 字符`,
        }}
      />
      <Collapse
        key={workflow.id}
        size="small"
        className="agent-thinking-panel"
        items={[
          {
            key: "model-thinking",
            label: `查看模型实际思考${activity.thinkingChars !== undefined ? ` / ${activity.thinkingChars} 字符` : ""}`,
            children: (
              <>
                {activity.truncated && (
                  <p className="agent-muted">
                    仅显示最近 12000 个思考字符，较早部分已省略。
                  </p>
                )}
                {activity.thinkingText ? (
                  <ThinkingStream
                    text={activity.thinkingText}
                    working={working && activity.status === "thinking"}
                  />
                ) : (
                  <p className="agent-muted">
                    {working
                      ? "尚未收到可展示的模型思考内容。"
                      : "本次模型未返回可展示的思考内容。"}
                  </p>
                )}
              </>
            ),
          },
        ]}
      />
    </section>
  );
}
