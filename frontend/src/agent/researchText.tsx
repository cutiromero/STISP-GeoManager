import type { ReactNode } from "react";

/** A short card title from a long request: its first sentence, trimmed. */
export function briefTitle(goal: string, limit = 36): string {
  const first =
    goal
      .trim()
      .split(/[。！？；\n]/)[0]
      ?.trim() ?? "";
  const text = (first || goal.trim()).replace(/^请(?:你|帮我)?/, "");
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

const NUMBER = /(\d[\d,.]*\s*(?:项|个|处|条|组|类|%|km²|公顷|平方米)?)/;

/** Bold the counts and measures that carry a conclusion. */
export function emphasizeNumbers(text: string): ReactNode[] {
  return text
    .split(NUMBER)
    .map((part, index) =>
      index % 2 ? <strong key={`${index}-${part}`}>{part}</strong> : part,
    );
}
