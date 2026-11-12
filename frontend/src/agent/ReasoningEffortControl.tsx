import { Button, Popover, Slider, Typography } from "antd";
import { DownOutlined } from "@ant-design/icons";
import type { AgentRunInput } from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";

export type ReasoningEffort = NonNullable<AgentRunInput["reasoningEffort"]>;
const efforts: ReasoningEffort[] = ["low", "medium", "xhigh"];

export default function ReasoningEffortControl({
  value,
  overridden,
  disabled,
  onChange,
  effortEnabled = true,
}: {
  value: ReasoningEffort;
  overridden: boolean;
  disabled: boolean;
  onChange: (value: ReasoningEffort | undefined) => void;
  effortEnabled?: boolean;
}) {
  const ui = useComputeText();
  const labels = [
    ui("轻量", "Light"),
    ui("标准", "Standard"),
    ui("深度", "Deep"),
  ];
  return (
    <Popover
      trigger="click"
      placement="top"
      title={ui("思考强度", "Reasoning effort")}
      content={
        <div className="agent-reasoning-settings">
          <Slider
            min={0}
            max={2}
            step={1}
            value={efforts.indexOf(value)}
            marks={{ 0: labels[0], 1: labels[1], 2: labels[2] }}
            tooltip={{ formatter: (index) => labels[index ?? 1] }}
            ariaLabelForHandle={ui("思考强度", "Reasoning effort")}
            disabled={disabled}
            onChange={(index) => onChange(efforts[index])}
            onChangeComplete={(index) => onChange(efforts[index])}
          />
          <Typography.Paragraph type="secondary" className="agent-effort-hint">
            {effortEnabled
              ? ui(
                  "更高强度通常需要更多思考时间。",
                  "Higher effort usually takes more time.",
                )
              : ui(
                  "选择强度将开启深度思考。",
                  "Choosing an effort level enables deep thinking.",
                )}
          </Typography.Paragraph>
          <Button
            type="link"
            size="small"
            disabled={disabled || !overridden}
            onClick={() => onChange(undefined)}
          >
            {ui("使用默认强度", "Use default effort")}
          </Button>
        </div>
      }
    >
      <Button
        type="text"
        disabled={disabled}
        aria-label={ui("调整思考强度", "Adjust reasoning effort")}
      >
        {ui("思考强度", "Effort")}
        {effortEnabled ? ` ${labels[efforts.indexOf(value)]}` : ""}{" "}
        <DownOutlined />
      </Button>
    </Popover>
  );
}
