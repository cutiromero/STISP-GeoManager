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
  AgentBootstrap,
  AgentKnowledgeSelection,
  AgentResearchDemoList,
  AgentResource,
  ComputeAlgorithm,
  ComputeCandidate,
  ComputeParameterSpec,
  KnowledgeDomainOption,
  KnowledgeDomain,
} from "../api/generated/types.gen";
import { createUuid } from "../utils/uuid";
import { useComputeText } from "../compute/ui";
import { useProjectContext } from "../projects/ProjectContext";
import { getActiveProject, projectSignal } from "../projects/session";
import { combineAbortSignals } from "../utils/abortSignals";
import DemoWorkflowForm, {
  demoGoals,
  demoInputsReady,
  type DemoWorkflowType,
} from "./DemoWorkflowForm";
import WorkflowResults from "./WorkflowResults";
import { allWorkflowPages, workflowGeologyVersions } from "./workflowCatalog";
import { multiElementType } from "./multiElementScenario";

const active = ["queued", "running", "waiting_compute", "waiting_approval"];

function planDraftSignature(value: Record<string, unknown>) {
  return JSON.stringify(value, (_key, item: unknown) =>
    item && typeof item === "object" && !Array.isArray(item)
      ? Object.fromEntries(
          Object.entries(item).sort(([a], [b]) => a.localeCompare(b)),
        )
      : item,
  );
}

export function workflowScenarioOptions(
  projectId: string,
  demos: AgentResearchDemoList["items"],
) {
  return [
    { value: "research_processing", label: "通用科研计算" },
    ...demos
      .filter((item) => String(item.projectId) === projectId)
      .map((item) => ({ value: item.scenario, label: item.title })),
  ];
}

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
        style={{ width: "100%", minWidth: 0 }}
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
  open = true,
  bootstrap,
  onStatusChange,
  onWorkflowChange,
}: {
  model: string;
  resourceIds: number[];
  embedded?: boolean;
  open?: boolean;
  bootstrap?: AgentBootstrap | null;
  onStatusChange?: (status: AgentWorkflow["status"] | undefined) => void;
  onWorkflowChange?: (workflow: AgentWorkflow | undefined) => void;
}) {
  const ui = useComputeText();
  const project = useProjectContext();
  const projectId = project?.current ?? getActiveProject();
  const [demos, setDemos] = useState<AgentResearchDemoList["items"]>([]);
  const [goal, setGoal] = useState("");
  const [workflowType, setWorkflowType] = useState("research_processing");
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
  const [catalogScope, setCatalogScope] = useState<string>();
  const [contextScope, setContextScope] = useState<string>();
  const [historyScope, setHistoryScope] = useState<string>();
  const catalogReady = catalogScope === projectId;
  const contextReady = contextScope === projectId;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [previousWorkflowId, setPreviousWorkflowId] = useState<string>();
  const [previewDraft, setPreviewDraft] = useState("");
  const mutationInFlight = useRef(false);
  const lastPreviewRequest = useRef<
    { signature: string; key: string } | undefined
  >(undefined);
  const isDemo =
    workflowType === "ecology_investigation" ||
    workflowType === "geology_correction" ||
    workflowType === "geology_age_correction" ||
    workflowType === "geology_map_review" ||
    workflowType === multiElementType;
  const reviewingPlan =
    workflow?.status === "waiting_approval" &&
    workflow.plan.phase === "review_plan";
  const initializing =
    !catalogReady || !contextReady || historyScope !== projectId;
  const locked =
    initializing ||
    Boolean(
      workflow &&
      [...active, "paused"].includes(workflow.status) &&
      !reviewingPlan,
    );
  const draft = {
    goal,
    model,
    workflowType,
    algorithmVersionId: isDemo ? null : (versionId ?? null),
    inputs,
    parameters,
    knowledgeSelection,
  };
  const planOutdated = Boolean(
    reviewingPlan && previewDraft && previewDraft !== planDraftSignature(draft),
  );
  const version = algorithms
    .flatMap((algorithm) => algorithm.versions)
    .find((v) => v.id === versionId);
  const geologyParameterSpecs = Array.from(
    new Map(
      workflowGeologyVersions(
        algorithms,
        workflowType === multiElementType
          ? [
              "geology-multi-check",
              "geology-multi-apply",
              "geology-multi-relations",
              "geology-multi-prospect",
            ]
          : workflowType === "geology_map_review"
            ? ["geology-map-check", "geology-map-correct"]
            : ["geology-age-check", "geology-age-edit"],
      )
        .flatMap((item) => item.manifest.parameters)
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
    setPreviewDraft("");
    if (!next) return;
    setWorkflowType(next.workflowType);
    setGoal(next.goal);
    setVersionId(next.algorithmVersionId ?? undefined);
    setParameters(next.parameters);
    const savedInputs = next.plan.inputs;
    const restoredInputs =
      savedInputs &&
      typeof savedInputs === "object" &&
      !Array.isArray(savedInputs)
        ? Object.fromEntries(
            Object.entries(savedInputs).filter(
              (entry): entry is [string, number] =>
                typeof entry[1] === "number",
            ),
          )
        : {};
    setInputs(restoredInputs);
    const selection = next.plan.knowledgeSelection;
    if (
      selection &&
      typeof selection === "object" &&
      "mode" in selection &&
      "domains" in selection &&
      ["auto", "manual", "all", "none"].includes(String(selection.mode)) &&
      Array.isArray(selection.domains)
    ) {
      const restoredKnowledge = {
        mode: selection.mode as AgentKnowledgeSelection["mode"],
        domains: selection.domains.filter((value): value is KnowledgeDomain =>
          ["remote_sensing", "pipelines", "geology", "arid_ecology"].includes(
            String(value),
          ),
        ),
      };
      setKnowledgeSelection(restoredKnowledge);
      setPreviewDraft(
        planDraftSignature({
          goal: next.goal,
          model,
          workflowType: next.workflowType,
          algorithmVersionId: next.algorithmVersionId ?? null,
          inputs: restoredInputs,
          parameters: next.parameters,
          knowledgeSelection: restoredKnowledge,
        }),
      );
    } else {
      const restoredKnowledge = { mode: "auto" as const, domains: [] };
      setKnowledgeSelection(restoredKnowledge);
      setPreviewDraft(
        planDraftSignature({
          goal: next.goal,
          model,
          workflowType: next.workflowType,
          algorithmVersionId: next.algorithmVersionId ?? null,
          inputs: restoredInputs,
          parameters: next.parameters,
          knowledgeSelection: restoredKnowledge,
        }),
      );
    }
  };
  useEffect(() => {
    if (!open || contextReady) return;
    let disposed = false;
    const controller = new AbortController();
    void Promise.allSettled([
      bootstrap
        ? Promise.resolve(bootstrap)
        : agentApi.bootstrap({ signal: controller.signal }),
      agentApi.resources("", { signal: controller.signal }),
      agentApi.researchDemos({ signal: controller.signal }),
    ]).then(([bootstrap, data, scenes]) => {
      if (disposed) return;
      if (bootstrap.status === "fulfilled") {
        setKnowledgeDomains(bootstrap.value.knowledgeDomains ?? []);
      }
      if (data.status === "fulfilled") setResources(data.value.items ?? []);
      if (scenes.status === "fulfilled") setDemos(scenes.value.items ?? []);
      setContextScope(projectId);
    });
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [open, projectId, contextReady, bootstrap]);
  useEffect(() => {
    if (!open || catalogReady) return;
    let disposed = false;
    const controller = new AbortController();
    const cancellation = combineAbortSignals([
      projectSignal(),
      controller.signal,
    ]);
    const signal = cancellation.signal;
    void Promise.all([
      allWorkflowPages(
        (params) => computeApi.algorithms(params, { signal }),
        projectId,
        signal,
      ),
      allWorkflowPages(
        (params) => computeApi.inputs(params, { signal }),
        projectId,
        signal,
      ),
    ])
      .then(([a, c]) => {
        if (disposed) return;
        setAlgorithms(a);
        setCandidates(c);
      })
      .catch((e) => {
        if (!disposed) report(e);
      })
      .finally(() => {
        cancellation.dispose();
        if (!disposed) setCatalogScope(projectId);
      });
    return () => {
      disposed = true;
      controller.abort();
      cancellation.dispose();
    };
  }, [open, projectId, catalogReady]);
  useEffect(() => {
    let disposed = false;
    const controller = new AbortController();
    setWorkflow(undefined);
    setHistory([]);
    setCandidates([]);
    setResources([]);
    setDemos([]);
    setAlgorithms([]);
    void agentApi
      .workflows({ signal: controller.signal })
      .then((result) => {
        if (disposed) return;
        setHistory(result.items);
        restore(result.items[0]);
      })
      .catch((error) => {
        if (!disposed) report(error);
      })
      .finally(() => {
        if (!disposed) setHistoryScope(projectId);
      });
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [projectId]);
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
      if (reviewingPlan && workflow) {
        const cancelled = await agentApi.cancelWorkflow(workflow.id, {
          replacePlanHash: workflow.planHash,
        });
        if (cancelled.status !== "cancelled")
          throw new Error(
            "旧计划尚未停止，已保留当前任务。请刷新状态后再生成计划。",
          );
        setWorkflow(cancelled);
        setHistory((old) =>
          old.map((item) => (item.id === cancelled.id ? cancelled : item)),
        );
      }
      const body = {
        goal,
        model,
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
      setPreviewDraft(planDraftSignature(draft));
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
    if (confirm && planOutdated) {
      setError("资料或参数已改变，请重新生成执行计划后确认。");
      return;
    }
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
  const reviewWorkflow = async (
    decision: "approve" | "reject",
    feedback: string,
    selectedSuggestionIds?: string[],
  ) => {
    if (!workflow || mutationInFlight.current) return;
    mutationInFlight.current = true;
    setBusy(true);
    setError("");
    try {
      setWorkflow(
        await agentApi.confirmWorkflow(workflow.id, workflow.planHash, {
          decision,
          feedback,
          ...(selectedSuggestionIds ? { selectedSuggestionIds } : {}),
        }),
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
  const scenarioOptions = workflowScenarioOptions(
    project?.current ?? getActiveProject(),
    demos,
  );
  const currentPreset = demos.find(
    (item) =>
      item.scenario === workflowType &&
      String(item.projectId) === (project?.current ?? getActiveProject()),
  )?.preset;
  if (
    workflow &&
    !scenarioOptions.some((item) => item.value === workflow.workflowType)
  ) {
    scenarioOptions.push({
      value: workflow.workflowType,
      label: "已保存的研究场景",
    });
  }
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
            loading={initializing}
            disabled={locked || busy || Boolean(previousWorkflowId)}
            options={scenarioOptions}
            onChange={(value) => {
              const preset = demos.find(
                (item) =>
                  item.scenario === value &&
                  String(item.projectId) ===
                    (project?.current ?? getActiveProject()),
              )?.preset;
              setWorkflowType(value);
              setInputs(preset?.inputs ?? {});
              setParameters(preset?.parameters ?? {});
              setVersionId(undefined);
              if (value !== "research_processing")
                setGoal(demoGoals[value as DemoWorkflowType]);
            }}
          />
        </label>
      </div>
      <Input.TextArea
        aria-label={ui("工作流目标", "Workflow goal")}
        value={goal}
        disabled={locked || busy}
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
          preset={currentPreset}
          onPresetRestore={() => {
            if (!currentPreset) return;
            setInputs(currentPreset.inputs);
            setParameters(currentPreset.parameters);
            setGoal(demoGoals[workflowType as DemoWorkflowType]);
            setKnowledgeSelection({ mode: "auto", domains: [] });
            setVersionId(undefined);
          }}
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
                  label: `${a.name} / ${v.version}`,
                })),
            )}
            onChange={(id) => {
              setVersionId(id);
              setInputs({});
              setParameters({});
            }}
          />
          {version?.manifest.inputs.map((spec) => (
            <label key={spec.key} className="agent-workflow-parameter">
              <Typography.Text>{spec.label}</Typography.Text>
              <Select
                aria-label={spec.label}
                style={{ width: "100%", minWidth: 0 }}
                value={inputs[spec.key]}
                allowClear
                options={candidates
                  .filter((c) => c.kind === spec.kind)
                  .map((c) => ({
                    value: c.id,
                    label:
                      resources.find((item) => item.id === c.id)?.name ??
                      c.name,
                  }))}
                onChange={(id) =>
                  setInputs((old) => {
                    const next = { ...old };
                    if (id === undefined) delete next[spec.key];
                    else next[spec.key] = id;
                    return next;
                  })
                }
              />
            </label>
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
              <label key={spec.key} className="agent-workflow-parameter">
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
              </label>
            ))}
        </>
      )}
      {[
        "geology_age_correction",
        "geology_map_review",
        multiElementType,
      ].includes(workflowType) &&
        geologyParameterSpecs.length > 0 && (
          <div className="agent-demo-fields agent-demo-parameters">
            {geologyParameterSpecs
              .filter((spec) => spec.key !== "segment")
              .map((spec) => (
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
          !model ||
          locked ||
          (knowledgeSelection.mode === "manual" &&
            !knowledgeSelection.domains.length) ||
          (isDemo &&
            !demoInputsReady(
              workflowType as DemoWorkflowType,
              inputs,
              candidates,
            )) ||
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
      {reviewingPlan && (
        <Typography.Text type="secondary">
          重新生成会撤销当前尚未执行的旧计划，并按上方资料、参数与知识范围生成新计划。
        </Typography.Text>
      )}
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
      {planOutdated && (
        <Alert
          type="warning"
          title="资料或参数已改变"
          description="当前显示的是旧计划。请重新生成执行计划，核对后再确认执行。"
        />
      )}
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
          onConfirm={planOutdated ? undefined : () => void action(true)}
          onCancel={() => void action(false)}
          onPause={() => void controlWorkflow("pause")}
          onResume={() => void controlWorkflow("resume")}
          onReview={(decision, feedback, selectedSuggestionIds) =>
            void reviewWorkflow(decision, feedback, selectedSuggestionIds)
          }
          onRestart={() => {
            restore(workflow);
            setWorkflow(undefined);
            setError("");
          }}
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
            "MH-workflow / 计划、执行与入库",
            "Research workflow / plan, execute and import",
          ),
          children: content,
        },
      ]}
    />
  );
}
