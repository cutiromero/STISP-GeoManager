import { Collapse, InputNumber, Select, Space, Typography } from "antd";
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
  canManage = false,
  options,
  profile,
  output,
  serviceWindow,
  disabled,
  onProfile,
  onOutput,
}: {
  canManage?: boolean;
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
        <Typography.Text>{ui("分析方案", "Analysis profile")}</Typography.Text>
        <Select
          aria-label={ui("分析方案", "Analysis profile")}
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
        <Typography.Text type="secondary">
          {profile === "materials"
            ? ui(
                "阅读长文档、整理大量材料",
                "Read long documents and organize material",
              )
            : profile === "reasoning"
              ? ui(
                  "复杂问题、多步推导",
                  "Complex questions and multi-step reasoning",
                )
              : ui(
                  "日常问答、常规数据分析",
                  "Everyday questions and data analysis",
                )}
        </Typography.Text>
      </Space>
      {canManage && (
        <Collapse
          ghost
          size="small"
          items={[
            {
              key: "advanced",
              label: ui("高级设置", "Advanced settings"),
              children: (
                <>
                  <Space wrap>
                    <Typography.Text>
                      {ui("生成上限", "Generation limit")}
                    </Typography.Text>
                    <InputNumber
                      aria-label={ui(
                        "本次生成上限",
                        "Generation limit for this task",
                      )}
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
                      {ui(
                        "留空用方案默认值",
                        "Leave empty for profile default",
                      )}
                    </Typography.Text>
                  </Space>
                  <Typography.Paragraph
                    type="secondary"
                    style={{ margin: "4px 0" }}
                  >
                    {ui("总窗口", "Total window")}{" "}
                    {budget.window.toLocaleString()} token /{" "}
                    {ui("可用输入", "Available input")}{" "}
                    {budget.input.toLocaleString()} token /{" "}
                    {ui("时限", "Timeout")} {budget.seconds / 60}{" "}
                    {ui("分钟", "minutes")}
                  </Typography.Paragraph>
                </>
              ),
            },
          ]}
        />
      )}
    </div>
  );
}
