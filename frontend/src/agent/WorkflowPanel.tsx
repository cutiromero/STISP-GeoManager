import {
  Alert,
  Button,
  Collapse,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import { useEffect, useRef, useState } from "react";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type {
  AgentWorkflow,
  AgentKnowledgeSelection,
  AgentModel,
  AgentResource,
  ComputeAlgorithm,
  ComputeCandidate,
  ComputeParameterSpec,
  KnowledgeDomainOption,
  KnowledgeDomain,
} from "../api/generated/types.gen";
import { createUuid } from "../utils/uuid";
import { useComputeText } from "../compute/ui";
import DemoWorkflowForm, {
  demoGoals,
  demoInputsReady,
  type DemoWorkflowType,
} from "./DemoWorkflowForm";
import WorkflowDecisionTimeline, {
  WorkflowEvidenceUpdate,
} from "./WorkflowDecisionTimeline";
import RunComputeTasks from "./RunComputeTasks";
import WorkflowKnowledgeReferences from "./WorkflowKnowledgeReferences";

const active = ["queued", "running", "waiting_compute", "waiting_approval"];
const labels: Record<string, string> = {
  queued: "等待处理",
  running: "准备计划",
  waiting_compute: "执行与入库",
  waiting_approval: "等待确认",
  succeeded: "已完成",
  failed: "未完成",
  cancelled: "已停止",
  interrupted: "已中断",
};

function workflowMapResourceIds(workflow: AgentWorkflow | undefined) {
  if (!workflow) return [];
  const record = (value: unknown): Record<string, unknown> =>
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  const demo = ["ecology_investigation", "geology_correction"].includes(
    workflow.workflowType,
  );
  const stages = Array.isArray(workflow.plan.stages)
    ? workflow.plan.stages
    : [];
  const results = demo
    ? stages.flatMap((stage) => {
        const outputs = record(stage).outputs;
        return Array.isArray(outputs)
          ? outputs.flatMap((value) => {
              const output = record(value);
              return ["raster", "vector"].includes(String(output.kind))
                ? [output.resourceId]
                : [];
            })
          : [];
      })
    : workflow.resultResourceIds;
  const original =
    workflow.workflowType === "geology_correction"
      ? record(workflow.plan.inputs).initial_map
      : undefined;
  const previousChange = demo
    ? record(workflow.plan.previousChange).resourceId
    : undefined;
  return [
    ...new Set(
      [original, previousChange, ...results].filter(
        (value): value is number =>
          typeof value === "number" && Number.isInteger(value) && value > 0,
      ),
    ),
  ];
}

function ParameterField({
  spec,
  value,
  candidate,
  onChange,
}: {
  spec: ComputeParameterSpec;
  value: unknown;
  candidate?: ComputeCandidate;
  onChange: (value: unknown) => void;
}) {
  if (spec.type === "boolean")
    return <Switch checked={value === true} onChange={onChange} />;
  if (["enum", "field", "band"].includes(spec.type)) {
    const values =
      spec.type === "enum"
        ? (spec.choices ?? [])
        : spec.type === "field"
          ? (candidate?.fields ?? [])
          : Array.from(
              { length: candidate?.bands ?? 0 },
              (_, index) => index + 1,
            );
    return (
      <Select
        aria-label={spec.label}
        style={{ minWidth: 180 }}
        value={value as string | number | undefined}
        onChange={onChange}
        options={values.map((v) => ({ value: v, label: String(v) }))}
      />
    );
  }
  if (["integer", "number"].includes(spec.type))
    return (
      <InputNumber
        aria-label={spec.label}
        min={spec.min}
        max={spec.max}
        precision={spec.type === "integer" ? 0 : undefined}
        value={typeof value === "number" ? value : null}
        onChange={onChange}
      />
    );
  return (
    <Input
      aria-label={spec.label}
      maxLength={2000}
      value={typeof value === "string" ? value : ""}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export default function WorkflowPanel({
  model,
  resourceIds,
  embedded = false,
  onStatusChange,
}: {
  model: string;
  resourceIds: number[];
  embedded?: boolean;
  onStatusChange?: (status: AgentWorkflow["status"] | undefined) => void;
}) {
  const ui = useComputeText();
  const [goal, setGoal] = useState("");
  const [workflowType, setWorkflowType] = useState("research_processing");
  const [selectedModel, setSelectedModel] = useState(model);
  const [models, setModels] = useState<AgentModel[]>([]);
  const [resources, setResources] = useState<AgentResource[]>([]);
  const [knowledgeDomains, setKnowledgeDomains] = useState<
    KnowledgeDomainOption[]
  >([]);
  const [knowledgeSelection, setKnowledgeSelection] =
    useState<AgentKnowledgeSelection>({ mode: "auto", domains: [] });
  const [algorithms, setAlgorithms] = useState<ComputeAlgorithm[]>([]);
  const [candidates, setCandidates] = useState<ComputeCandidate[]>([]);
  const [versionId, setVersionId] = useState<number>();
  const [inputs, setInputs] = useState<Record<string, number>>({});
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const [workflow, setWorkflow] = useState<AgentWorkflow>();
  const [history, setHistory] = useState<AgentWorkflow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [previousWorkflowId, setPreviousWorkflowId] = useState<string>();
  const mutationInFlight = useRef(false);
  const lastPreviewRequest = useRef<
    { signature: string; key: string } | undefined
  >(undefined);
  const isDemo =
    workflowType === "ecology_investigation" ||
    workflowType === "geology_correction";
  const locked = Boolean(workflow && active.includes(workflow.status));
  const version = algorithms
    .flatMap((algorithm) => algorithm.versions)
    .find((v) => v.id === versionId);
  const report = (e: unknown) => {
    setError(e instanceof Error ? e.message : "请求失败");
    if (
      typeof e === "object" &&
      e !== null &&
      "status" in e &&
      [401, 403, 404].includes(Number(e.status))
    ) {
      setWorkflow(undefined);
      setHistory([]);
      setCandidates([]);
      setResources([]);
      setPreviousWorkflowId(undefined);
    }
  };
  const restore = (next: AgentWorkflow | undefined) => {
    setPreviousWorkflowId(undefined);
    setWorkflow(next);
    if (!next) return;
    setWorkflowType(next.workflowType);
    setGoal(next.goal);
    setSelectedModel(next.model);
    setVersionId(next.algorithmVersionId ?? undefined);
    setParameters(next.parameters);
    const savedInputs = next.plan.inputs;
    setInputs(
      savedInputs &&
        typeof savedInputs === "object" &&
        !Array.isArray(savedInputs)
        ? Object.fromEntries(
            Object.entries(savedInputs).filter(
              (entry): entry is [string, number] =>
                typeof entry[1] === "number",
            ),
          )
        : {},
    );
    const selection = next.plan.knowledgeSelection;
    if (
      selection &&
      typeof selection === "object" &&
      "mode" in selection &&
      "domains" in selection &&
      ["auto", "manual", "all", "none"].includes(String(selection.mode)) &&
      Array.isArray(selection.domains)
    ) {
      setKnowledgeSelection({
        mode: selection.mode as AgentKnowledgeSelection["mode"],
        domains: selection.domains.filter((value): value is KnowledgeDomain =>
          ["remote_sensing", "pipelines", "geology", "arid_ecology"].includes(
            String(value),
          ),
        ),
      });
    } else setKnowledgeSelection({ mode: "auto", domains: [] });
  };
  useEffect(() => setSelectedModel(model), [model]);
  useEffect(() => {
    let disposed = false;
    void Promise.allSettled([agentApi.bootstrap(), agentApi.resources()]).then(
      ([bootstrap, data]) => {
        if (disposed) return;
        if (bootstrap.status === "fulfilled") {
          setModels(
            (bootstrap.value.models ?? []).filter((entry) => entry.allowAgent),
          );
          setKnowledgeDomains(bootstrap.value.knowledgeDomains ?? []);
        }
        if (data.status === "fulfilled") setResources(data.value.items ?? []);
      },
    );
    return () => {
      disposed = true;
    };
  }, []);
  useEffect(() => {
    let disposed = false;
    void Promise.all([
      computeApi.algorithms({ pageSize: 100 }),
      computeApi.inputs({ pageSize: 100 }),
      agentApi.workflows(),
    ])
      .then(([a, c, w]) => {
        if (disposed) return;
        setAlgorithms(a.items);
        setCandidates(c.items);
        setHistory(w.items);
        restore(w.items[0]);
      })
      .catch((e) => {
        if (!disposed) report(e);
      });
    return () => {
      disposed = true;
    };
  }, []);
  useEffect(() => {
    if (
      !workflow ||
      !active.includes(workflow.status) ||
      workflow.status === "waiting_approval"
    )
      return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await agentApi.workflow(workflow.id);
        if (disposed) return;
        setWorkflow(next);
        if (["queued", "running", "waiting_compute"].includes(next.status))
          timer = setTimeout(poll, document.hidden ? 5000 : 1500);
      } catch (e) {
        if (!disposed) report(e);
      }
    };
    timer = setTimeout(poll, 700);
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [workflow?.id, workflow?.status]);
  const preview = async () => {
    if (mutationInFlight.current) return;
    mutationInFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const body = {
        goal,
        model: selectedModel,
        resourceIds: [...new Set([...resourceIds, ...Object.values(inputs)])],
        workflowType,
        algorithmVersionId: isDemo ? undefined : versionId,
        inputs,
        parameters:
          workflowType === "ecology_investigation"
            ? {
                red: 1,
                nir: 2,
                decline_threshold: -0.15,
                min_coverage: 0.65,
                ...parameters,
              }
            : parameters,
        knowledgeSelection,
        ...(previousWorkflowId ? { previousWorkflowId } : {}),
        executeOperators: false,
        importResults: true,
      };
      const signature = JSON.stringify(body);
      if (lastPreviewRequest.current?.signature !== signature)
        lastPreviewRequest.current = { signature, key: createUuid() };
      const result = await agentApi.createWorkflow({
        ...body,
        idempotencyKey: lastPreviewRequest.current!.key,
      });
      lastPreviewRequest.current = undefined;
      setWorkflow(result);
      setPreviousWorkflowId(undefined);
      setHistory((old) => [result, ...old]);
    } catch (e) {
      report(e);
    } finally {
      mutationInFlight.current = false;
      setBusy(false);
    }
  };
  const action = async (confirm: boolean) => {
    if (!workflow || mutationInFlight.current) return;
    mutationInFlight.current = true;
    setBusy(true);
    setError("");
    try {
      setWorkflow(
        confirm
          ? await agentApi.confirmWorkflow(workflow.id, workflow.planHash)
          : await agentApi.cancelWorkflow(workflow.id),
      );
    } catch (e) {
      report(e);
    } finally {
      mutationInFlight.current = false;
      setBusy(false);
    }
  };
  useEffect(() => {
    onStatusChange?.(workflow?.status);
  }, [workflow?.status, onStatusChange]);
  const fields = (value: unknown) =>
    value && typeof value === "object" && !Array.isArray(value)
      ? Object.entries(value)
      : [];
  const mapResourceIds = workflowMapResourceIds(workflow);
  const content = (
    <Space orientation="vertical" style={{ width: "100%" }}>
      <Typography.Text type="secondary">
        {ui(
          "描述目标，核对数据与算法后确认执行。平台持续跟踪计算、知识检查和结果入库，离开页面后仍可恢复查看。",
          "Describe a goal, review the data and algorithm, then confirm. The platform tracks calculation, knowledge checks and import even after you leave.",
        )}
      </Typography.Text>
      <div className="agent-workflow-selectors">
        <label>
          <span>研究场景</span>
          <Select
            aria-label="研究场景"
            value={workflowType}
            disabled={locked || busy || Boolean(previousWorkflowId)}
            options={[
              { value: "research_processing", label: "通用科研计算" },
              {
                value: "ecology_investigation",
                label: "干旱区生态 · 变化与调查优先区",
              },
              {
                value: "geology_correction",
                label: "地质填图 · 检查、纠正与复核",
              },
            ]}
            onChange={(value) => {
              setWorkflowType(value);
              setInputs({});
              setParameters({});
              setVersionId(undefined);
              if (value !== "research_processing")
                setGoal(demoGoals[value as DemoWorkflowType]);
            }}
          />
        </label>
        <label>
          <span>分析模型</span>
          <Select
            aria-label="工作流分析模型"
            value={selectedModel}
            disabled={locked || busy}
            options={
              models.length
                ? models.map((entry) => ({
                    value: entry.alias,
                    label: entry.alias === "mock" ? "模拟模型" : entry.name,
                    disabled: entry.status === "offline",
                  }))
                : [
                    {
                      value: selectedModel,
                      label:
                        selectedModel === "mock" ? "模拟模型" : selectedModel,
                      disabled: false,
                    },
                  ]
            }
            onChange={setSelectedModel}
          />
        </label>
      </div>
      <Input.TextArea
        aria-label={ui("工作流目标", "Workflow goal")}
        value={goal}
        onChange={(e) => setGoal(e.target.value)}
        maxLength={12000}
        autoSize={{ minRows: 2, maxRows: 4 }}
        placeholder={ui(
          "例如：使用 NDVI 算法处理所选影像并将结果入库。",
          "Example: calculate NDVI for the selected image and import the result.",
        )}
      />
      {isDemo ? (
        <DemoWorkflowForm
          type={workflowType as DemoWorkflowType}
          candidates={candidates}
          resources={resources}
          inputs={inputs}
          parameters={parameters}
          disabled={locked || busy}
          onInputsChange={setInputs}
          onParametersChange={setParameters}
          evidenceOnly={Boolean(previousWorkflowId)}
        />
      ) : (
        <>
          <Select
            aria-label={ui("指定算法", "Select algorithm")}
            style={{ width: "100%" }}
            allowClear
            showSearch
            optionFilterProp="label"
            value={versionId}
            placeholder={ui(
              "自动按目标匹配，或指定算法与参数",
              "Match the goal automatically or choose an algorithm",
            )}
            options={algorithms.flatMap((a) =>
              a.versions
                .filter((v) => v.status === "published")
                .map((v) => ({
                  value: v.id,
                  label: `${a.name} · ${v.version}`,
                })),
            )}
            onChange={(id) => {
              setVersionId(id);
              setInputs({});
              setParameters({});
            }}
          />
          {version?.manifest.inputs.map((spec) => (
            <Space key={spec.key} wrap>
              <Typography.Text>{spec.label}</Typography.Text>
              <Select
                aria-label={spec.label}
                style={{ minWidth: 220 }}
                value={inputs[spec.key]}
                allowClear
                options={candidates
                  .filter((c) => c.kind === spec.kind)
                  .map((c) => ({ value: c.id, label: c.name }))}
                onChange={(id) =>
                  setInputs((old) => {
                    const next = { ...old };
                    if (id === undefined) delete next[spec.key];
                    else next[spec.key] = id;
                    return next;
                  })
                }
              />
            </Space>
          ))}
          {version?.manifest.parameters
            .filter(
              (spec) =>
                !spec.when ||
                (parameters[String(spec.when.key)] ??
                  version.manifest.parameters.find(
                    (p) => p.key === spec.when?.key,
                  )?.default) === spec.when.equals,
            )
            .map((spec) => (
              <Space key={spec.key} wrap>
                <Typography.Text>{spec.label}</Typography.Text>
                <ParameterField
                  spec={spec}
                  value={parameters[spec.key] ?? spec.default}
                  candidate={
                    spec.input
                      ? candidates.find(
                          (c) => c.id === inputs[spec.input ?? ""],
                        )
                      : undefined
                  }
                  onChange={(value) =>
                    setParameters((old) => ({ ...old, [spec.key]: value }))
                  }
                />
              </Space>
            ))}
        </>
      )}
      <div className="agent-workflow-selectors">
        <label>
          <span>知识依据</span>
          <Select
            aria-label="工作流知识模式"
            value={knowledgeSelection.mode}
            disabled={locked || busy}
            options={[
              { value: "auto", label: "按场景自动选择" },
              { value: "manual", label: "指定知识分区" },
              { value: "all", label: "所有可见知识" },
              { value: "none", label: "本次不使用知识" },
            ]}
            onChange={(mode: AgentKnowledgeSelection["mode"]) =>
              setKnowledgeSelection({
                mode,
                domains: mode === "manual" ? knowledgeSelection.domains : [],
              })
            }
          />
        </label>
        {knowledgeSelection.mode === "manual" && (
          <label>
            <span>知识分区</span>
            <Select
              aria-label="工作流知识分区"
              mode="multiple"
              disabled={locked || busy}
              value={knowledgeSelection.domains}
              options={knowledgeDomains.map((entry) => ({
                value: entry.id,
                label: `${entry.label}（${entry.count}）`,
              }))}
              onChange={(domains) =>
                setKnowledgeSelection({ mode: "manual", domains })
              }
            />
          </label>
        )}
      </div>
      <Button
        type="primary"
        loading={busy}
        disabled={
          !goal.trim() ||
          !selectedModel ||
          locked ||
          (knowledgeSelection.mode === "manual" &&
            !knowledgeSelection.domains.length) ||
          (isDemo &&
            !demoInputsReady(workflowType as DemoWorkflowType, inputs)) ||
          Boolean(
            previousWorkflowId &&
            inputs.context ===
              (workflow?.plan.inputs &&
              typeof workflow.plan.inputs === "object" &&
              "context" in workflow.plan.inputs
                ? workflow.plan.inputs.context
                : undefined),
          ) ||
          (workflowType === "ecology_investigation" &&
            (!parameters.early_date || !parameters.late_date))
        }
        onClick={() => void preview()}
      >
        {previousWorkflowId
          ? ui("生成更新计划", "Preview evidence update")
          : ui("生成执行计划", "Preview plan")}
      </Button>
      {previousWorkflowId && (
        <Alert
          type="info"
          title="更新这次调查的观测依据"
          description="请选择新的生态背景与观测记录。平台会结合已有变化结果更新调查建议，保留本次影像、日期和参数。"
          action={
            <Button
              size="small"
              onClick={() => setPreviousWorkflowId(undefined)}
            >
              返回普通分析
            </Button>
          }
        />
      )}
      {error && <Alert type="error" title={error} />}
      {history.length > 1 && (
        <Select
          aria-label={ui("历史工作流", "Workflow history")}
          style={{ width: "100%" }}
          value={workflow?.id}
          options={history.map((item) => ({
            value: item.id,
            label: item.goal,
          }))}
          onChange={(id) => {
            setError("");
            void agentApi.workflow(id).then(restore).catch(report);
          }}
        />
      )}
      {workflow && (
        <div className="agent-workflow-status">
          <Space wrap>
            <Tag
              color={
                workflow.status === "succeeded"
                  ? "green"
                  : workflow.status === "failed"
                    ? "red"
                    : "blue"
              }
            >
              {ui(labels[workflow.status] ?? workflow.status)}
            </Tag>
            <span>{workflow.detail}</span>
          </Space>
          {workflow.planHash && (
            <dl className="agent-plan-summary">
              <dt>{ui("算法", "Algorithm")}</dt>
              <dd>
                {workflow.plan.algorithm
                  ? String(workflow.plan.algorithm)
                  : fields(workflow.plan.algorithms).map(([key, value]) => (
                      <div key={key}>
                        {value && typeof value === "object" && "name" in value
                          ? String(value.name)
                          : key}
                      </div>
                    ))}
              </dd>
              <dt>{ui("输入数据", "Input data")}</dt>
              <dd>
                {fields(workflow.plan.inputNames).map(([key, value]) => (
                  <div key={key}>{String(value)}</div>
                ))}
              </dd>
              <dt>{ui("执行参数", "Parameters")}</dt>
              <dd>
                {fields(workflow.plan.parameters ?? workflow.parameters).map(
                  ([key, value]) => (
                    <div key={key}>
                      {key}：{String(value)}
                    </div>
                  ),
                )}
              </dd>
              <dt>{ui("知识依据", "Knowledge references")}</dt>
              <dd>
                {workflow.evidence.length ? (
                  <WorkflowKnowledgeReferences items={workflow.evidence} />
                ) : (
                  ui(
                    "未匹配到相关知识规则，将保留算法原始结果",
                    "No matching rules; the original calculation will be preserved",
                  )
                )}
              </dd>
            </dl>
          )}
          {workflow.status === "waiting_approval" && (
            <Button
              type="primary"
              loading={busy}
              onClick={() => void action(true)}
            >
              {Array.isArray(workflow.plan.reviewOutputs) &&
              workflow.plan.reviewOutputs.length
                ? ui("审核并继续", "Review and continue")
                : ui("确认执行", "Confirm execution")}
            </Button>
          )}
          {active.includes(workflow.status) && (
            <Button loading={busy} onClick={() => void action(false)}>
              {ui("停止此工作流", "Stop workflow")}
            </Button>
          )}
          <WorkflowEvidenceUpdate
            previousAnalysis={workflow.plan.previousAnalysis}
            steps={workflow.steps}
          />
          <WorkflowDecisionTimeline steps={workflow.steps} />
          {workflow.workflowType === "ecology_investigation" &&
            workflow.status === "succeeded" &&
            !previousWorkflowId && (
              <Button
                onClick={() => {
                  restore(workflow);
                  setPreviousWorkflowId(workflow.id);
                }}
              >
                补充观测后更新判断
              </Button>
            )}
          {workflow.steps.some((step) => step.computeTaskId) && (
            <RunComputeTasks
              taskIds={workflow.steps
                .map((step) => step.computeTaskId)
                .filter(Boolean)}
              autoImport={workflow.importResults}
              refreshKey={`${workflow.id}:${workflow.status}`}
            />
          )}
          {!!workflow.resultResourceIds.length && (
            <Alert
              type="success"
              title={ui(
                "成果已保存到本项目的数据资源",
                "Results saved in this project's data resources",
              )}
              description={
                mapResourceIds.length ? (
                  <a
                    href={`/map?resources=${mapResourceIds.join(",")}&projectTagId=${workflow.projectId}`}
                  >
                    {ui(
                      "在地理工作台对比成果图层",
                      "Compare result layers in the map workspace",
                    )}
                  </a>
                ) : (
                  ui(
                    "可在本项目的数据资源中查看成果",
                    "View the results in this project's data resources",
                  )
                )
              }
            />
          )}
        </div>
      )}
    </Space>
  );
  return embedded ? (
    <section className="agent-workflow-content">{content}</section>
  ) : (
    <Collapse
      size="small"
      className="agent-workflow-panel"
      items={[
        {
          key: "workflow",
          label: ui(
            "科研工作流 · 计划、执行与入库",
            "Research workflow · plan, execute and import",
          ),
          children: content,
        },
      ]}
    />
  );
}
