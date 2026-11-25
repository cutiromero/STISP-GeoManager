import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Select,
  Switch,
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import type {
  BusinessFlowDefinition,
  BusinessFlowInputBinding,
  BusinessFlowNode,
  BusinessFlowNodeContract,
  BusinessFlowSpec,
  BusinessFlowVersion,
  ComputeAlgorithm,
} from "../api/generated/types.gen";
import { computeApi } from "../api/compute";
import { useComputeText } from "../compute/ui";
import { createUuid } from "../utils/uuid";
import BusinessFlowGraph, { businessFlowLevels } from "./BusinessFlowGraph";

export function newBusinessFlowSpec(): BusinessFlowSpec {
  return {
    schemaVersion: 2,
    adapter: "research_flow",
    skill: {
      title: "科研目的与判断依据",
      instructions: "",
      nodeInstructions: {},
      knowledgeQuestions: [],
    },
    inputRequirements: [],
    nodes: [
      {
        id: "research",
        title: "分析项目资料",
        description: "",
        kind: "agent",
        dependsOn: [],
        dataRoles: [],
        instruction: "",
        review: { ai: false, human: false, maxRevisions: 0 },
      },
      {
        id: "deliver",
        title: "整理科研成果",
        description: "",
        kind: "result",
        dependsOn: ["research"],
        dataRoles: [],
        instruction: "",
        review: { ai: false, human: false, maxRevisions: 0 },
      },
    ],
    outputRequirements: [],
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
const calculationTools: NonNullable<BusinessFlowNodeContract["tools"]> = [
  "operator_catalog",
  "preflight_operator",
  "run_operator",
];
const distinctLines = (lines: string[]) => [
  ...new Set(lines.map((line) => line.trim()).filter(Boolean)),
];
export default function BusinessFlowEditor({
  open,
  flow,
  version,
  sourceName,
  onClose,
  onSave,
}: {
  open: boolean;
  flow?: BusinessFlowDefinition;
  version?: BusinessFlowVersion | null;
  sourceName?: string;
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
  const [panel, setPanel] = useState<"nodes" | "purpose" | "inputs">("nodes");
  const [selectedId, setSelectedId] = useState<string | undefined>("research");
  const node = spec.nodes.find((node) => node.id === selectedId);
  const newNodeLabel = ui("新节点", "New node");
  const graphNodes = useMemo(
    () =>
      spec.nodes.map((node) =>
        node.title ? node : { ...node, title: newNodeLabel },
      ),
    [spec.nodes, newNodeLabel],
  );
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
  const concise = spec.schemaVersion === 2;
  const taskExecutor = concise || spec.executionMode === "main_agent";
  useEffect(() => {
    if (!open) return;
    const initial = version
      ? structuredClone(version.definition)
      : newBusinessFlowSpec();
    if (!flow && initial.adapter === "research_flow" && initial.schemaVersion === 1) {
      initial.executionMode = "main_agent";
      initial.skill ??= { title: "科研目的与判断依据", instructions: "" };
    }
    setSpec(initial);
    setPanel("nodes");
    setSelectedId(initial.nodes[0]?.id);
    form.setFieldsValue({
      code: flow?.code ?? "",
      name:
        flow?.name ?? (sourceName ? `${sourceName} · 副本`.slice(0, 120) : ""),
      description: flow?.description ?? "",
    });
    setError("");
    setParameterDrafts({});
    setBindingDrafts({});
    rowKeys.current.clear();
  }, [open, flow?.id, version?.id, sourceName, form]);
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
  const updateDependencies = (id: string, dependsOn: string[]) => {
    try {
      businessFlowLevels(
        spec.nodes.map((node) =>
          node.id === id ? { ...node, dependsOn } : node,
        ),
      );
      updateNode(id, { dependsOn });
      setError("");
    } catch {
      setError("这条连接会形成循环，请选择更早完成的节点。");
    }
  };
  const updateNodeGuidance = (id: string, value: string) => {
    setSpec((old) => {
      if (!old.skill) return old;
      const notes = { ...old.skill.nodeInstructions };
      if (value.trim()) notes[id] = value;
      else delete notes[id];
      return { ...old, skill: { ...old.skill, nodeInstructions: notes } };
    });
  };
  const setAdaptiveCalculation = (node: BusinessFlowNode, enabled: boolean) => {
    const contract: BusinessFlowNodeContract = node.contract ?? {
      goal: node.description,
      acceptance: [],
      requiredOutputs: [{ name: "analysis", semanticType: "analysis" }],
      tools: ["read_evidence", "read_task_record", "ask_user", "finish_node"],
    };
    const tools = contract.tools ?? ["read_evidence", "read_task_record", "ask_user", "finish_node"];
    updateNode(node.id, {
      contract: {
        ...contract,
        tools: enabled
          ? [...new Set([...tools, ...calculationTools])]
          : tools.filter(
              (tool) =>
                !calculationTools.includes(tool) && tool !== "prepare_input",
            ),
        maxOperatorCalls: enabled ? contract.maxOperatorCalls || 6 : 0,
      },
    });
  };
  const renameNode = (id: string, next: string) => {
    if (next === id) return;
    if (spec.nodes.some((node) => node.id === next)) {
      setError("该节点编码已被占用。");
      return;
    }
    setError("");
    renameKey("node", id, next);
    setSelectedId(next);
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
      ...(old.skill?.nodeInstructions
        ? {
            skill: {
              ...old.skill,
              nodeInstructions: Object.fromEntries(
                Object.entries(old.skill.nodeInstructions).map(
                  ([key, note]) => [key === id ? next : key, note],
                ),
              ),
            },
          }
        : {}),
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
  const addNode = () => {
    const id = nextKey(
      "node",
      spec.nodes.map((node) => node.id),
    );
    setSpec((old) => ({
      ...old,
      nodes: [
        ...old.nodes,
        {
          id,
          title: "",
          description: "",
          instruction: "",
          kind: "agent",
          dependsOn: node ? [node.id] : [],
          dataRoles: [],
          review: { ai: false, human: false, maxRevisions: 0 },
        },
      ],
    }));
    setSelectedId(id);
  };
  const removeNode = (id: string) => {
    if (
      spec.nodes.some((candidate) => {
        if (candidate.id === id || candidate.kind !== "operator") return false;
        let bindings = candidate.inputBindings;
        if (bindingDrafts[candidate.id] !== undefined) {
          try {
            bindings = JSON.parse(bindingDrafts[candidate.id]!);
          } catch {
            return true;
          }
        }
        return Object.values(bindings ?? {}).some(
          (binding) =>
            binding &&
            typeof binding === "object" &&
            "nodeId" in binding &&
            binding.nodeId === id,
        );
      })
    ) {
      setError("其他节点仍引用该节点的成果，请先调整算子输入来源。");
      return;
    }
    const remaining = spec.nodes.filter((node) => node.id !== id);
    setSelectedId(node?.dependsOn[0] ?? remaining[0]?.id);
    setError("");
    for (const setDrafts of [setBindingDrafts, setParameterDrafts]) {
      setDrafts((old) => {
        const next = { ...old };
        delete next[id];
        return next;
      });
    }
    setSpec((old) => ({
      ...old,
      ...(old.skill?.nodeInstructions
        ? {
            skill: {
              ...old.skill,
              nodeInstructions: Object.fromEntries(
                Object.entries(old.skill.nodeInstructions).filter(
                  ([key]) => key !== id,
                ),
              ),
            },
          }
        : {}),
      nodes: remaining.map((node) => ({
        ...node,
        dependsOn: node.dependsOn.filter((parent) => parent !== id),
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
      const needsResearchPlan =
        spec.executionMode === "main_agent" && !managedSkeleton;
      const outputRequirements = distinctLines(spec.outputRequirements);
      const knowledgeQuestions = distinctLines(
        spec.skill?.knowledgeQuestions ?? [],
      );
      if (
        knowledgeQuestions.length > 3 ||
        knowledgeQuestions.some((question) => question.length > 160)
      ) {
        setPanel("purpose");
        throw new Error("待查证的知识问题最多三项，每项最多160字。");
      }
      if (needsResearchPlan && !spec.skill?.instructions.trim()) {
        setPanel("purpose");
        throw new Error("请写明流程要回答的科研问题，以及判断结果的依据。");
      }
      if (needsResearchPlan && !outputRequirements.length) {
        setPanel("inputs");
        throw new Error("请至少填写一项预期交付成果。");
      }
      if (!spec.nodes.length) throw new Error("请至少登记一个流程节点。");
      const incomplete = spec.nodes.find(
        (node) =>
          !node.title.trim() ||
          (!concise && !managedSkeleton && !node.instruction.trim()) ||
          (needsResearchPlan && !node.description.trim()) ||
          (!concise && node.contract && !distinctLines(node.contract.acceptance ?? []).length) ||
          !/^([a-z][a-z0-9_-]{1,63})$/.test(node.id),
      );
      if (incomplete) {
        setPanel("nodes");
        setSelectedId(incomplete.id);
        throw new Error(
          `请补全「${incomplete.title || incomplete.id}」的节点目的、判断与交付要求，并核对名称、编码及验收条件。`,
        );
      }
      businessFlowLevels(spec.nodes);
      const definition = {
        ...spec,
        ...(spec.skill && spec.skill.knowledgeQuestions !== undefined
          ? { skill: { ...spec.skill, knowledgeQuestions } }
          : {}),
        outputRequirements,
        nodes: spec.nodes.map((node) => {
          const next: BusinessFlowNode = {
            ...node,
            ...(node.contract
              ? {
                  contract: {
                    ...node.contract,
                    acceptance: distinctLines(node.contract.acceptance ?? []),
                  },
                }
              : {}),
          };
          if (node.kind !== "operator" || managedSkeleton) return next;
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
      if (concise && !definition.skill?.instructions.trim()) {
        if (!knowledgeQuestions.length) delete definition.skill;
        else if (definition.skill) {
          definition.skill.instructions = metadata.description.trim() || metadata.name.trim();
        }
      }
      await onSave(
        {
          ...metadata,
          description:
            metadata.description.trim() ||
            spec.skill?.instructions.trim() ||
            "",
        },
        definition,
      );
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
          ? ui(
              "编辑业务流 · 发布新版本",
              "Edit workflow · publish a new version",
            )
          : ui("新建业务流", "New business flow")
      }
      onCancel={() => {
        if (!busy) onClose();
      }}
      onOk={() => void save()}
      confirmLoading={busy}
      okText={ui("保存并发布", "Save and publish")}
      cancelText={ui("取消", "Cancel")}
      width={1200}
      className="business-flow-modal business-flow-authoring"
      destroyOnHidden
    >
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
            <Input maxLength={120} placeholder="例如：岩性—构造—蚀变综合推理" />
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
        <Segmented
          aria-label={ui("编辑内容", "Editor section")}
          value={panel}
          onChange={setPanel}
          options={[
            { value: "nodes", label: ui("节点设计", "Nodes") },
            { value: "purpose", label: ui("科研目的", "Research purpose") },
            {
              value: "inputs",
              label: ui("资料与交付", "Inputs and deliverables"),
            },
          ]}
        />
        <div
          className="business-flow-authoring-panel"
          hidden={panel !== "purpose"}
        >
          {taskExecutor && (
            <Form.Item
              label={ui("科研目的与判断依据", "Research purpose and evidence")}
              required={!managedSkeleton && !concise}
            >
              <Input.TextArea
                aria-label={ui(
                  "科研目的与判断依据",
                  "Research purpose and evidence",
                )}
                value={spec.skill?.instructions ?? ""}
                rows={3}
                maxLength={600}
                placeholder={ui(
                  "例如：识别海岸带哪些地段可能发生入侵扩张，为外业复查排序。结合三季物候和实际有效范围判断，参考项目中的物候识别规则。",
                  "State the scientific question, intended use, evidence or standards, and decisions the agent can adapt.",
                )}
                onChange={(event) => {
                  const instructions = event.target.value;
                  setSpec((old) => ({
                    ...old,
                    skill: {
                      ...old.skill,
                      title: old.skill?.title ?? "科研目的与判断依据",
                      instructions,
                    },
                  }));
                }}
              />
            </Form.Item>
          )}
          {taskExecutor && (
            <Form.Item label={ui("待查证的知识问题", "Knowledge questions")}>
              <Input.TextArea
                aria-label={ui("待查证的知识问题", "Knowledge questions")}
                value={spec.skill?.knowledgeQuestions?.join("\n") ?? ""}
                rows={3}
                maxLength={482}
                placeholder={ui(
                  "每行一项，最多三项。例如：使用 FCCI 做月度比较前，如何识别重复观测和缺测？",
                  "Up to three questions, one per line. Include the product or standard and the decision it informs.",
                )}
                onChange={(event) => {
                  const questions = event.target.value.split("\n");
                  setSpec((old) => ({
                    ...old,
                    skill: {
                      title: "科研目的与判断依据",
                      instructions: "",
                      ...old.skill,
                      knowledgeQuestions: questions,
                    },
                  }));
                }}
              />
            </Form.Item>
          )}
          <Form.Item
            name="description"
            label={ui("目录摘要（可选）", "Catalog summary (optional)")}
            rules={[{ max: 3000 }]}
          >
            <Input.TextArea
              rows={2}
              maxLength={3000}
              placeholder="默认沿用科研目的。可另写供目录浏览的简短摘要。"
            />
          </Form.Item>
        </div>
      </Form>
      <section
        className="business-flow-authoring-panel"
        hidden={panel !== "nodes"}
      >
        <div className="business-flow-section-heading">
          <h3>{ui("流程节点", "Flow nodes")}</h3>
          {!managedSkeleton && (
            <Button
              size="small"
              icon={<PlusOutlined />}
              disabled={spec.nodes.length >= 32}
              aria-label={ui("添加节点", "Add node")}
              onClick={addNode}
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
        <div className="business-flow-authoring-grid">
          <div className="business-flow-authoring-graph">
            {spec.nodes.length ? (
              <BusinessFlowGraph
                nodes={graphNodes}
                selectedNode={selectedId}
                onSelectNode={(node) => setSelectedId(node.id)}
                compact
              />
            ) : (
              <p>
                {ui("添加一个节点，开始设计流程。", "Add a node to begin.")}
              </p>
            )}
            <Select
              aria-label={ui("定位编辑节点", "Find node to edit")}
              placeholder={ui("定位节点", "Find a node")}
              value={selectedId}
              showSearch={{ optionFilterProp: "label" }}
              options={spec.nodes.map((node) => ({
                value: node.id,
                label: node.title || node.id,
              }))}
              onChange={setSelectedId}
            />
          </div>
          {node && (
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
                    onClick={() => removeNode(node.id)}
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
                <label className="business-flow-editor-field full">
                  {ui("节点目的", "Node purpose")}
                  <Input
                    value={node.description}
                    maxLength={2000}
                    placeholder="它为哪个科研判断提供证据？例如：确定哪些像元确实记录了本期火烧。"
                    onChange={(event) => {
                      const description = event.target.value;
                      updateNode(node.id, {
                        description,
                        ...(node.contract
                          ? {
                              contract: {
                                ...node.contract,
                                goal: description,
                              },
                            }
                          : {}),
                      });
                    }}
                  />
                </label>
                <label className="business-flow-editor-field full">
                  {ui("判断与交付", "Decisions and deliverables")}
                  <Input.TextArea
                    value={node.instruction}
                    disabled={managedSkeleton}
                    rows={2}
                    maxLength={5000}
                    onChange={(event) =>
                      updateNode(node.id, { instruction: event.target.value })
                    }
                    placeholder="写明使用哪些证据，什么成果算完成，遇到差异时如何判断。"
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
                        ...(kind !== "operator"
                          ? {
                              algorithmVersionId: undefined,
                              inputBindings: undefined,
                              parameters: undefined,
                            }
                          : {}),
                        ...(kind !== node.kind ? { contract: undefined } : {}),
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
                    onChange={(dependsOn) =>
                      updateDependencies(node.id, dependsOn)
                    }
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
                {node.kind === "agent" &&
                  !managedSkeleton &&
                  taskExecutor &&
                  (node.contract?.requiredOutputs.every(
                    (output) => output.semanticType === "analysis",
                  ) ??
                    true) && (
                    <label className="business-flow-editor-field full">
                      <Checkbox
                        checked={
                          node.contract?.tools?.includes("run_operator") ?? false
                        }
                        onChange={(event) =>
                          setAdaptiveCalculation(node, event.target.checked)
                        }
                      >
                        {ui(
                          "允许按资料选择已发布算子",
                          "Allow choosing a published operator",
                        )}
                      </Checkbox>
                    </label>
                  )}
                {node.contract && !managedSkeleton && (
                  <label className="business-flow-editor-field full">
                    {ui("验收条件", "Acceptance criteria")}
                    <Input.TextArea
                      aria-label={ui("验收条件", "Acceptance criteria")}
                      rows={2}
                      value={(node.contract.acceptance ?? []).join("\n")}
                      onChange={(event) =>
                        updateNode(node.id, {
                          contract: {
                            ...node.contract!,
                            acceptance: event.target.value.split("\n"),
                          },
                        })
                      }
                      placeholder="每行一条，例如：异常变化可定位到具体年份和图斑"
                    />
                  </label>
                )}
                {taskExecutor && spec.skill && (
                  <details className="business-flow-editor-advanced full">
                    <summary>
                      {ui("节点专项补充", "Additional node guidance")}
                    </summary>
                    <Input.TextArea
                      aria-label={ui(
                        "节点专项补充",
                        "Additional node guidance",
                      )}
                      rows={2}
                      maxLength={300}
                      value={spec.skill.nodeInstructions?.[node.id] ?? ""}
                      onChange={(event) =>
                        updateNodeGuidance(node.id, event.target.value)
                      }
                      placeholder="例如：同月重复的观测记录共用一个月尺度统计口径。"
                    />
                  </details>
                )}
                <details className="business-flow-editor-advanced full">
                  <summary>{ui("节点标识", "Node identity")}</summary>
                  <label className="business-flow-editor-field">
                    {ui("节点编码", "Node code")}
                    <Input
                      value={node.id}
                      disabled={managedSkeleton}
                      onChange={(event) =>
                        renameNode(node.id, event.target.value)
                      }
                    />
                  </label>
                </details>
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
                      updateNode(node.id, {
                        review: { ...node.review, human },
                      })
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
          )}
        </div>
      </section>
      <div
        className="business-flow-authoring-panel"
        hidden={panel !== "inputs"}
      >
        <details className="flow-input-policy" style={{ marginBottom: 16 }}>
          <summary>{ui("资料衔接策略", "Input preparation policy")}</summary>
          <div
            style={{
              display: "flex",
              gap: 20,
              flexWrap: "wrap",
              paddingTop: 12,
            }}
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
                    inputPreparation: {
                      ...old.inputPreparation,
                      reviewScripts,
                    },
                  }))
                }
              />{" "}
              {ui(
                "独立审核衔接脚本",
                "Independently review preparation scripts",
              )}
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
                          i === index
                            ? { ...row, key: event.target.value }
                            : row,
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
                  {ui(
                    "目标数据语义（可选）",
                    "Target data semantics (optional)",
                  )}
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
        <label className="business-flow-editor-field">
          {ui("交付要求", "Expected deliverables")}
          <Input.TextArea
            aria-label={ui("交付要求", "Expected deliverables")}
            rows={3}
            value={spec.outputRequirements.join("\n")}
            onChange={(event) =>
              setSpec((old) => ({
                ...old,
                outputRequirements: event.target.value.split("\n"),
              }))
            }
            placeholder="每行一项，例如：带图斑编号的复查清单"
          />
        </label>
        <details className="business-flow-editor-advanced">
          <summary>
            {ui("查看完整流程定义", "View full flow definition")}
          </summary>
          <Input.TextArea
            readOnly
            value={JSON.stringify(spec, null, 2)}
            rows={9}
            aria-label={ui("完整流程定义", "Full flow definition")}
          />
        </details>
      </div>
    </Modal>
  );
}
