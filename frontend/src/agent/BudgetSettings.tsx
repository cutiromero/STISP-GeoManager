import {
  Card,
  Form,
  InputNumber,
  Select,
  Space,
  Switch,
  Typography,
} from "antd";
import { useComputeText } from "../compute/ui";

export default function BudgetSettings() {
  const ui = useComputeText();
  const profiles = [
    { value: "normal", label: ui("普通分析", "General analysis") },
    { value: "materials", label: ui("长材料", "Long documents") },
    { value: "reasoning", label: ui("长推理", "Long reasoning") },
  ];
  return (
    <Card
      title={ui("任务预算与用户上限", "Task budgets and user limits")}
      style={{ marginTop: 16 }}
    >
      <Typography.Paragraph type="secondary">
        {ui(
          "模型服务决定实际窗口；以下设置决定用户可用额度。输入预算＝可用窗口－本次生成预留－256 token 安全余量。生成包括思考和正文，按实际用量消耗，不会强制写满。任务时限是平台设置。",
          "The serving model sets the physical window; these settings control user allowances. Input budget = available window − generation reserve − 256 safety tokens. Generation includes reasoning and answers, and is consumed only as needed. Runtime limits are platform settings.",
        )}
      </Typography.Paragraph>
      <Form.Item
        name="taskBudgetsEnabled"
        label={ui("开启按任务分配预算", "Enable task budgets")}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name="defaultBudgetProfile"
        label={ui("默认任务方案", "Default task profile")}
      >
        <Select options={profiles} />
      </Form.Item>
      {profiles.map(({ value, label }) => (
        <Card key={value} size="small" title={label} style={{ marginTop: 12 }}>
          <Space wrap size="large">
            <Form.Item
              name={["budgetProfiles", value, "maxOutputTokens"]}
              label={ui(
                "默认思考＋正文上限（token）",
                "Default generation limit (tokens)",
              )}
            >
              <InputNumber min={128} step={1024} />
            </Form.Item>
            <Form.Item
              name={["budgetProfiles", value, "maxRunSeconds"]}
              label={ui("默认任务时限（秒）", "Default task timeout (seconds)")}
            >
              <InputNumber min={60} step={60} />
            </Form.Item>
            <Form.Item
              name={["budgetProfiles", value, "reasoningEffort"]}
              label={ui("深度模式思考强度", "Deep mode reasoning effort")}
            >
              <Select
                style={{ width: 150 }}
                options={[
                  { value: "low", label: ui("低", "Low") },
                  { value: "medium", label: ui("中", "Medium") },
                  { value: "xhigh", label: ui("高", "High") },
                ]}
              />
            </Form.Item>
          </Space>
        </Card>
      ))}
      {(
        [
          [
            "standard",
            ui(
              "普通用户（含平台管理员）",
              "Standard users (including platform admins)",
            ),
          ],
          ["superadmin", ui("超级管理员", "Superadmins")],
        ] as const
      ).map(([tier, label]) => (
        <Card key={tier} size="small" title={label} style={{ marginTop: 12 }}>
          <Space wrap size="large">
            <Form.Item
              name={["budgetLimits", tier, "contextWindowTokens"]}
              label={ui("允许总窗口（token）", "Allowed window (tokens)")}
            >
              <InputNumber min={1024} step={1024} />
            </Form.Item>
            <Form.Item
              name={["budgetLimits", tier, "maxOutputTokens"]}
              label={ui("允许生成上限（token）", "Generation ceiling (tokens)")}
              extra={ui(
                "须至少给输入和安全余量留下512 token",
                "Leave at least 512 tokens for input and safety",
              )}
            >
              <InputNumber min={128} step={1024} />
            </Form.Item>
            <Form.Item
              name={["budgetLimits", tier, "maxRunSeconds"]}
              label={ui("允许最长时限（秒）", "Timeout ceiling (seconds)")}
            >
              <InputNumber min={60} step={60} />
            </Form.Item>
          </Space>
        </Card>
      ))}
      <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
        {ui(
          "方案默认值会按用户上限和所选模型窗口收窄。这里适用于快速对话和科研智能体；MH-workflow规划仍使用下方全局参数。",
          "Profile defaults are capped by the user allowance and selected model. These budgets apply to chat and data agents; research workflow planning uses the global settings below.",
        )}
      </Typography.Paragraph>
    </Card>
  );
}
