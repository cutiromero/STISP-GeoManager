import type { AgentRun } from "../api/generated/types.gen";

export default function AnswerPreview({ run }: { run: AgentRun }) {
  if (run.answer || !run.answerPreview) return null;
  const generating = ["queued", "running"].includes(run.status);
  const stopped = ["failed", "cancelled", "interrupted"].includes(run.status);
  return (
    <section className="agent-answer-preview" aria-label="答复增量预览">
      <p className="agent-muted" role="status">
        {generating
          ? "正在生成答复，尚未最终校验"
          : stopped
            ? "本轮已中断或停止；以下为尚未最终校验的部分答复"
            : "以下为尚未最终校验的部分答复"}
      </p>
      <div className="agent-answer-preview-text">{run.answerPreview}</div>
      {Array.from(run.answerPreview).length >= 24000 && (
        <p className="agent-muted">
          预览已达到 24000 字符上限，最终答复仍将完整显示。
        </p>
      )}
    </section>
  );
}
