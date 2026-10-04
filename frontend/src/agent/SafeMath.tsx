import { useLayoutEffect, useRef } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";

/** KaTeX builds its own DOM; source text is never treated as HTML. */
export default function SafeMath({
  expression,
  display = false,
}: {
  expression: string;
  display?: boolean;
}) {
  const target = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const element = target.current;
    if (!element) return;
    if (expression.length > 4000) {
      element.textContent = expression;
      return;
    }
    try {
      katex.render(expression, element, {
        displayMode: display,
        trust: false,
        throwOnError: false,
        maxExpand: 200,
        maxSize: 10,
        strict: "ignore",
        macros: {},
        output: "htmlAndMathml",
      });
    } catch {
      element.textContent = expression;
    }
  }, [expression, display]);
  return (
    <span
      ref={target}
      className={display ? "knowledge-math-block" : "knowledge-math-inline"}
      style={
        display
          ? { display: "block", maxWidth: "100%", overflowX: "auto" }
          : undefined
      }
    />
  );
}
