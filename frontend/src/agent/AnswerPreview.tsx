import type { AgentRun } from "../api/generated/types.gen";
import { useDeferredValue } from "react";
import SafeMarkdown from "./SafeMarkdown";
import { MAX_ANSWER_PREVIEW } from "../api/watchAgentRun";

export default function AnswerPreview({ run }: { run: AgentRun }) {
  const text = useDeferredValue(run.answerPreview ?? "");
  const current = run.answerPreview ?? "";
  // Never defer the first text or show an old preview after a protocol reset.
  const visible = text && current.startsWith(text) ? text : current;
  if (run.answer || !run.answerPreview) return null;
  const generating = ["queued", "running"].includes(run.status);
  const stopped = ["failed", "cancelled", "interrupted"].includes(run.status);
  return (
    <section className="agent-answer-preview" aria-label="答复增量预览">
      <p className="agent-muted" role="status">
        {generating
          ? "正在生成 · 内容将在完成后核验"
          : stopped
            ? "本轮已中断或停止；以下为尚未最终校验的部分答复"
            : "以下为尚未最终校验的部分答复"}
      </p>
      <div className="agent-answer-preview-text">
        <SafeMarkdown text={visible} />
      </div>
      {run.answerPreview.length >= MAX_ANSWER_PREVIEW && (
        <p className="agent-muted">
          实时预览已达到展示上限，最终答复仍将完整显示。
        </p>
      )}
    </section>
  );
}
