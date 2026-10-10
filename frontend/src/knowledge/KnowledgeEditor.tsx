import {
  Alert,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
} from "antd";
import { useState } from "react";
import type {
  KnowledgeEntry,
  KnowledgeEntryInput,
  KnowledgeSource,
  KnowledgeDomain,
} from "../api/generated/types.gen";
import { knowledgeApi } from "../api/knowledge";
import { KNOWLEDGE_DOMAINS } from "./domains";

type EditorFields = Pick<
  KnowledgeEntryInput,
  | "title"
  | "category"
  | "domain"
  | "subject"
  | "predicate"
  | "object"
  | "statement"
  | "explanation"
  | "status"
  | "ruleKind"
> & {
  conditions: string;
  exceptions: string;
  aliases: string;
  sources: KnowledgeSource[];
  minerals: string;
  system: string;
  field: string;
  minimum: number;
  maximum: number;
  unit: string;
  fields: string;
};
const lines = (value?: string) =>
  (value ?? "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
export const ruleLabels = {
  none: "解释与人工核查",
  mineral_equilibrium: "矿物平衡组合",
  numeric_range: "数值范围",
  required_fields: "必需字段",
};
export const stateLabels = {
  draft: "草稿",
  published: "已发布",
  retired: "已停用",
};

export default function KnowledgeEditor({
  entry,
  categories,
  defaultDomain,
  onClose,
  onSaved,
}: {
  entry: KnowledgeEntry | null;
  categories: string[];
  defaultDomain?: KnowledgeDomain;
  onClose: () => void;
  onSaved: (entry: KnowledgeEntry) => void;
}) {
  const [form] = Form.useForm<EditorFields>();
  const kind = Form.useWatch("ruleKind", form) ?? entry?.ruleKind ?? "none";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const config = entry?.ruleConfig ?? {};
  const initial = {
    ...entry,
    domain: entry?.domain ?? defaultDomain ?? "geology",
    conditions: entry?.conditions.join("\n"),
    exceptions: entry?.exceptions.join("\n"),
    aliases: entry?.aliases.join("\n"),
    sources: entry?.sources.length
      ? entry.sources
      : [{ title: "", url: "", locator: "", excerpt: "" }],
    status: entry?.status ?? "draft",
    ruleKind: entry?.ruleKind ?? "none",
    minerals: Array.isArray(config.minerals) ? config.minerals.join("\n") : "",
    system: config.system,
    field: config.field,
    minimum: config.minimum,
    maximum: config.maximum,
    unit: config.unit,
    fields: Array.isArray(config.fields) ? config.fields.join("\n") : "",
  };
  async function save() {
    try {
      const value = await form.validateFields();
      let ruleConfig: KnowledgeEntryInput["ruleConfig"] = {};
      if (value.ruleKind === "mineral_equilibrium")
        ruleConfig = { minerals: lines(value.minerals), system: value.system };
      if (value.ruleKind === "numeric_range")
        ruleConfig = {
          field: value.field,
          minimum: value.minimum,
          maximum: value.maximum,
          unit: value.unit ?? "",
        };
      if (value.ruleKind === "required_fields")
        ruleConfig = { fields: lines(value.fields) };
      const body: KnowledgeEntryInput = {
        title: value.title,
        category: value.category,
        domain: value.domain,
        subject: value.subject,
        predicate: value.predicate,
        object: value.object,
        statement: value.statement,
        explanation: value.explanation ?? "",
        status: value.status,
        ruleKind: value.ruleKind,
        ruleConfig,
        conditions: lines(value.conditions),
        exceptions: lines(value.exceptions),
        aliases: lines(value.aliases),
        sources: (value.sources ?? [])
          .filter(
            (source) =>
              source &&
              (source.title || source.url || source.locator || source.excerpt),
          )
          .map((source) => ({
            title: source.title ?? "",
            url: source.url ?? "",
            locator: source.locator ?? "",
            excerpt: source.excerpt ?? "",
          })),
        ...(entry ? { revision: entry.revision } : {}),
      };
      setBusy(true);
      setError("");
      onSaved(await knowledgeApi.save(entry?.id ?? null, body));
    } catch (failure) {
      if (failure instanceof Error) setError(failure.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open
      width={820}
      title={entry ? `维护知识 · v${entry.revision}` : "新建知识条目"}
      onCancel={onClose}
      onOk={() => void save()}
      okText="保存知识"
      cancelText="取消"
      confirmLoading={busy}
      maskClosable={!busy}
    >
      {error && <Alert type="error" showIcon title={error} />}
      <Form
        form={form}
        layout="vertical"
        initialValues={initial}
        className="knowledge-editor"
      >
        <Form.Item
          name="title"
          label="条目标题"
          rules={[{ required: true, whitespace: true }]}
        >
          <Input maxLength={180} />
        </Form.Item>
        <div className="knowledge-form-pair">
          <Form.Item
            name="domain"
            label="知识分区"
            rules={[{ required: true }]}
          >
            <Select
              options={KNOWLEDGE_DOMAINS.map((item) => ({
                value: item.id,
                label: item.label,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="category"
            label="细分类"
            rules={[{ required: true, whitespace: true }]}
          >
            <Input maxLength={80} list="knowledge-category-options" />
          </Form.Item>
          <datalist id="knowledge-category-options">
            {categories.map((category) => (
              <option key={category} value={category} />
            ))}
          </datalist>
          <Form.Item name="status" label="发布状态">
            <Select
              options={Object.entries(stateLabels).map(([value, label]) => ({
                value,
                label,
              }))}
            />
          </Form.Item>
        </div>
        <div className="knowledge-form-relation">
          {(
            [
              ["subject", "主体"],
              ["predicate", "关系"],
              ["object", "客体"],
            ] as const
          ).map(([name, label]) => (
            <Form.Item
              key={name}
              name={name}
              label={label}
              rules={[{ required: true, whitespace: true }]}
            >
              <Input maxLength={120} />
            </Form.Item>
          ))}
        </div>
        <Form.Item
          name="statement"
          label="知识陈述"
          rules={[{ required: true, whitespace: true }]}
        >
          <Input.TextArea rows={3} maxLength={4000} />
        </Form.Item>
        <Form.Item name="explanation" label="解释与使用方法">
          <Input.TextArea rows={3} maxLength={8000} />
        </Form.Item>
        <div className="knowledge-form-pair">
          <Form.Item name="conditions" label="适用条件（每行一项）">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="exceptions" label="例外与核验条件（每行一项）">
            <Input.TextArea rows={3} />
          </Form.Item>
        </div>
        <Form.Item name="aliases" label="别名与检索关键词（每行一项）">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item name="ruleKind" label="核查方式">
          <Select
            options={Object.entries(ruleLabels).map(([value, label]) => ({
              value,
              label,
            }))}
          />
        </Form.Item>
        {kind === "mineral_equilibrium" && (
          <div className="knowledge-form-pair">
            <Form.Item
              name="minerals"
              label="待核查矿物组合（每行一个，至少两个）"
              rules={[
                { required: true },
                {
                  validator: (_, value) =>
                    lines(value).length >= 2
                      ? Promise.resolve()
                      : Promise.reject(new Error("至少填写两个矿物名称")),
                },
              ]}
            >
              <Input.TextArea rows={3} />
            </Form.Item>
            <Form.Item
              name="system"
              label="适用体系"
              rules={[{ required: true }]}
            >
              <Input maxLength={120} />
            </Form.Item>
          </div>
        )}
        {kind === "numeric_range" && (
          <>
            <div className="knowledge-form-pair">
              <Form.Item
                name="field"
                label="数值字段名"
                rules={[{ required: true }]}
              >
                <Input maxLength={120} />
              </Form.Item>
              <Form.Item name="unit" label="单位">
                <Input />
              </Form.Item>
            </div>
            <div className="knowledge-form-pair">
              <Form.Item
                name="minimum"
                label="下限"
                rules={[{ required: true }]}
              >
                <InputNumber />
              </Form.Item>
              <Form.Item
                name="maximum"
                label="上限"
                rules={[{ required: true }]}
              >
                <InputNumber />
              </Form.Item>
            </div>
          </>
        )}
        {kind === "required_fields" && (
          <Form.Item
            name="fields"
            label="必需的数据字段（每行一个）"
            rules={[{ required: true }]}
          >
            <Input.TextArea rows={3} />
          </Form.Item>
        )}
        <h3>来源依据</h3>
        <p className="knowledge-muted">
          发布条目需要来源标题，以及链接或章节定位。
        </p>
        <Form.List name="sources">
          {(fields, { add, remove }) => (
            <>
              {fields.map(({ key, name, ...rest }) => (
                <div className="knowledge-source-editor" key={key}>
                  <div className="knowledge-form-pair">
                    <Form.Item
                      {...rest}
                      name={[name, "title"]}
                      label="来源标题"
                    >
                      <Input maxLength={300} />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, "url"]} label="来源链接">
                      <Input placeholder="https://" maxLength={1000} />
                    </Form.Item>
                  </div>
                  <Form.Item
                    {...rest}
                    name={[name, "locator"]}
                    label="章节或页码"
                  >
                    <Input maxLength={500} />
                  </Form.Item>
                  <Form.Item
                    {...rest}
                    name={[name, "excerpt"]}
                    label="对应证据摘录"
                  >
                    <Input.TextArea rows={2} maxLength={1200} />
                  </Form.Item>
                  <Button type="text" danger onClick={() => remove(name)}>
                    移除此来源
                  </Button>
                </div>
              ))}
              <Space>
                <Button
                  disabled={fields.length >= 20}
                  onClick={() =>
                    add({ title: "", url: "", locator: "", excerpt: "" })
                  }
                >
                  添加来源
                </Button>
              </Space>
            </>
          )}
        </Form.List>
      </Form>
    </Modal>
  );
}
