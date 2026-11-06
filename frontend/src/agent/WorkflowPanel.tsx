import { approvalSelection, type AlterationActions } from "./approvalSelection";
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
import WorkflowCard from "./WorkflowCard";
import WorkflowResults from "./WorkflowResults";
import {
  agentWorkflowCatalog,
  allWorkflowPages,
  workflowGeologyVersions,
} from "./workflowCatalog";
import {
  genericGeologyGoal,
  genericGeologyType,
  multiElementType,
} from "./multiElementScenario";
import FieldMappingReview from "./FieldMappingReview";
import GenericWorkflowUploads from "./GenericWorkflowUploads";
import ActiveWorkflowNotice from "./ActiveWorkflowNotice";

const active = ["queued", "running", "waiting_compute", "waiting_approval"];
type WorkflowHistory = Pick<
  AgentWorkflow,
  "id" | "goal" | "status" | "workflowType" | "updatedAt"
>;

const newBatchId = () => createUuid().replace(/-/g, "").toLowerCase();

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
  demos: Pick<
    AgentResearchDemoList["items"][number],
    "scenario" | "projectId" | "title"
  >[],
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
  userId,
  bootstrap,
  onStatusChange,
  onWorkflowChange,
  fixedScenario,
}: {
  model: string;
  resourceIds: number[];
  embedded?: boolean;
  open?: boolean;
  userId?: number;
  bootstrap?: AgentBootstrap | null;
  onStatusChange?: (status: AgentWorkflow["status"] | undefined) => void;
  onWorkflowChange?: (workflow: AgentWorkflow | undefined) => void;
  /** Opens one scenario directly and hides the scene and knowledge selectors. */
  fixedScenario?: string;
}) {
  const ui = useComputeText();
  const project = useProjectContext();
  const projectId = project?.current ?? getActiveProject();
  const [demos, setDemos] = useState<AgentResearchDemoList["items"]>([]);
  const [scenes, setScenes] = useState<
    Pick<
      AgentResearchDemoList["items"][number],
      "scenario" | "projectId" | "title"
    >[]
  >([]);
  const fixedGeneric = fixedScenario === genericGeologyType;
  const [goal, setGoal] = useState(fixedGeneric ? genericGeologyGoal : "");
  const [workflowType, setWorkflowType] = useState(fixedScenario ?? "");
  const [resources, setResources] = useState<AgentResource[]>([]);
  const [algorithmOptions, setAlgorithmOptions] = useState<
    NonNullable<AgentBootstrap["algorithmOptions"]>
  >([]);
  const [knowledgeDomains, setKnowledgeDomains] = useState<
    KnowledgeDomainOption[]
  >([]);
  const [knowledgeSelection, setKnowledgeSelection] =
    useState<AgentKnowledgeSelection>({ mode: "auto", domains: [] });
  const [algorithms, setAlgorithms] = useState<ComputeAlgorithm[]>([]);
  const [candidates, setCandidates] = useState<ComputeCandidate[]>([]);
  const ordinaryCatalog = agentWorkflowCatalog(
    algorithms,
    candidates,
    resources,
    algorithmOptions,
  );
  const [versionId, setVersionId] = useState<number>();
  const [inputs, setInputs] = useState<Record<string, number>>({});
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const [workflow, setWorkflow] = useState<AgentWorkflow>();
  const [history, setHistory] = useState<WorkflowHistory[]>([]);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historyHasMore, setHistoryHasMore] = useState(false);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string>();
  const [demosScope, setDemosScope] = useState<string>();
  const [scenesLoading, setScenesLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [contextLoading, setContextLoading] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [catalogScope, setCatalogScope] = useState<string>();
  const [contextScope, setContextScope] = useState<string>();
  const [historyScope, setHistoryScope] = useState<string>();
  const catalogReady = catalogScope === projectId;
  const sceneScope = `${projectId}:${workflowType}`;
  const historyRequestScope = `${sceneScope}:${historyOffset}`;
  const contextReady = contextScope === sceneScope;
  const currentScope = useRef(sceneScope);
  currentScope.current = sceneScope;
  const currentSelection = useRef({ workflow, selectedWorkflowId });
  currentSelection.current = { workflow, selectedWorkflowId };
  const workflowCache = useRef(new Map<string, AgentWorkflow>());
  const storageKey = userId ? `workflow-session:${userId}:${projectId}` : "";
  const rememberedTask = (scene: string) => {
    try {
      return storageKey
        ? sessionStorage.getItem(`${storageKey}:${scene}`) || undefined
        : undefined;
    } catch {
      return undefined;
    }
  };
  const [batchId, setBatchId] = useState(newBatchId);
  const [busy, setBusy] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
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
  const generic = workflowType === genericGeologyType;
  const WorkflowPresentation =
    generic || workflowType === multiElementType
      ? WorkflowCard
      : WorkflowResults;
  const fieldMappingReview =
    workflow?.status === "waiting_approval" &&
    workflow.plan.phase === "review_mapping"
      ? workflow.plan.fieldMappingReview
      : undefined;
  const reviewingPlan =
    workflow?.status === "waiting_approval" &&
    workflow.plan.phase === "review_plan";
  const initializing =
    Boolean(workflowType) &&
    (fixedGeneric
      ? Boolean(selectedWorkflowId && (!workflow || detailLoading))
      : !catalogReady ||
        !contextReady ||
        !historyScope?.startsWith(`${sceneScope}:`) ||
        detailLoading);
  const locked =
    !workflowType ||
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
  const version = ordinaryCatalog.algorithms
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
      workflowCache.current.clear();
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
    // Generic tasks run on working copies of a used batch; a new task re-uploads.
    const reuploads = next.workflowType === genericGeologyType;
    if (reuploads) setBatchId(newBatchId());
    const restoredInputs =
      !reuploads &&
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
    setWorkflow(undefined);
    setHistory([]);
    setHistoryOffset(0);
    setHistoryHasMore(false);
    setCandidates([]);
    setResources([]);
    setAlgorithmOptions([]);
    setDemos([]);
    setScenes([]);
    setAlgorithms([]);
    setCatalogScope(undefined);
    setContextScope(undefined);
    setHistoryScope(undefined);
    setDemosScope(undefined);
    setGoal("");
    setInputs({});
    setParameters({});
    setError("");
    workflowCache.current.clear();
    let remembered = "";
    try {
      remembered = storageKey ? sessionStorage.getItem(storageKey) || "" : "";
    } catch {
      // Storage can be disabled by browser privacy settings.
    }
    const scene = fixedScenario ?? remembered;
    setWorkflowType(scene);
    setSelectedWorkflowId(rememberedTask(scene));
    if (fixedScenario === genericGeologyType) setGoal(genericGeologyGoal);
  }, [projectId, storageKey, fixedScenario]);
  useEffect(() => {
    if (!open || fixedGeneric || demosScope === projectId) return;
    let disposed = false;
    const controller = new AbortController();
    setScenesLoading(true);
    void agentApi
      .researchDemoSummaries({ signal: controller.signal })
      .then((result) => {
        if (disposed) return;
        setScenes(result.items);
        setDemosScope(projectId);
      })
      .catch((reason) => {
        if (!disposed) report(reason);
      })
      .finally(() => {
        if (!disposed) setScenesLoading(false);
      });
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [open, projectId, demosScope, loadAttempt, fixedGeneric]);
  useEffect(() => {
    if (!open || fixedGeneric || !workflowType || contextReady) return;
    let disposed = false;
    const controller = new AbortController();
    setContextLoading(true);
    void Promise.all([
      bootstrap
        ? Promise.resolve(bootstrap)
        : agentApi.bootstrap({ signal: controller.signal }),
      agentApi.resources("", { signal: controller.signal }),
      workflowType === "research_processing"
        ? Promise.resolve({ items: [] })
        : agentApi.researchDemos({
            scenario:
              workflowType as AgentResearchDemoList["items"][number]["scenario"],
            signal: controller.signal,
          }),
    ])
      .then(([configuration, data, presets]) => {
        if (disposed) return;
        setKnowledgeDomains(configuration.knowledgeDomains ?? []);
        setResources(data.items ?? []);
        setAlgorithmOptions(configuration.algorithmOptions ?? []);
        setDemos(presets.items);
        if (
          !currentSelection.current.workflow &&
          !currentSelection.current.selectedWorkflowId
        ) {
          const preset = presets.items.find(
            (item) => item.scenario === workflowType,
          )?.preset;
          setInputs(preset?.inputs ?? {});
          setParameters(preset?.parameters ?? {});
        }
        setContextScope(sceneScope);
      })
      .catch((reason) => {
        if (!disposed) report(reason);
      })
      .finally(() => {
        if (!disposed) setContextLoading(false);
      });
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [open, sceneScope, contextReady, bootstrap, loadAttempt, fixedGeneric]);
  useEffect(() => {
    if (!open || fixedGeneric || !workflowType || catalogReady) return;
    let disposed = false;
    const controller = new AbortController();
    const cancellation = combineAbortSignals([
      projectSignal(),
      controller.signal,
    ]);
    const signal = cancellation.signal;
    setCatalogLoading(true);
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
        setCatalogScope(projectId);
      })
      .catch((e) => {
        if (!disposed) report(e);
      })
      .finally(() => {
        cancellation.dispose();
        if (!disposed) setCatalogLoading(false);
      });
    return () => {
      disposed = true;
      controller.abort();
      cancellation.dispose();
    };
  }, [
    open,
    projectId,
    catalogReady,
    Boolean(workflowType),
    loadAttempt,
    fixedGeneric,
  ]);
  useEffect(() => {
    if (!open || !workflowType || historyScope === historyRequestScope) return;
    let disposed = false;
    const controller = new AbortController();
    if (!historyOffset) setHistory([]);
    setHistoryLoading(true);
    void agentApi
      .workflowHistory({
        workflowType,
        offset: historyOffset,
        limit: 30,
        signal: controller.signal,
      })
      .then((result) => {
        if (disposed) return;
        setHistory((previous) =>
          historyOffset
            ? [
                ...previous,
                ...result.items.filter(
                  (item) => !previous.some((old) => old.id === item.id),
                ),
              ]
            : result.items,
        );
        setHistoryHasMore(result.hasMore);
        setHistoryScope(historyRequestScope);
      })
      .catch((error) => {
        if (!disposed) report(error);
      })
      .finally(() => {
        if (!disposed) setHistoryLoading(false);
      });
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [open, historyRequestScope, historyScope, loadAttempt]);
  useEffect(() => {
    const requestedId = workflow?.id ?? selectedWorkflowId;
    if (!open || !requestedId) return;
    let disposed = false;
    const controller = new AbortController();
    const requestedScope = sceneScope;
    setDetailLoading(true);
    void agentApi
      .workflow(requestedId, {
        signal: controller.signal,
        view:
          generic || workflowType === multiElementType ? "inspection" : "full",
      })
      .then((next) => {
        if (disposed || currentScope.current !== requestedScope) return;
        if (
          String(next.projectId) !== projectId ||
          next.workflowType !== workflowType
        )
          throw new Error("该历史任务不属于当前项目或研究场景，请重新选择。");
        restore(next);
      })
      .catch((reason) => {
        if (!disposed) report(reason);
      })
      .finally(() => {
        if (!disposed) setDetailLoading(false);
      });
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [open, selectedWorkflowId, sceneScope, loadAttempt]);
  useEffect(() => {
    if (!workflow || String(workflow.projectId) !== projectId) return;
    workflowCache.current.set(
      `${projectId}:${workflow.workflowType}`,
      workflow,
    );
    if (!storageKey) return;
    try {
      sessionStorage.setItem(storageKey, workflow.workflowType);
      sessionStorage.setItem(
        `${storageKey}:${workflow.workflowType}`,
        workflow.id,
      );
    } catch {
      // A disabled session store does not prevent the current task from running.
    }
  }, [workflow, storageKey, projectId]);
  useEffect(() => {
    if (
      !open ||
      !workflow ||
      !active.includes(workflow.status) ||
      workflow.status === "waiting_approval"
    )
      return;
    let disposed = false;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await agentApi.workflow(workflow.id, {
          signal: controller.signal,
          view:
            generic || workflowType === multiElementType
              ? "inspection"
              : "full",
        });
        if (disposed) return;
        setWorkflow(next);
        if (["queued", "running", "waiting_compute"].includes(next.status))
          timer = setTimeout(poll, document.hidden ? 5000 : 1500);
      } catch (e) {
        if (!disposed) report(e);
      }
    };
    timer = setTimeout(poll, 0);
    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [open, workflow?.id, workflow?.status]);
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
        ...(generic ? { uploadBatchId: batchId, resourceIds: [] } : {}),
        parameters: generic
          ? {}
          : workflowType === "ecology_investigation"
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
      setPreviewDraft(generic ? "" : planDraftSignature(draft));
      if (generic) {
        // A batch belongs to one task; the next task starts a fresh upload set.
        setBatchId(newBatchId());
        setInputs({});
      }
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
  const confirmFieldMapping = async (
    fieldMapping: Record<string, Record<string, string | null>>,
    applyRuleSuggestions = false,
  ) => {
    if (!workflow || mutationInFlight.current) return;
    mutationInFlight.current = true;
    setBusy(true);
    setError("");
    try {
      setWorkflow(
        await agentApi.confirmWorkflow(workflow.id, workflow.planHash, {
          fieldMapping,
          executeAfterMapping: true,
          applyRuleSuggestions,
        }),
      );
    } catch (reason) {
      report(reason);
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
    alterationActions?: AlterationActions,
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
          ...(await approvalSelection(workflow, selectedSuggestionIds)),
          ...(alterationActions && Object.keys(alterationActions).length
            ? { alterationActions }
            : {}),
        }),
      );
    } catch (reason) {
      report(reason);
    } finally {
      mutationInFlight.current = false;
      setBusy(false);
    }
  };
  const reportedWorkflow =
    [
      workflow,
      ...[...workflowCache.current.values()].filter(
        (item) => item.id !== workflow?.id,
      ),
    ].find((item) => item && [...active, "paused"].includes(item.status)) ??
    workflow;
  useEffect(() => {
    onStatusChange?.(reportedWorkflow?.status);
  }, [reportedWorkflow?.status, onStatusChange]);
  useEffect(() => {
    onWorkflowChange?.(reportedWorkflow);
  }, [reportedWorkflow, onWorkflowChange]);
  const scenarioOptions = workflowScenarioOptions(
    project?.current ?? getActiveProject(),
    scenes,
  );
  const currentPreset = demos.find(
    (item) =>
      item.scenario === workflowType &&
      String(item.projectId) === (project?.current ?? getActiveProject()),
  )?.preset;
  const scenarioCandidates = candidates.filter(
    (candidate) =>
      ordinaryCatalog.candidates.some((item) => item.id === candidate.id) ||
      candidate.id === currentPreset?.inputs.rules,
  );
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
      {open && (
        <ActiveWorkflowNotice
          projectId={projectId}
          currentId={workflow?.id}
          refreshKey={`${error}:${workflow?.status ?? ""}`}
        />
      )}
      <Typography.Text type="secondary">
        {ui(
          "描述目标，核对数据与算法后确认执行。平台持续跟踪计算、知识检查和结果入库，离开页面后仍可恢复查看。",
          "Describe a goal, review the data and algorithm, then confirm. The platform tracks calculation, knowledge checks and import even after you leave.",
        )}
      </Typography.Text>
      <div className="agent-workflow-selectors" hidden={Boolean(fixedScenario)}>
        <label>
          <span>研究场景</span>
          <Select
            aria-label="研究场景"
            value={workflowType || undefined}
            placeholder="请选择研究场景"
            loading={scenesLoading}
            disabled={scenesLoading || busy || Boolean(previousWorkflowId)}
            options={scenarioOptions}
            onChange={(value) => {
              const preset = demos.find(
                (item) =>
                  item.scenario === value &&
                  String(item.projectId) ===
                    (project?.current ?? getActiveProject()),
              )?.preset;
              setWorkflowType(value);
              setWorkflow(undefined);
              setPreviousWorkflowId(undefined);
              setPreviewDraft("");
              setHistory([]);
              setHistoryOffset(0);
              setHistoryHasMore(false);
              setHistoryScope(undefined);
              setContextScope(undefined);
              setDetailLoading(false);
              setError("");
              setInputs(preset?.inputs ?? {});
              setParameters(preset?.parameters ?? {});
              setVersionId(undefined);
              setBatchId(newBatchId());
              setGoal(
                value === "research_processing"
                  ? ""
                  : value === genericGeologyType
                    ? genericGeologyGoal
                    : demoGoals[value as DemoWorkflowType],
              );
              setSelectedWorkflowId(rememberedTask(value));
              const cached = workflowCache.current.get(`${projectId}:${value}`);
              if (cached) {
                restore(cached);
                setSelectedWorkflowId(cached.id);
              }
              try {
                if (storageKey) sessionStorage.setItem(storageKey, value);
              } catch {
                // Keep the selected scene in memory when storage is unavailable.
              }
            }}
          />
        </label>
      </div>
      {(scenesLoading ||
        historyLoading ||
        detailLoading ||
        catalogLoading ||
        contextLoading) && (
        <Typography.Text role="status" aria-live="polite" type="secondary">
          {scenesLoading
            ? "正在加载研究场景…"
            : detailLoading
              ? "正在恢复所选任务…"
              : "正在加载当前场景的资料与历史…"}
        </Typography.Text>
      )}
      {error && (
        <Alert
          type="error"
          title={error}
          action={
            <Button
              size="small"
              onClick={() => {
                setError("");
                setLoadAttempt((value) => value + 1);
              }}
            >
              重新加载
            </Button>
          }
        />
      )}
      {!workflowType && !scenesLoading && (
        <Typography.Text type="secondary">
          选择研究场景后加载本项目资料和您在该场景下的历史任务。
        </Typography.Text>
      )}
      {workflowType && (
        <>
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
              candidates={scenarioCandidates}
              boundRulesId={
                ordinaryCatalog.candidates.some(
                  (candidate) => candidate.id === currentPreset?.inputs.rules,
                )
                  ? undefined
                  : currentPreset?.inputs.rules
              }
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
          ) : generic ? (
            <GenericWorkflowUploads
              model={model}
              onActivityChange={setUploadBusy}
              batchId={batchId}
              inputs={inputs}
              disabled={locked || busy}
              onInputsChange={setInputs}
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
                options={ordinaryCatalog.algorithms.flatMap((a) =>
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
                    options={ordinaryCatalog.candidates
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
                          ? ordinaryCatalog.candidates.find(
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
                          setParameters((old) => ({
                            ...old,
                            [spec.key]: value,
                          }))
                        }
                      />
                    </label>
                  ))}
              </div>
            )}
          <div
            className="agent-workflow-selectors"
            hidden={Boolean(fixedScenario)}
          >
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
                    domains:
                      mode === "manual" ? knowledgeSelection.domains : [],
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
              (generic && (!inputs.lithology || uploadBusy)) ||
              (isDemo &&
                !demoInputsReady(
                  workflowType as DemoWorkflowType,
                  inputs,
                  scenarioCandidates,
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
          {planOutdated && (
            <Alert
              type="warning"
              title="资料或参数已改变"
              description="当前显示的是旧计划。请重新生成执行计划，核对后再确认执行。"
            />
          )}
          {history.length > 0 && (
            <Select
              aria-label={ui("历史工作流", "Workflow history")}
              style={{ width: "100%" }}
              value={workflow?.id}
              placeholder="选择历史任务后查看详情"
              loading={historyLoading || detailLoading}
              disabled={busy}
              options={history.map((item) => ({
                value: item.id,
                label: item.goal,
              }))}
              onChange={(id) => {
                setError("");
                setWorkflow(undefined);
                setSelectedWorkflowId(id);
              }}
            />
          )}
          {historyHasMore && (
            <Button
              size="small"
              loading={historyLoading}
              onClick={() => setHistoryOffset(history.length)}
            >
              加载更多历史任务
            </Button>
          )}
          {fieldMappingReview && (
            <FieldMappingReview
              startAnalysis
              key={workflow?.planHash}
              review={fieldMappingReview}
              busy={busy}
              onConfirm={(mapping, automatic) =>
                void confirmFieldMapping(mapping, automatic)
              }
            />
          )}
          {workflow && (
            <WorkflowPresentation
              workflow={workflow}
              busy={busy}
              onConfirm={
                planOutdated || fieldMappingReview
                  ? undefined
                  : () => void action(true)
              }
              onCancel={() => void action(false)}
              onPause={() => void controlWorkflow("pause")}
              onResume={() => void controlWorkflow("resume")}
              reviewError={error}
              onReview={(
                decision,
                feedback,
                selectedSuggestionIds,
                alterationActions,
              ) =>
                void reviewWorkflow(
                  decision,
                  feedback,
                  selectedSuggestionIds,
                  alterationActions,
                )
              }
              onRestart={() => {
                restore(workflow);
                setWorkflow(undefined);
                setSelectedWorkflowId(undefined);
                workflowCache.current.delete(sceneScope);
                try {
                  if (storageKey)
                    sessionStorage.removeItem(`${storageKey}:${workflowType}`);
                } catch {
                  // The form can still be restarted without browser persistence.
                }
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
        </>
      )}
    </Space>
  );
  if (!open) return null;
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
