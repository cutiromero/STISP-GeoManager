import { Select } from "antd";
import type { ReasoningEffort } from "./ReasoningEffortControl";

const choices: { value: ReasoningEffort | "off"; label: string }[] = [
  { value: "off", label: "关" },
  { value: "low", label: "低" },
  { value: "medium", label: "中" },
  { value: "xhigh", label: "高" },
];

export default function LogicThinkingControl({
  value,
  disabled,
  onChange,
}: {
  value: ReasoningEffort | "off";
  disabled: boolean;
  onChange: (value: ReasoningEffort | "off") => void;
}) {
  return (
    <label>
      <span>思考</span>
      <Select
        aria-label="思考"
        value={value}
        disabled={disabled}
        options={choices}
        onChange={onChange}
        style={{ width: 80 }}
      />
    </label>
  );
}
