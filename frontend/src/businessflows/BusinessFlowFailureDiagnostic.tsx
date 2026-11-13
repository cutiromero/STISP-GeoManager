import type { BusinessFlowFailureDiagnostic as Diagnostic } from "../api/generated/types.gen";

export default function BusinessFlowFailureDiagnostic({ value }: { value?: Diagnostic }) {
  if (!value) return null;
  return (
    <section aria-label="执行错误诊断">
      <h4>错误位置</h4>
      <p>{value.location} · {value.code}</p>
      <h4>已确认的错误</h4>
      <ul>{value.facts.map((fact) => <li key={fact}>{fact}</li>)}</ul>
      <h4>实际尝试记录</h4>
      {value.attempts.length ? (
        <ul>{value.attempts.map((attempt) => <li key={attempt}>{attempt}</li>)}</ul>
      ) : <p>没有自动补救记录。</p>}
      <h4>{value.analysisStatus === "completed" ? "主执行智能体的原因分析" : "AI诊断未完成"}</h4>
      <p>{value.analysis}</p>
      <h4>需要您处理</h4>
      <ul>{value.suggestions.map((suggestion) => <li key={suggestion}>{suggestion}</li>)}</ul>
      <p>{value.resumeAt}</p>
      <details><summary>定位记录编号</summary><ul>{value.references.map((ref) => <li key={ref}>{ref}</li>)}</ul></details>
    </section>
  );
}
