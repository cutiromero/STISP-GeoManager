import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Switch,
} from "antd";
import { useEffect, useRef, useState } from "react";
import type {
  BusinessFlowDefinition,
  BusinessFlowInputBinding,
  BusinessFlowNode,
  BusinessFlowSpec,
  BusinessFlowVersion,
  ComputeAlgorithm,
} from "../api/generated/types.gen";
import { computeApi } from "../api/compute";
import { useComputeText } from "../compute/ui";
import { createUuid } from "../utils/uuid";

export function newBusinessFlowSpec(): BusinessFlowSpec {
  return {
    schemaVersion: 1,
    adapter: "research_flow",
    executionMode: "main_agent",
    skill: {
      title: "科研业务流执行与恢复",
      instructions:
        "由同一主执行智能体贯穿任务。资料与成果按引用交接，只读取必要片段和统计。格式、引用或审核问题先核对原始响应与具体诊断，不裁掉必要证据，不重复已完成工作；自动补救仍无法继续时保留成果，先说明错误位置、实际差距、已尝试办法和需要用户处理的内容，再等待人工补充后从当前节点继续并重新校验。补充说明不授予额外权限、不改变算子核心，也不构成人工批准。",
      nodeInstructions: {},
    },
    inputRequirements: [],
    nodes: [
      {
        id: "research",
        title: "分析项目资料",
        description: "根据任务目标读取资料并形成有依据的分析。",
        kind: "agent",
        dependsOn: [],
        dataRoles: [],
        instruction: "仅使用本项目已授权资料，保留来源依据，不修改原始数据。",
        review: { ai: false, human: false, maxRevisions: 0 },
      },
      {
        id: "deliver",
        title: "整理科研成果",
        description: "汇总上游分析并交付结果。",
        kind: "result",
        dependsOn: ["research"],
        dataRoles: [],
        instruction: "综合已完成的上游结果，清楚说明结论、依据与限制。",
        review: { ai: false, human: false, maxRevisions: 0 },
      },
    ],
    outputRequirements: ["有来源依据的科研分析结果"],
  };
}
const nextKey = (prefix: string, identities: string[]) => {
  const used = new Set(identities);
  let number = 1;
  while (used.has(`${prefix}_${number}`)) number++;
  return `${prefix}_${number}`;
};
const formats = [
  { value: "vector", label: "矢量数据" },
  { value: "raster", label: "栅格影像" },
  { value: "table", label: "数据表" },
  { value: "document", label: "文档" },
  { value: "image", label: "图片" },
  { value: "gene", label: "基因数据" },
];
export default function BusinessFlowEditor({
  open,
  flow,
  version,
  onClose,
  onSave,
}: {
  open: boolean;
  flow?: BusinessFlowDefinition;
  version?: BusinessFlowVersion | null;
  onClose: () => void;
  onSave: (
    metadata: Pick<BusinessFlowDefinition, "code" | "name" | "description">,
    definition: BusinessFlowSpec,
  ) => Promise<void>;
}) {
  const ui = useComputeText();
  const [form] =
    Form.useForm<
      Pick<BusinessFlowDefinition, "code" | "name" | "description">
    >();
  const [spec, setSpec] = useState<BusinessFlowSpec>(newBusinessFlowSpec);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [algorithms, setAlgorithms] = useState<ComputeAlgorithm[]>([]);
  const [algorithmError, setAlgorithmError] = useState("");
  const [algorithmLoading, setAlgorithmLoading] = useState(false);
  const [parameterDrafts, setParameterDrafts] = useState<
    Record<string, string>
  >({});
  const [bindingDrafts, setBindingDrafts] = useState<Record<string, string>>(
    {},
  );
  const saving = useRef(false);
  const rowKeys = useRef(new Map<string, string>());
  const rowKey = (kind: string, id: string) => {
    const key = `${kind}:${id}`;
    if (!rowKeys.current.has(key)) rowKeys.current.set(key, createUuid());
    return rowKeys.current.get(key)!;
  };
  const renameKey = (kind: string, id: string, next: string) => {
    const previous = rowKey(kind, id);
    rowKeys.current.delete(`${kind}:${id}`);
    rowKeys.current.set(`${kind}:${next}`, previous);
  };
  const hasOperator = spec.nodes.some((node) => node.kind === "operator");
  const managedSkeleton = spec.adapter === "geology_generic";
  useEffect(() => {
    if (!open) return;
    setSpec(
      version ? structuredClone(version.definition) : newBusinessFlowSpec(),
    );
    form.setFieldsValue({
      code: flow?.code ?? "",
      name: flow?.name ?? "",
      description: flow?.description ?? "",
    });
    setError("");
    setParameterDrafts({});
    setBindingDrafts({});
    rowKeys.current.clear();
  }, [open, flow?.id, version?.id, form]);
  useEffect(() => {
    if (!open || !hasOperator || managedSkeleton) return;
    const controller = new AbortController();
    setAlgorithmLoading(true);
    setAlgorithmError("");
    void computeApi
      .algorithms({ limit: 200 }, { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setAlgorithms(result.items);
      })
      .catch((reason) => {
        if (!controller.signal.aborted)
          setAlgorithmError(
            reason instanceof Error ? reason.message : "无法读取已发布算子",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setAlgorithmLoading(false);
      });
    return () => controller.abort();
  }, [open, hasOperator, managedSkeleton]);
  const updateNode = (id: string, change: Partial<BusinessFlowNode>) =>
    setSpec((old) => ({
      ...old,
      nodes: old.nodes.map((node) =>
        node.id === id ? { ...node, ...change } : node,
      ),
    }));
  const renameNode = (id: string, next: string) => {
    renameKey("node", id, next);
    setParameterDrafts((old) => {
      if (old[id] === undefined) return old;
      const result = { ...old, [next]: old[id] };
      delete result[id];
      return result;
    });
    setBindingDrafts((old) => {
      const result: Record<string, string> = {};
      for (const [key, text] of Object.entries(old)) {
        let rewritten = text;
        try {
          const value = JSON.parse(text);
          if (value && typeof value === "object" && !Array.isArray(value)) {
            for (const item of Object.values(value))
              if (
                item &&
                typeof item === "object" &&
                "nodeId" in item &&
                item.nodeId === id
              )
                item.nodeId = next;
            rewritten = JSON.stringify(value, null, 2);
          }
        } catch {
          /* Preserve an incomplete draft for the user to correct. */
        }
        result[key === id ? next : key] = rewritten;
      }
      return result;
    });
    setSpec((old) => ({
      ...old,
      nodes: old.nodes.map((node) => ({
        ...node,
        ...(node.id === id ? { id: next } : {}),
        dependsOn: node.dependsOn.map((parent) =>
          parent === id ? next : parent,
        ),
        ...(node.inputBindings
          ? {
              inputBindings: Object.fromEntries(
                Object.entries(node.inputBindings).map(([key, value]) => [
                  key,
                  "nodeId" in value && value.nodeId === id
                    ? { ...value, nodeId: next }
                    : value,
                ]),
              ),
            }
          : {}),
      })),
    }));
  };
  const save = async () => {
    if (saving.current) return;
    saving.current = true;
    setBusy(true);
    setError("");
    try {
      const metadata = await form.validateFields();
      if (!spec.nodes.length) throw new Error("请至少登记一个流程节点。");
      if (
        spec.nodes.some(
          (node) =>
            !node.title.trim() ||
            (!managedSkeleton && !node.instruction.trim()) ||
            !/^([a-z][a-z0-9_-]{1,63})$/.test(node.id),
        )
      )
        throw new Error(
          "请填写节点名称、处理要求和有效的节点编码（2–64位小写字母、数字、连字符或下划线）。",
        );
      const definition = {
        ...spec,
        nodes: spec.nodes.map((node) => {
          if (node.kind !== "operator" || managedSkeleton) return node;
          const next: BusinessFlowNode = { ...node };
          if (parameterDrafts[node.id] !== undefined) {
            let value: unknown;
            try {
              value = JSON.parse(parameterDrafts[node.id]!);
            } catch {
              throw new Error(`${node.title}的固定参数不是有效JSON。`);
            }
            if (!value || typeof value !== "object" || Array.isArray(value))
              throw new Error(`${node.title}的固定参数必须是对象。`);
            next.parameters = value as Record<string, unknown>;
          }
          if (bindingDrafts[node.id] !== undefined) {
            let value: unknown;
            try {
              value = JSON.parse(bindingDrafts[node.id]!);
            } catch {
              throw new Error(`${node.title}的输入来源不是有效JSON。`);
            }
            if (
              !value ||
              typeof value !== "object" ||
              Array.isArray(value) ||
              Object.values(value).some((item) => {
                if (!item || typeof item !== "object" || Array.isArray(item))
                  return true;
                const row = item as Record<string, unknown>,
                  keys = Object.keys(row);
                return !(
                  (keys.length === 1 && typeof row.role === "string") ||
                  (keys.length === 2 &&
                    typeof row.nodeId === "string" &&
                    typeof row.outputKey === "string")
                );
              })
            )
              throw new Error(
                `${node.title}的输入来源必须按资料角色或上游节点输出绑定。`,
              );
            next.inputBindings = value as Record<
              string,
              BusinessFlowInputBinding
            >;
          }
          return next;
        }),
      };
      await onSave(metadata, definition);
    } catch (reason) {
      if (reason instanceof Error) setError(reason.message);
    } finally {
      saving.current = false;
      setBusy(false);
    }
  };
  return (
    <Modal
      open={open}
      title={
        flow
          ? ui("发布业务流新版本", "Publish a new flow version")
          : ui("登记业务流", "Register a business flow")
      }
      onCancel={() => {
        if (!busy) onClose();
      }}
      onOk={() => void save()}
      confirmLoading={busy}
      okText={ui("保存并发布", "Save and publish")}
      cancelText={ui("取消", "Cancel")}
      width={820}
      className="business-flow-modal"
      destroyOnHidden
    >
      <p className="business-flow-editor-intro">
        {ui(
          "发布的版本保留完整流程定义，已有任务继续使用启动时的版本。审核由节点自行配置，简单流程可以直接完成。",
          "Published versions retain their full definitions. Existing tasks keep their original version; reviews are configured per node and may be omitted for simple flows.",
        )}
      </p>
      {!flow && (
        <p className="business-flow-editor-intro">
          {ui(
            "业务流归当前项目。在公开项目登记的通用业务流可供所有项目使用。",
            "Flows belong to the current project. General flows registered in the public project are available in all projects.",
          )}
        </p>
      )}
      {error && (
        <Alert
          type="error"
          showIcon
          title={error}
          style={{ marginBottom: 16 }}
        />
      )}
      <Form
        form={form}
        layout="vertical"
        initialValues={{ code: "", name: "", description: "" }}
      >
        <div className="business-flow-editor-meta">
          <Form.Item
            name="name"
            label={ui("流程名称", "Flow name")}
            rules={[
              { required: true, message: "请填写流程名称" },
              { max: 120 },
            ]}
            style={{ flex: 1 }}
          >
            <Input
              maxLength={120}
              disabled={Boolean(flow)}
              placeholder="例如：岩性—构造—蚀变综合推理"
            />
          </Form.Item>
          <Form.Item
            name="code"
            label={ui("流程编码", "Flow code")}
            rules={[
              { required: true, message: "请填写流程编码" },
              {
                pattern: /^[a-z][a-z0-9_-]{1,79}$/,
                message: "2–80位，以小写字母开头",
              },
            ]}
            style={{ width: 230 }}
          >
            <Input
              maxLength={80}
              disabled={Boolean(flow)}
              placeholder="geology_reasoning"
            />
          </Form.Item>
        </div>
        <Form.Item
          name="description"
          label={ui("用途说明", "Purpose")}
          rules={[{ max: 3000 }]}
        >
          <Input.TextArea
            rows={2}
            maxLength={3000}
            disabled={Boolean(flow)}
            placeholder="这项流程解决什么问题，适合哪些资料。"
          />
        </Form.Item>
      </Form>
      <details className="flow-input-policy" style={{ marginBottom: 16 }}>
        <summary>{ui("资料衔接策略", "Input preparation policy")}</summary>
        <div
          style={{ display: "flex", gap: 20, flexWrap: "wrap", paddingTop: 12 }}
        >
          <label>
            <Switch
              size="small"
              checked={spec.inputPreparation?.allowScripts !== false}
              onChange={(allowScripts) =>
                setSpec((old) => ({
                  ...old,
                  inputPreparation: { ...old.inputPreparation, allowScripts },
                }))
              }
            />{" "}
            {ui(
              "允许智能体编写衔接脚本",
              "Allow agent-written preparation scripts",
            )}
          </label>
          <label>
            <Switch
              size="small"
              checked={
                spec.inputPreparation?.reviewScripts ??
                spec.nodes.some((node) => node.review.ai)
              }
              onChange={(reviewScripts) =>
                setSpec((old) => ({
                  ...old,
                  inputPreparation: { ...old.inputPreparation, reviewScripts },
                }))
              }
            />{" "}
            {ui("独立审核衔接脚本", "Independently review preparation scripts")}
          </label>
          <label>
            {ui("最多返修", "Repair limit")}{" "}
            <InputNumber
              size="small"
              min={0}
              max={2}
              value={spec.inputPreparation?.maxRepairs ?? 2}
              onChange={(value) =>
                setSpec((old) => ({
                  ...old,
                  inputPreparation: {
                    ...old.inputPreparation,
                    maxRepairs: value ?? 2,
                  },
                }))
              }
            />
          </label>
        </div>
      </details>
      {managedSkeleton && (
        <Alert
          type="info"
          showIcon
          title={ui(
            "可在处置建议和报告节点配置结果审核。",
            "Configure result review for recommendations and reports.",
          )}
          style={{ marginBottom: 16 }}
        />
      )}
      <div className="business-flow-section-heading">
        <h3>{ui("输入资料规范", "Input requirements")}</h3>
        {!managedSkeleton && (
          <Button
            size="small"
            icon={<PlusOutlined />}
            disabled={spec.inputRequirements.length >= 30}
            onClick={() =>
              setSpec((old) => ({
                ...old,
                inputRequirements: [
                  ...old.inputRequirements,
                  {
                    key: nextKey(
                      "input",
                      old.inputRequirements.map((input) => input.key),
                    ),
                    label: "",
                    description: "",
                    dataTypes: ["table"],
                    required: true,
                    requiredFields: [],
                  },
                ],
              }))
            }
          >
            {ui("添加资料角色", "Add input role")}
          </Button>
        )}
      </div>
      <div className="business-flow-editor-rows">
        {spec.inputRequirements.map((input, index) => (
          <div
            className="business-flow-editor-node"
            key={rowKey("input", input.key)}
          >
            <div className="business-flow-editor-node-grid">
              <label className="business-flow-editor-field">
                {ui("角色名称", "Role name")}
                <Input
                  value={input.label}
                  disabled={managedSkeleton}
                  onChange={(event) =>
                    setSpec((old) => ({
                      ...old,
                      inputRequirements: old.inputRequirements.map((row, i) =>
                        i === index
                          ? { ...row, label: event.target.value }
                          : row,
                      ),
                    }))
                  }
                  placeholder="例如：岩性识别成果"
                />
              </label>
              <label className="business-flow-editor-field">
                {ui("角色编码", "Role code")}
                <Input
                  value={input.key}
                  disabled={managedSkeleton}
                  onChange={(event) => {
                    renameKey("input", input.key, event.target.value);
                    setSpec((old) => ({
                      ...old,
                      inputRequirements: old.inputRequirements.map((row, i) =>
                        i === index ? { ...row, key: event.target.value } : row,
                      ),
                      nodes: old.nodes.map((node) => ({
                        ...node,
                        dataRoles: node.dataRoles.map((role) =>
                          role === input.key ? event.target.value : role,
                        ),
                      })),
                    }));
                  }}
                />
              </label>
              <label className="business-flow-editor-field">
                {ui("允许的数据类型", "Accepted data types")}
                <Select
                  mode="multiple"
                  value={input.dataTypes}
                  options={formats}
                  disabled={managedSkeleton}
                  onChange={(dataTypes) =>
                    setSpec((old) => ({
                      ...old,
                      inputRequirements: old.inputRequirements.map((row, i) =>
                        i === index ? { ...row, dataTypes } : row,
                      ),
                    }))
                  }
                />
              </label>
              <label className="business-flow-editor-field">
                {ui("需要的字段", "Required fields")}
                <Select
                  mode="tags"
                  value={input.requiredFields}
                  disabled={managedSkeleton}
                  placeholder="输入字段名后回车，可留空"
                  onChange={(requiredFields) =>
                    setSpec((old) => ({
                      ...old,
                      inputRequirements: old.inputRequirements.map((row, i) =>
                        i === index ? { ...row, requiredFields } : row,
                      ),
                    }))
                  }
                />
              </label>
              <label className="business-flow-editor-field full">
                {ui("目标数据语义（可选）", "Target data semantics (optional)")}
                <Input
                  value={input.semanticType ?? ""}
                  maxLength={100}
                  disabled={managedSkeleton}
                  placeholder="例如 class_mask_stack_v1 或 raster_band_statistics_v1"
                  onChange={(event) =>
                    setSpec((old) => ({
                      ...old,
                      inputRequirements: old.inputRequirements.map((row, i) =>
                        i === index
                          ? {
                              ...row,
                              semanticType: event.target.value || undefined,
                            }
                          : row,
                      ),
                    }))
                  }
                />
              </label>
              <label className="business-flow-editor-field">
                {ui("允许多份来源", "Allow multiple sources")}
                <Switch
                  checked={input.multiple ?? false}
                  disabled={managedSkeleton}
                  onChange={(multiple) =>
                    setSpec((old) => ({
                      ...old,
                      inputRequirements: old.inputRequirements.map((row, i) =>
                        i === index ? { ...row, multiple } : row,
                      ),
                    }))
                  }
                />
              </label>
              <label className="business-flow-editor-field full">
                {ui("资料说明", "Description")}
                <Input
                  value={input.description}
                  disabled={managedSkeleton}
                  onChange={(event) =>
                    setSpec((old) => ({
                      ...old,
                      inputRequirements: old.inputRequirements.map((row, i) =>
                        i === index
                          ? { ...row, description: event.target.value }
                          : row,
                      ),
                    }))
                  }
                />
              </label>
            </div>
            <div
              className="business-flow-editor-node-head"
              style={{ marginTop: 12, marginBottom: 0 }}
            >
              <Checkbox
                checked={input.required}
                disabled={managedSkeleton}
                onChange={(event) =>
                  setSpec((old) => ({
                    ...old,
                    inputRequirements: old.inputRequirements.map((row, i) =>
                      i === index
                        ? { ...row, required: event.target.checked }
                        : row,
                    ),
                  }))
                }
              >
                {ui("开始前必须提供", "Required before execution")}
              </Checkbox>
              {!managedSkeleton && (
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  aria-label={`删除资料角色 ${input.label || input.key}`}
                  onClick={() =>
                    setSpec((old) => ({
                      ...old,
                      inputRequirements: old.inputRequirements.filter(
                        (_, i) => i !== index,
                      ),
                      nodes: old.nodes.map((node) => ({
                        ...node,
                        dataRoles: node.dataRoles.filter(
                          (role) => role !== input.key,
                        ),
                      })),
                    }))
                  }
                />
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="business-flow-section-heading">
        <h3>{ui("流程节点", "Flow nodes")}</h3>
        {!managedSkeleton && (
          <Button
            size="small"
            icon={<PlusOutlined />}
            disabled={spec.nodes.length >= 32}
            onClick={() =>
              setSpec((old) => ({
                ...old,
                nodes: [
                  ...old.nodes,
                  {
                    id: nextKey(
                      "node",
                      old.nodes.map((node) => node.id),
                    ),
                    title: "",
                    description: "",
                    instruction: "",
                    kind: "agent",
                    dependsOn: old.nodes.length
                      ? [old.nodes[old.nodes.length - 1]!.id]
                      : [],
                    dataRoles: [],
                    review: { ai: false, human: false, maxRevisions: 0 },
                  },
                ],
              }))
            }
          >
            {ui("添加节点", "Add node")}
          </Button>
        )}
      </div>
      {algorithmError && (
        <Alert
          type="warning"
          showIcon
          title={algorithmError}
          style={{ marginBottom: 12 }}
        />
      )}
      <div className="business-flow-editor-rows">
        {spec.nodes.map((node) => (
          <div
            className="business-flow-editor-node"
            key={rowKey("node", node.id)}
          >
            <div className="business-flow-editor-node-head">
              <span>{node.title || ui("新节点", "New node")}</span>
              {!managedSkeleton && (
                <Button
                  type="text"
                  danger
                  size="small"
                  icon={<DeleteOutlined />}
                  aria-label={`删除节点 ${node.title || node.id}`}
                  onClick={() =>
                    setSpec((old) => ({
                      ...old,
                      nodes: old.nodes
                        .filter((row) => row.id !== node.id)
                        .map((row) => ({
                          ...row,
                          dependsOn: row.dependsOn.filter(
                            (id) => id !== node.id,
                          ),
                        })),
                    }))
                  }
                />
              )}
            </div>
            <div className="business-flow-editor-node-grid">
              <label className="business-flow-editor-field">
                {ui("节点名称", "Node title")}
                <Input
                  value={node.title}
                  maxLength={120}
                  onChange={(event) =>
                    updateNode(node.id, { title: event.target.value })
                  }
                />
              </label>
              <label className="business-flow-editor-field">
                {ui("节点编码", "Node code")}
                <Input
                  value={node.id}
                  disabled={managedSkeleton}
                  onChange={(event) => renameNode(node.id, event.target.value)}
                />
              </label>
              <label className="business-flow-editor-field">
                {ui("节点职责", "Node role")}
                <Select
                  value={node.kind}
                  disabled={managedSkeleton}
                  options={[
                    { value: "agent", label: "智能体分析" },
                    { value: "operator", label: "调用已发布算子" },
                    { value: "human", label: "人工决定" },
                    { value: "result", label: "整理交付成果" },
                  ]}
                  onChange={(kind) =>
                    updateNode(node.id, {
                      kind,
                      review:
                        kind === "human"
                          ? { ai: false, human: true, maxRevisions: 0 }
                          : node.review,
                    })
                  }
                />
              </label>
              <label className="business-flow-editor-field">
                {ui("前置节点", "Dependencies")}
                <Select
                  mode="multiple"
                  value={node.dependsOn}
                  disabled={managedSkeleton}
                  options={spec.nodes
                    .filter((row) => row.id !== node.id)
                    .map((row) => ({
                      value: row.id,
                      label: row.title || row.id,
                    }))}
                  onChange={(dependsOn) => updateNode(node.id, { dependsOn })}
                />
              </label>
              <label className="business-flow-editor-field full">
                {ui("本节点使用的资料", "Input roles for this node")}
                <Select
                  mode="multiple"
                  value={node.dataRoles}
                  disabled={managedSkeleton}
                  options={spec.inputRequirements.map((input) => ({
                    value: input.key,
                    label: input.label || input.key,
                  }))}
                  onChange={(dataRoles) => updateNode(node.id, { dataRoles })}
                />
              </label>
              {node.kind === "operator" && !managedSkeleton && (
                <label className="business-flow-editor-field full">
                  {ui("已发布算子", "Published operator")}
                  <Select
                    value={node.algorithmVersionId ?? undefined}
                    showSearch
                    optionFilterProp="label"
                    loading={algorithmLoading}
                    disabled={managedSkeleton}
                    placeholder="选择计算中心已发布的版本"
                    options={algorithms
                      .filter((item) => item.enabled)
                      .flatMap((item) =>
                        item.versions
                          .filter((value) => value.status === "published")
                          .map((value) => ({
                            value: value.id,
                            label: `${item.name} · ${value.version}`,
                          })),
                      )}
                    onChange={(algorithmVersionId) =>
                      updateNode(node.id, { algorithmVersionId })
                    }
                  />
                </label>
              )}
              {node.kind === "operator" && !managedSkeleton && (
                <details className="business-flow-editor-advanced full">
                  <summary>
                    {ui(
                      "固定算法参数（可选）",
                      "Fixed operator parameters (optional)",
                    )}
                  </summary>
                  <Input.TextArea
                    rows={3}
                    value={
                      parameterDrafts[node.id] ??
                      JSON.stringify(node.parameters ?? {}, null, 2)
                    }
                    aria-label={`${node.title || node.id}：固定算法参数`}
                    onChange={(event) =>
                      setParameterDrafts((old) => ({
                        ...old,
                        [node.id]: event.target.value,
                      }))
                    }
                    placeholder="{}"
                  />
                </details>
              )}
              {node.kind === "operator" && !managedSkeleton && (
                <details className="business-flow-editor-advanced full">
                  <summary>
                    {ui(
                      "算子输入来源（资料角色或上游输出）",
                      "Operator inputs (roles or previous outputs)",
                    )}
                  </summary>
                  <p className="business-flow-editor-intro">
                    {ui(
                      '按算子输入键绑定，例如 {"image":{"role":"source"}}；复用上游结果可写 {"image":{"nodeId":"previous","outputKey":"result"}}。只允许本流程声明的资料及前置算子的真实输出。',
                      "Bind manifest inputs by role or by a previous operator’s output. Only declared data and real upstream outputs are allowed.",
                    )}
                  </p>
                  <Input.TextArea
                    rows={4}
                    value={
                      bindingDrafts[node.id] ??
                      JSON.stringify(node.inputBindings ?? {}, null, 2)
                    }
                    aria-label={`${node.title || node.id}：算子输入来源`}
                    onChange={(event) =>
                      setBindingDrafts((old) => ({
                        ...old,
                        [node.id]: event.target.value,
                      }))
                    }
                    placeholder="{}"
                  />
                </details>
              )}
              <label className="business-flow-editor-field full">
                {ui("节点说明", "Node description")}
                <Input
                  value={node.description}
                  onChange={(event) =>
                    updateNode(node.id, { description: event.target.value })
                  }
                />
              </label>
              <label className="business-flow-editor-field full">
                {ui(
                  "处理要求与通过依据",
                  "Instructions and acceptance criteria",
                )}
                <Input.TextArea
                  value={node.instruction}
                  disabled={managedSkeleton}
                  rows={2}
                  maxLength={5000}
                  onChange={(event) =>
                    updateNode(node.id, { instruction: event.target.value })
                  }
                  placeholder="说明应完成的工作，以及审核应依据哪些事实。"
                />
              </label>
            </div>
            <div className="business-flow-editor-guard-row">
              <label>
                <Switch
                  size="small"
                  checked={node.review.ai}
                  aria-label={`${node.title || node.id}：独立审核`}
                  disabled={
                    managedSkeleton && !["apply", "finish"].includes(node.id)
                  }
                  onChange={(ai) =>
                    updateNode(node.id, {
                      review: {
                        ...node.review,
                        ai,
                      },
                    })
                  }
                />
                {ui("独立审核", "Independent review")}
              </label>
              <label>
                <Switch
                  size="small"
                  checked={node.review.human || node.kind === "human"}
                  aria-label={`${node.title || node.id}：必须由人决定`}
                  disabled={node.kind === "human" || managedSkeleton}
                  onChange={(human) =>
                    updateNode(node.id, { review: { ...node.review, human } })
                  }
                />
                {ui("必须由人决定", "Human decision required")}
              </label>
              {(node.review.ai ||
                node.review.human ||
                node.kind === "human") && (
                <label>
                  {ui("最多返修", "Revision limit")}
                  <InputNumber
                    size="small"
                    min={0}
                    max={3}
                    value={node.review.maxRevisions}
                    onChange={(maxRevisions) =>
                      updateNode(node.id, {
                        review: {
                          ...node.review,
                          maxRevisions: maxRevisions ?? 0,
                        },
                      })
                    }
                    style={{ width: 58 }}
                  />
                  {ui("次", "times")}
                </label>
              )}
            </div>
          </div>
        ))}
      </div>
      <label className="business-flow-editor-field">
        {ui("交付要求", "Expected deliverables")}
        <Select
          mode="tags"
          value={spec.outputRequirements}
          onChange={(outputRequirements) =>
            setSpec((old) => ({ ...old, outputRequirements }))
          }
          placeholder="输入成果要求后回车"
        />
      </label>
      <details className="business-flow-editor-advanced">
        <summary>{ui("查看完整流程定义", "View full flow definition")}</summary>
        <Input.TextArea
          readOnly
          value={JSON.stringify(spec, null, 2)}
          rows={9}
          aria-label={ui("完整流程定义", "Full flow definition")}
        />
      </details>
    </Modal>
  );
}
