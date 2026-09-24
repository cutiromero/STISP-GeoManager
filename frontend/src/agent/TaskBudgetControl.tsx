import { InputNumber, Select, Space, Typography } from "antd";
import type {
  AgentBudgetOptions,
  AgentBudgetProfileId,
} from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";

export function budgetPreview(
  options: AgentBudgetOptions,
  profile: AgentBudgetProfileId,
  serviceWindow: number,
  override?: number,
) {
  const preset = options.profiles.find(
    (item) => item.budgetProfile === profile,
  );
  const window = Math.min(serviceWindow, options.limits.contextWindowTokens);
  const ceiling = Math.min(options.limits.maxOutputTokens, window - 512);
  const output =
    override ??
    Math.min(preset?.maxOutputTokens ?? 128, ceiling, Math.floor(window / 2));
  return {
    window,
    ceiling,
    output,
    input: Math.max(0, window - output - 256),
    seconds: preset?.maxRunSeconds ?? 0,
  };
}

export default function TaskBudgetControl({
  options,
  profile,
  output,
  serviceWindow,
  disabled,
  onProfile,
  onOutput,
}: {
  options: AgentBudgetOptions;
  profile: AgentBudgetProfileId;
  output?: number;
  serviceWindow: number;
  disabled: boolean;
  onProfile: (value: AgentBudgetProfileId) => void;
  onOutput: (value: number | undefined) => void;
}) {
  const ui = useComputeText();
  const budget = budgetPreview(options, profile, serviceWindow, output);
  return (
    <div style={{ marginTop: 8 }}>
      <Space wrap>
        <Typography.Text>{ui("任务预算", "Task budget")}</Typography.Text>
        <Select
          aria-label={ui("任务预算", "Task budget")}
          value={profile}
          disabled={disabled}
          style={{ minWidth: 130 }}
          onChange={onProfile}
          options={[
            { value: "normal", label: ui("普通分析", "General analysis") },
            { value: "materials", label: ui("长材料", "Long documents") },
            { value: "reasoning", label: ui("长推理", "Long reasoning") },
          ]}
        />
        <Typography.Text>{ui("生成上限", "Generation limit")}</Typography.Text>
        <InputNumber
          aria-label={ui("本次生成上限", "Generation limit for this task")}
          value={output ?? null}
          placeholder={String(budget.output)}
          min={128}
          max={budget.ceiling}
          step={1024}
          disabled={disabled}
          onChange={(value) => onOutput(value ?? undefined)}
          style={{ width: 140 }}
        />
        <Typography.Text type="secondary">
          {ui("留空用方案默认值", "Leave empty for profile default")}
        </Typography.Text>
      </Space>
      <Typography.Paragraph type="secondary" style={{ margin: "4px 0" }}>
        {ui("服务窗口", "Serving window")} {serviceWindow.toLocaleString()} ·{" "}
        {ui("您可用", "Your window")} {budget.window.toLocaleString()} ·{" "}
        {ui("输入预算", "Input budget")} {budget.input.toLocaleString()} ·{" "}
        {ui("思考＋正文预留", "Reasoning + answer reserve")}{" "}
        {budget.output.toLocaleString()} token · {ui("时限", "Timeout")}{" "}
        {budget.seconds / 60} {ui("分钟", "minutes")}
      </Typography.Paragraph>
      <Typography.Text type="secondary">
        {ui(
          "实际输入还包含历史、系统说明、工具结果和附件；发送后显示实际占用。长推理需同时选择深度思考。",
          "Input also includes history, instructions, tool results and attachments. Actual usage appears after submission. Select deep thinking when using long reasoning.",
        )}
      </Typography.Text>
    </div>
  );
}
