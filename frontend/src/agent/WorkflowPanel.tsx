import {
  Alert,
  Button,
  Collapse,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
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
import WorkflowResults from "./WorkflowResults";

const active = ["queued", "running", "waiting_compute", "waiting_approval"];

function ParameterField({
  spec,
  value,
  candidate,
  onChange,
  disabled = false,
}: {
  spec: ComputeParameterSpec;
  value: unknown;
  candidate?: ComputeCandidate;
  onChange: (value: unknown) => void;
  disabled?: boolean;
}) {
  if (spec.type === "boolean")
    return (
      <Switch
        checked={value === true}
        onChange={onChange}
        disabled={disabled}
      />
    );
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
        disabled={disabled}
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
        disabled={disabled}
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
      disabled={disabled}
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
  onWorkflowChange,
}: {
  model: string;
  resourceIds: number[];
  embedded?: boolean;
  onStatusChange?: (status: AgentWorkflow["status"] | undefined) => void;
  onWorkflowChange?: (workflow: AgentWorkflow | undefined) => void;
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
    workflowType === "geology_correction" ||
    workflowType === "geology_age_correction";
  const locked = Boolean(
    workflow && [...active, "paused"].includes(workflow.status),
  );
  const version = algorithms
    .flatMap((algorithm) => algorithm.versions)
    .find((v) => v.id === versionId);
  const ageParameterSpecs = Array.from(
    new Map(
      algorithms
        .filter((algorithm) =>
          ["geology-age-check", "geology-age-edit"].includes(
            algorithm.identifier,
          ),
        )
        .flatMap((algorithm) =>
          algorithm.versions
            .filter((item) => item.status === "published")
            .sort((left, right) => right.id - left.id)
            .slice(0, 1)
            .flatMap((item) => item.manifest.parameters),
        )
        .map((spec) => [spec.key, spec] as const),
    ).values(),
  );
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
  const controlWorkflow = async (action: "pause" | "resume") => {
    if (!workflow || mutationInFlight.current) return;
    mutationInFlight.current = true;
    setBusy(true);
    setError("");
    try {
      setWorkflow(
        action === "pause"
          ? await agentApi.pauseWorkflow(workflow.id)
          : await agentApi.resumeWorkflow(workflow.id),
      );
    } catch (reason) {
      report(reason);
    } finally {
      mutationInFlight.current = false;
      setBusy(false);
    }
  };
  useEffect(() => {
    onStatusChange?.(workflow?.status);
  }, [workflow?.status, onStatusChange]);
  useEffect(() => {
    onWorkflowChange?.(workflow);
  }, [workflow, onWorkflowChange]);
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
              {
                value: "geology_age_correction",
                label: "真实底图 · 地层时代录入纠偏",
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
      {workflowType === "geology_age_correction" &&
        ageParameterSpecs.length > 0 && (
          <div className="agent-demo-fields agent-demo-parameters">
            {ageParameterSpecs.map((spec) => (
              <label key={spec.key}>
                <span>{spec.label}</span>
                <ParameterField
                  spec={spec}
                  value={parameters[spec.key] ?? spec.default}
                  disabled={locked || busy}
                  onChange={(value) =>
                    setParameters((old) => ({ ...old, [spec.key]: value }))
                  }
                />
              </label>
            ))}
          </div>
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
        <WorkflowResults
          workflow={workflow}
          busy={busy}
          onConfirm={() => void action(true)}
          onCancel={() => void action(false)}
          onPause={() => void controlWorkflow("pause")}
          onResume={() => void controlWorkflow("resume")}
          onEvidenceUpdate={
            !previousWorkflowId
              ? () => {
                  restore(workflow);
                  setPreviousWorkflowId(workflow.id);
                }
              : undefined
          }
        />
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
