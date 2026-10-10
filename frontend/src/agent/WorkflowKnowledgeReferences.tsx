import { Collapse } from "antd";
import type { AgentWorkflow } from "../api/generated/types.gen";

function text(value: unknown) {
  return typeof value === "string" ? value : "";
}

function sourceLink(value: unknown) {
  try {
    const url = new URL(text(value));
    return ["http:", "https:"].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}

export default function WorkflowKnowledgeReferences({
  items,
}: {
  items: AgentWorkflow["evidence"];
}) {
  return (
    <Collapse
      className="agent-workflow-knowledge"
      ghost
      size="small"
      items={items.map((entry) => {
        const title = text(entry.title) || "知识依据";
        const conditions = Array.isArray(entry.conditions)
          ? entry.conditions.filter(
              (value): value is string => typeof value === "string",
            )
          : [];
        const sources = Array.isArray(entry.sources)
          ? entry.sources.filter(
              (value): value is Record<string, unknown> =>
                value !== null &&
                typeof value === "object" &&
                !Array.isArray(value),
            )
          : [];
        return {
          key: String(entry.id ?? title),
          label: `${title}${entry.revision !== undefined ? ` · 版本 ${String(entry.revision)}` : ""}`,
          children: (
            <article aria-label={`${title}原文与出处`}>
              {text(entry.statement) && <p>{text(entry.statement)}</p>}
              {!!conditions.length && (
                <div>
                  <strong>适用条件</strong>
                  <ul>
                    {conditions.map((condition) => (
                      <li key={condition}>{condition}</li>
                    ))}
                  </ul>
                </div>
              )}
              {!!sources.length && (
                <div>
                  <strong>原文出处</strong>
                  <ul>
                    {sources.map((source) => {
                      const href = sourceLink(source.url);
                      const sourceTitle = text(source.title) || "查看来源";
                      return (
                        <li key={JSON.stringify(source)}>
                          {href ? (
                            <a
                              href={href}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {sourceTitle}
                            </a>
                          ) : (
                            <span>{sourceTitle}</span>
                          )}
                          {text(source.locator) && (
                            <p className="agent-evidence-source">
                              原文位置：{text(source.locator)}
                            </p>
                          )}
                          {text(source.excerpt) && (
                            <blockquote>{text(source.excerpt)}</blockquote>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </article>
          ),
        };
      })}
    />
  );
}
