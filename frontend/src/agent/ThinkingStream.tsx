import { useLayoutEffect, useRef, useState } from "react";

export default function ThinkingStream({
  text,
  working,
}: {
  text: string;
  working: boolean;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const [initialLength] = useState(text.length);
  useLayoutEffect(() => {
    if (follow.current && viewport.current)
      viewport.current.scrollTop = viewport.current.scrollHeight;
  }, [text]);
  let offset = 0;
  const lines = text.split("\n").map((value) => {
    const line = { value, offset };
    offset += value.length + 1;
    return line;
  });
  return (
    <div
      className={`agent-thinking-content${working ? " is-streaming" : ""}`}
      ref={viewport}
      aria-label="模型思考内容"
      onScroll={(event) => {
        const box = event.currentTarget;
        follow.current =
          box.scrollHeight - box.scrollTop - box.clientHeight < 48;
      }}
    >
      {lines.map((line) => (
        <div
          key={`offset-${line.offset}`}
          className={`agent-thinking-line${working && line.offset >= initialLength ? " is-new" : ""}`}
        >
          {line.value || "\u00a0"}
          {working && line.offset === lines[lines.length - 1]?.offset && (
            <span className="agent-stream-cursor" aria-hidden="true" />
          )}
        </div>
      ))}
    </div>
  );
}
