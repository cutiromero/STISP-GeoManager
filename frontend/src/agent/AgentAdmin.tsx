import {
  Alert,
  App,
  Button,
  Card,
  Form,
  InputNumber,
  Select,
  Space,
  Spin,
  Switch,
  Typography,
} from "antd";
import { useEffect, useState } from "react";
import { agentApi } from "../api/agent";
import type {
  AgentAdmin as AgentAdminData,
  AgentPolicy,
} from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";
import "./agent.css";

export default function AgentAdmin() {
  const ui = useComputeText();
  const { message } = App.useApp();
  const [data, setData] = useState<AgentAdminData | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<AgentPolicy>();
  const load = async () => {
    try {
      const result = await agentApi.admin();
      setData(result);
      form.setFieldsValue(result.policy);
      setError("");
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : ui("无法读取配置", "Unable to read settings"),
      );
    }
  };
  useEffect(() => {
    void load();
  }, []);
  const save = async (value: AgentPolicy) => {
    if (!data) return;
    setSaving(true);
    try {
      const result = await agentApi.savePolicy({
        policy: value,
        revision: data.revision,
      });
      setData(result);
      form.setFieldsValue(result.policy);
      message.success(ui("智能体设置已保存", "Agent settings saved"));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : ui("保存失败", "Save failed"));
    } finally {
      setSaving(false);
    }
  };
  const groups =
    data?.groups.map((g) => ({ label: g.name, value: g.id })) ?? [];
  const users = data?.users.map((u) => ({ label: u.name, value: u.id })) ?? [];
  const audience = (prefix: (string | number)[]) => (
    <>
      <Form.Item
        name={[...prefix, "restricted"]}
        label={ui("限制可见范围", "Restrict audience")}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name={[...prefix, "groupIds"]}
        label={ui("允许的用户组", "Allowed groups")}
      >
        <Select mode="multiple" options={groups} />
      </Form.Item>
      <Form.Item
        name={[...prefix, "userIds"]}
        label={ui("允许的用户", "Allowed users")}
      >
        <Select
          mode="multiple"
          options={users}
          showSearch
          optionFilterProp="label"
        />
      </Form.Item>
      <Form.Item
        name={[...prefix, "deniedUserIds"]}
        label={ui("禁用的用户（优先）", "Denied users (takes precedence)")}
      >
        <Select
          mode="multiple"
          options={users}
          showSearch
          optionFilterProp="label"
        />
      </Form.Item>
    </>
  );
  if (!data) return error ? <Alert type="error" title={error} /> : <Spin />;
  return (
    <div className="agent-settings">
      <Typography.Title level={3}>
        {ui("智能体管理", "Agent settings")}
      </Typography.Title>
      {error && (
        <Alert
          type="error"
          title={error}
          action={
            <Button onClick={() => void load()}>{ui("刷新", "Refresh")}</Button>
          }
        />
      )}
      <Alert
        type="info"
        title={ui(
          "使用范围仍受功能权限和项目成员关系约束；以下设置只会收窄权限。",
          "These policies narrow existing feature and project permissions.",
        )}
        description={`${ui("工作进程", "Worker")}: ${data.workerOnline ? ui("在线", "Online") : ui("离线", "Offline")} · ${ui("排队", "Queued")}: ${data.queued} · ${ui("运行", "Running")}: ${data.running}`}
      />
      <Form
        form={form}
        layout="vertical"
        onFinish={save}
        initialValues={data.policy}
      >
        <Card
          title={ui("功能与用户范围", "Features and audiences")}
          style={{ marginTop: 16 }}
        >
          <Space size="large" wrap>
            {(
              [
                ["enabled", "模块总开关", "Module enabled"],
                ["chatEnabled", "模型对话", "Model chat"],
                ["agentEnabled", "数据智能体", "Data agent"],
                ["thinkingEnabled", "允许深度思考", "Allow deep thinking"],
                ["workflowEnabled", "科研工作流规划", "Research workflows"],
                [
                  "operatorEnabled",
                  "允许智能体提交算子",
                  "Allow agent operators",
                ],
                [
                  "systemInfoEnabled",
                  "允许读取系统参数",
                  "Allow system information",
                ],
                ["internetEnabled", "允许联网检索", "Allow internet retrieval"],
                [
                  "allowAttachments",
                  "允许上传文档和图片",
                  "Allow document and image uploads",
                ],
              ] as const
            ).map(([key, zh, en]) => (
              <Form.Item
                key={key}
                name={key}
                label={ui(zh, en)}
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
            ))}
          </Space>
          <Typography.Title level={5}>
            {ui("模型对话使用范围", "Chat audience")}
          </Typography.Title>
          {audience(["chatAudience"])}
          <Typography.Title level={5}>
            {ui("数据智能体使用范围", "Data agent audience")}
          </Typography.Title>
          {audience(["agentAudience"])}
        </Card>
        <Card
          title={ui("模型与默认设置", "Models and defaults")}
          style={{ marginTop: 16 }}
        >
          <Form.Item
            name="defaultChatModel"
            label={ui("聊天默认模型", "Default chat model")}
          >
            <Select
              options={data.models.map((m) => ({
                value: m.alias,
                label: m.name,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="defaultAgentModel"
            label={ui("智能体默认模型", "Default agent model")}
          >
            <Select
              options={data.models.map((m) => ({
                value: m.alias,
                label: m.name,
              }))}
            />
          </Form.Item>
          <Form.List name="models">
            {(fields) =>
              fields.map((field) => (
                <Card
                  key={field.key}
                  size="small"
                  title={`${data.models.find((m) => m.alias === data.policy.models[field.name]?.alias)?.name ?? data.policy.models[field.name]?.alias} · ${data.models.find((m) => m.alias === data.policy.models[field.name]?.alias)?.status}`}
                  style={{ marginTop: 12 }}
                >
                  <Form.Item name={[field.name, "alias"]} hidden>
                    <Select />
                  </Form.Item>
                  <Space size="large" wrap>
                    <Form.Item
                      name={[field.name, "enabled"]}
                      label={ui("启用", "Enabled")}
                      valuePropName="checked"
                    >
                      <Switch />
                    </Form.Item>
                    <Form.Item
                      name={[field.name, "allowAgent"]}
                      label={ui("允许数据智能体", "Allow data agent")}
                      valuePropName="checked"
                    >
                      <Switch />
                    </Form.Item>
                    <Form.Item
                      name={[field.name, "sortOrder"]}
                      label={ui("排序", "Order")}
                    >
                      <InputNumber min={0} max={999} />
                    </Form.Item>
                    <Form.Item
                      name={[field.name, "concurrency"]}
                      label={ui("模型并发", "Concurrency")}
                    >
                      <InputNumber min={1} max={3} />
                    </Form.Item>
                  </Space>
                  <Typography.Text type="secondary">
                    {(() => {
                      const model = data.models.find(
                        (item) =>
                          item.alias === data.policy.models[field.name]?.alias,
                      );
                      return ui(
                        `模型窗口：${model?.contextWindowTokens ?? "未知"} token · ${model?.supportsThinking ? "支持深度思考" : "仅快速回答"}`,
                        `Context window: ${model?.contextWindowTokens ?? "unknown"} tokens · ${model?.supportsThinking ? "deep thinking supported" : "fast mode only"}`,
                      );
                    })()}
                  </Typography.Text>
                  {audience([field.name, "audience"])}
                </Card>
              ))
            }
          </Form.List>
        </Card>
        <Card
          title={ui("上下文与生成参数", "Context and generation")}
          style={{ marginTop: 16 }}
        >
          <Typography.Paragraph type="secondary">
            {ui(
              "模型窗口以各模型卡片中的服务实测值为准。输入预算与生成预留共享窗口；生成量包含思考和正文。保存后新运行采用新参数，已有运行保留开始时的参数。",
              "Model cards show the serving window. Input and generation share it; generation includes reasoning and the final answer. Saved settings apply to new runs.",
            )}
          </Typography.Paragraph>
          <Space size="large" wrap>
            <Form.Item
              name="maxContextBytes"
              label={ui(
                "输入文本大小保护（字节）",
                "Input text size guard (bytes)",
              )}
              extra={ui(
                "文本大小保护；模型窗口通过实际分词另行检查",
                "Text size guard; the tokenizer checks the actual window separately",
              )}
            >
              <InputNumber min={8000} max={500000} step={1000} />
            </Form.Item>
            <Form.Item
              name="maxOutputTokens"
              label={ui(
                "思考＋正文生成上限（token）",
                "Reasoning + answer token limit",
              )}
            >
              <InputNumber min={128} max={32768} step={1024} />
            </Form.Item>
            <Form.Item
              name="maxContextTokens"
              label={ui("输入预算（token）", "Input token budget")}
            >
              <InputNumber min={1024} max={262144} step={1024} />
            </Form.Item>
            <Form.Item
              name="reasoningEffort"
              label={ui("深度思考强度", "Reasoning effort")}
            >
              <Select
                style={{ minWidth: 170 }}
                options={[
                  { value: "low", label: ui("低 · 较快", "Low · faster") },
                  {
                    value: "medium",
                    label: ui("中 · 均衡", "Medium · balanced"),
                  },
                  {
                    value: "xhigh",
                    label: ui("高 · 更长思考", "High · longer reasoning"),
                  },
                ]}
              />
            </Form.Item>
            <Form.Item name="temperature" label="Temperature">
              <InputNumber min={0} max={2} step={0.1} />
            </Form.Item>
            <Form.Item name="topP" label="Top P">
              <InputNumber min={0} max={1} step={0.05} />
            </Form.Item>
            <Form.Item
              name="maxProtocolRetries"
              label={ui("协议纠错次数", "Protocol retries")}
            >
              <InputNumber min={0} max={3} />
            </Form.Item>
            <Form.Item
              name="maxRunSeconds"
              label={ui("单次最长秒数", "Max run seconds")}
            >
              <InputNumber min={60} max={1800} step={30} />
            </Form.Item>
            <Form.Item
              name="maxAttachmentBytes"
              label={ui("单个附件上限（字节）", "Max attachment bytes")}
              extra={ui("建议不超过 50 MB", "Recommended maximum: 50 MB")}
            >
              <InputNumber min={1024} max={200_000_000} step={1024 * 1024} />
            </Form.Item>
            <Form.Item
              name="maxAttachments"
              label={ui("每次最多附件数", "Max attachments per run")}
            >
              <InputNumber min={1} max={20} />
            </Form.Item>
          </Space>
        </Card>
        <Card
          title={ui("额度与只读能力", "Quotas and read-only capabilities")}
          style={{ marginTop: 16 }}
        >
          <Space size="large" wrap>
            {(
              [
                ["dailyRuns", "每人每日次数", "Daily runs per user", 1, 1000],
                ["maxSteps", "最多工具步骤", "Tool step limit", 1, 64],
                ["maxResources", "最多详细资源", "Resource limit", 1, 3],
                [
                  "maxIterations",
                  "迭代上限（后续扩展预留）",
                  "Iteration limit (reserved)",
                  1,
                  20,
                ],
                [
                  "maxOperatorSteps",
                  "最大算子步骤",
                  "Operator step limit",
                  1,
                  64,
                ],
              ] as const
            ).map(([key, zh, en, min, max]) => (
              <Form.Item key={key} name={key} label={ui(zh, en)}>
                <InputNumber
                  min={min}
                  max={max}
                  disabled={key === "maxIterations"}
                />
              </Form.Item>
            ))}
          </Space>
          <Form.Item
            name="dataTypes"
            label={ui("允许读取的数据类型", "Allowed data types")}
          >
            <Select
              mode="multiple"
              options={[
                ["table", "表格", "Table"],
                ["vector", "矢量", "Vector"],
                ["raster", "栅格元数据", "Raster metadata"],
                ["gene", "基因结构摘要", "Gene summaries"],
                ["document", "文档", "Document"],
                ["image", "图片元数据", "Image metadata"],
              ].map(([value, zh, en]) => ({ value, label: ui(zh!, en!) }))}
            />
          </Form.Item>
          <Form.Item
            name="allowDocuments"
            label={ui("文档正文读取（纯文本）", "Document text (plain text)")}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="allowCompare"
            label={ui("跨资源比较", "Cross-resource comparison")}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Typography.Paragraph>
            {ui(
              "科研工作流默认只生成计划。开启算子提交前，请先完成算法清单、隔离环境和固定样例验收；代码执行、写入和发布仍保持关闭。",
              "Research workflows create plans by default. Before enabling operators, validate manifests, isolation and fixed samples; code execution, writes and publishing remain disabled.",
            )}
          </Typography.Paragraph>
          <Form.List name="quotas">
            {(fields, { add, remove }) => (
              <>
                {fields.map((field) => (
                  <Space key={field.key} wrap align="start">
                    <Form.Item
                      name={[field.name, "kind"]}
                      rules={[{ required: true }]}
                    >
                      <Select
                        style={{ width: 130 }}
                        options={[
                          { value: "user", label: ui("用户", "User") },
                          { value: "group", label: ui("用户组", "Group") },
                        ]}
                      />
                    </Form.Item>
                    <Form.Item noStyle shouldUpdate>
                      {() => (
                        <Form.Item
                          name={[field.name, "id"]}
                          rules={[{ required: true }]}
                        >
                          <Select
                            style={{ width: 200 }}
                            options={
                              form.getFieldValue([
                                "quotas",
                                field.name,
                                "kind",
                              ]) === "group"
                                ? groups
                                : users
                            }
                          />
                        </Form.Item>
                      )}
                    </Form.Item>
                    <Form.Item
                      name={[field.name, "dailyRuns"]}
                      label={ui("每日次数", "Daily limit")}
                      rules={[{ required: true }]}
                    >
                      <InputNumber min={1} max={1000} />
                    </Form.Item>
                    <Button danger onClick={() => remove(field.name)}>
                      {ui("移除", "Remove")}
                    </Button>
                  </Space>
                ))}
                <Button onClick={() => add({ kind: "user", dailyRuns: 20 })}>
                  {ui("添加用户或组额度限制", "Add user or group quota")}
                </Button>
              </>
            )}
          </Form.List>
        </Card>
        <Space style={{ marginTop: 20 }}>
          <Button type="primary" htmlType="submit" loading={saving}>
            {ui("保存设置", "Save settings")}
          </Button>
          <Button onClick={() => void load()}>
            {ui("重新读取", "Reload")}
          </Button>
        </Space>
      </Form>
    </div>
  );
}
