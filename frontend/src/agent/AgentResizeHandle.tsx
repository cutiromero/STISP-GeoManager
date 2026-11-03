import { useRef, useState } from "react";

export default function AgentResizeHandle({
  orientation,
  label,
  hint,
  controls,
  value,
  min,
  max,
  defaultValue,
  reverse = false,
  onChange,
}: {
  orientation: "horizontal" | "vertical";
  label: string;
  hint: string;
  controls: string;
  value: number;
  min: number;
  max: number;
  defaultValue: number;
  reverse?: boolean;
  onChange: (value: number) => void;
}) {
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{
    pointer: number;
    position: number;
    value: number;
  } | null>(null);
  const vertical = orientation === "vertical";
  const update = (next: number) =>
    onChange(Math.round(Math.min(max, Math.max(min, next))));
  const finish = () => {
    drag.current = null;
    setDragging(false);
  };
  return (
    <div
      role="separator"
      tabIndex={0}
      aria-label={label}
      aria-controls={controls}
      aria-orientation={orientation}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={value}
      aria-valuetext={`${value} px`}
      title={hint}
      className={`agent-resize-handle agent-resize-${orientation}${dragging ? " is-dragging" : ""}`}
      onDoubleClick={() => update(defaultValue)}
      onKeyDown={(event) => {
        const step = event.shiftKey ? 32 : 16;
        const increase = vertical
          ? reverse
            ? "ArrowLeft"
            : "ArrowRight"
          : "ArrowUp";
        const decrease = vertical
          ? reverse
            ? "ArrowRight"
            : "ArrowLeft"
          : "ArrowDown";
        const next =
          event.key === increase
            ? value + step
            : event.key === decrease
              ? value - step
              : event.key === "Home"
                ? min
                : event.key === "End"
                  ? max
                  : event.key === "Enter"
                    ? defaultValue
                    : undefined;
        if (next !== undefined) {
          event.preventDefault();
          update(next);
        }
      }}
      onPointerDown={(event) => {
        if (event.button !== 0 || drag.current) return;
        event.preventDefault();
        event.currentTarget.focus();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = {
          pointer: event.pointerId,
          position: vertical ? event.clientX : event.clientY,
          value,
        };
        setDragging(true);
      }}
      onPointerMove={(event) => {
        const start = drag.current;
        if (!start || start.pointer !== event.pointerId) return;
        const position = vertical ? event.clientX : event.clientY;
        const direction = vertical && !reverse ? 1 : -1;
        update(start.value + (position - start.position) * direction);
      }}
      onPointerUp={(event) => {
        if (drag.current?.pointer !== event.pointerId) return;
        finish();
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
      }}
      onPointerCancel={finish}
      onLostPointerCapture={finish}
    >
      <span aria-hidden="true" />
    </div>
  );
}
