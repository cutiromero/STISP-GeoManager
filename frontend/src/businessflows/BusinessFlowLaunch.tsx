import {
  AuditOutlined,
  BranchesOutlined,
  CloseOutlined,
  DatabaseOutlined,
  DownOutlined,
  PlayCircleOutlined,
  RobotOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Alert, Button, Input, Select, Spin, Tag } from "antd";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type {
  AgentResource,
  BusinessFlowRun,
  BusinessFlowVersion,
  BusinessFlowInputAdapterChoices,
  BusinessFlowInputPlan,
  AgentBudgetProfileId,
  BusinessFlowStart,
  MonitoringWorkflowLaunch,
} from "../api/generated/types.gen";
import { businessFlowsApi } from "../api/businessFlows";
import { agentApi } from "../api/agent";
import { ApiError } from "../api/client";
import { useAgentBootstrapState } from "../agent/useAgentBootstrap";
import {
  getActiveProject,
  projectSignal,
  requestScope,
} from "../projects/session";
import {
  browserSessionEpoch,
  browserSessionSignal,
} from "../auth/browserSession";
import { useComputeText } from "../compute/ui";
import { createUuid } from "../utils/uuid";
import { canonicalReadKey } from "../api/readFlights";
import InputAdaptationReview, { preparationKey } from "./InputAdaptationReview";
import { ResourceSearchLabel } from "../agent/ResourceSearchLabel";
import { RESOURCE_SEARCH_DELAY_MS } from "../agent/resourceSearch";
import ReasoningEffortControl, {
  type ReasoningEffort,
} from "../agent/ReasoningEffortControl";
import TaskBudgetControl from "../agent/TaskBudgetControl";
import "./business-flows.css";
import "./business-flow-launch.css";

// Candidate reads are bounded metadata. Search is remote and shared by all roles.
const CANDIDATE_SEARCH_DELAY_MS = RESOURCE_SEARCH_DELAY_MS;
const MAX_CANDIDATE_LABELS = 256;
const GenericWorkflowUploads = lazy(
  () => import("../agent/GenericWorkflowUploads"),
);
export type BusinessFlowLaunchIntent = MonitoringWorkflowLaunch;
export default function BusinessFlowLaunch({
  launch,
  model,
  conversationId,
  onStarted,
  onCancel,
  compact = false,
  reasoningEffort = "medium",
  onReasoningEffortChange,
  initialInputs,
  inputLabels,
  parameters,
  presentation = "default",
}: {
  launch: BusinessFlowLaunchIntent;
  model: string;
  conversationId?: number;
  onStarted: (flow: BusinessFlowRun) => void | Promise<void>;
  onCancel: () => void;
  compact?: boolean;
  reasoningEffort?: ReasoningEffort;
  onReasoningEffortChange?: (value: ReasoningEffort) => void;
  initialInputs?: Record<string, number>;
  inputLabels?: Record<number, string>;
  parameters?: BusinessFlowStart["parameters"];
  presentation?: "default" | "task";
}) {
  const ui = useComputeText();
  const { bootstrap } = useAgentBootstrapState();
  const [version, setVersion] = useState<BusinessFlowVersion>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [goal, setGoal] = useState(
    typeof launch.goal === "string" ? launch.goal : "",
  );
  const [inputs, setInputs] = useState<Record<string, number>>({});
  const [adapterChoices, setAdapterChoices] =
    useState<BusinessFlowInputAdapterChoices>({});
  const [preparation, setPreparation] = useState<{
    key: string;
    ready: boolean;
    plan?: BusinessFlowInputPlan;
  }>();
  const previousInputs = useRef(inputs);
  const [reviewer, setReviewer] = useState<string>();
  const [effort, setEffort] = useState(reasoningEffort);
  const [budgetProfile, setBudgetProfile] =
    useState<AgentBudgetProfileId>("normal");
  const [outputTokens, setOutputTokens] = useState<number>();
  useEffect(() => {
    setBudgetProfile(bootstrap?.budgets?.defaultProfile ?? "normal");
    setOutputTokens(undefined);
  }, [
    bootstrap?.budgets?.defaultProfile,
    launch.definitionId,
    launch.versionId,
  ]);
  useEffect(() => setEffort(reasoningEffort), [reasoningEffort]);
  const [batchId, setBatchId] = useState(() => createUuid().replace(/-/g, ""));
  const [uploading, setUploading] = useState(false);
  const [materialCount, setMaterialCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [resources, setResources] = useState<AgentResource[]>([]);
  const [resourceState, setResourceState] = useState<
    "idle" | "loading" | "ready" | "error"
  >("idle");
  const [resourceError, setResourceError] = useState("");
  const [resourceSearch, setResourceSearch] = useState("");
  const candidateComposing = useRef(false);
  const [openRole, setOpenRole] = useState<string | null>(null);
  const roleOpen = useRef<string | null>(null);
  const lastRole = useRef<string | null>(null);
  const wantedQuery = useRef("");
  const readyQuery = useRef<string | null>(null);
  const requestQuery = useRef<string | null>(null);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const candidateLabels = useRef(new Map<number, string>());
  const selectedInputs = useRef(inputs);
  selectedInputs.current = inputs;
  const candidateScope = `${browserSessionEpoch()}:${getActiveProject()}:${launch.definitionId}:${launch.versionId}`;
  const candidateScopeRef = useRef(candidateScope);
  candidateScopeRef.current = candidateScope;
  const alive = useRef(true);
  const identity = useRef(`${launch.definitionId}:${launch.versionId}`);
  identity.current = `${launch.definitionId}:${launch.versionId}`;
  const inFlight = useRef(false);
  const candidateRequest = useRef<AbortController | null>(null);
  const retry = useRef<{ fingerprint: string; key: string } | null>(null);
  const callbacks = useRef({ onStarted, onCancel });
  callbacks.current = { onStarted, onCancel };
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      candidateRequest.current?.abort();
      clearTimeout(searchTimer.current);
    };
  }, []);
  useEffect(() => {
    const clear = () => {
      clearTimeout(searchTimer.current);
      searchTimer.current = undefined;
      candidateRequest.current?.abort();
      candidateRequest.current = null;
      requestQuery.current = null;
      readyQuery.current = null;
      wantedQuery.current = "";
      candidateLabels.current.clear();
      roleOpen.current = null;
      lastRole.current = null;
      setResources([]);
      setResourceState("idle");
      setResourceError("");
      setResourceSearch("");
      candidateComposing.current = false;
      setOpenRole(null);
      setInputs({});
    };
    clear();
    const auth = browserSessionSignal(),
      project = projectSignal();
    auth.addEventListener("abort", clear, { once: true });
    project.addEventListener("abort", clear, { once: true });
    return () => {
      clearTimeout(searchTimer.current);
      candidateRequest.current?.abort();
      auth.removeEventListener("abort", clear);
      project.removeEventListener("abort", clear);
    };
  }, [candidateScope]);
  useEffect(() => {
    setGoal(typeof launch.goal === "string" ? launch.goal : "");
    setInputs(initialInputs ?? {});
    for (const [key, label] of Object.entries(inputLabels ?? {}))
      candidateLabels.current.set(Number(key), label);
    setReviewer(undefined);
    setBatchId(createUuid().replace(/-/g, ""));
    retry.current = null;
    setBusy(false);
    inFlight.current = false;
  }, [launch.definitionId, launch.versionId]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setVersion(undefined);
    if (
      !Number.isSafeInteger(launch.definitionId) ||
      launch.definitionId < 1 ||
      !Number.isSafeInteger(launch.versionId) ||
      launch.versionId < 1
    ) {
      setLoading(false);
      setError("业务流版本标识无效，请从目录重新选择。");
      return () => controller.abort();
    }
    void businessFlowsApi
      .detail(launch.definitionId, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return;
        const selected = result.versions.find(
          (value) =>
            value.id === launch.versionId && value.status === "published",
        );
        if (!selected)
          throw new Error("该发布版本已无法读取，请返回业务流目录重新选择。");
        if (!result.flow.isActive)
          throw new Error("此业务流已停用，不能启动新任务。");
        setVersion(selected);
      })
      .catch((reason) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error ? reason.message : "暂时无法读取业务流版本",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [launch.definitionId, launch.versionId, attempt]);
  const isLegacy = version?.definition.adapter === "geology_generic";
  const inputRequest = {
    versionId: launch.versionId,
    inputs,
    inputAdapters: adapterChoices,
    ...(isLegacy ? { uploadBatchId: batchId } : {}),
  };
  const inputKey = preparationKey(inputRequest);
  const inputReady = preparation?.key === inputKey && preparation.ready;
  useEffect(() => {
    const old = previousInputs.current;
    previousInputs.current = inputs;
    setAdapterChoices((previous) => {
      const next = Object.fromEntries(
        Object.entries(previous).filter(
          ([role]) => inputs[role] !== undefined && inputs[role] === old[role],
        ),
      );
      return Object.keys(next).length === Object.keys(previous).length
        ? previous
        : next;
    });
  }, [canonicalReadKey(inputs)]);
  const needsReview = Boolean(
    version?.definition.nodes.some((node) => node.review.ai),
  );
  const reviewerModel = reviewer ?? model;
  const budgetAliases = [
    model,
    ...(version?.definition.nodes
      .filter((node) => node.review.ai)
      .map((node) => node.review.model || reviewerModel) ?? []),
  ];
  const budgetWindow = Math.min(
    ...budgetAliases.map(
      (alias) =>
        bootstrap?.models.find((item) => item.alias === alias)
          ?.contextWindowTokens ??
        bootstrap?.budgets?.limits.contextWindowTokens ??
        32768,
    ),
  );
  const thinkingAvailable =
    bootstrap?.thinkingEnabled !== false &&
    Boolean(
      bootstrap?.models.find((item) => item.alias === model)?.supportsThinking,
    );
  const modelOptions = (bootstrap?.models ?? [])
    .filter((value) => value.allowAgent)
    .map((value) => ({
      value: value.alias,
      label: value.name,
      disabled: value.status !== "online",
    }));
  const missing =
    version?.definition.inputRequirements.filter(
      (input) =>
        input.required &&
        !Object.keys(inputs).some(
          (key) =>
            key === input.key ||
            (input.multiple && key.startsWith(input.key + ":")),
        ),
    ) ?? [];
  const loadCandidates = async (query = wantedQuery.current, force = false) => {
    if (!roleOpen.current || !alive.current || candidateComposing.current)
      return;
    query = query.trim().slice(0, 200);
    wantedQuery.current = query;
    if (
      candidateRequest.current &&
      !candidateRequest.current.signal.aborted &&
      requestQuery.current === query
    )
      return;
    if (!force && readyQuery.current === query) return;
    candidateRequest.current?.abort();
    const controller = new AbortController(),
      scope = candidateScopeRef.current,
      ensureScope = requestScope();
    candidateRequest.current = controller;
    requestQuery.current = query;
    readyQuery.current = null;
    setResources([]);
    setResourceState("loading");
    setResourceError("");
    try {
      const result = await agentApi.resources(query, {
        signal: controller.signal,
      });
      ensureScope();
      if (
        !alive.current ||
        controller.signal.aborted ||
        candidateRequest.current !== controller ||
        candidateScopeRef.current !== scope ||
        wantedQuery.current !== query
      )
        return;
      for (const resource of result.items)
        candidateLabels.current.set(resource.id, resource.name);
      const retained = new Set([
        ...Object.values(selectedInputs.current),
        ...result.items.map((resource) => resource.id),
      ]);
      for (const identity of candidateLabels.current.keys()) {
        if (candidateLabels.current.size <= MAX_CANDIDATE_LABELS) break;
        if (!retained.has(identity)) candidateLabels.current.delete(identity);
      }
      setResources(result.items);
      readyQuery.current = query;
      setResourceState("ready");
    } catch (reason) {
      if (
        !alive.current ||
        controller.signal.aborted ||
        candidateRequest.current !== controller ||
        candidateScopeRef.current !== scope ||
        wantedQuery.current !== query
      )
        return;
      if (reason instanceof Error && reason.name === "AbortError") return;
      readyQuery.current = null;
      setResourceState("error");
      setResourceError(
        reason instanceof Error ? reason.message : "暂时无法读取授权资料",
      );
      if (reason instanceof ApiError && [401, 403].includes(reason.status)) {
        candidateLabels.current.clear();
        setResources([]);
        setInputs({});
      }
    } finally {
      if (candidateRequest.current === controller) {
        candidateRequest.current = null;
        requestQuery.current = null;
      }
    }
  };
  const searchCandidates = (query: string) => {
    if (!roleOpen.current) return;
    const next = query.trim().slice(0, 200);
    setResourceSearch(query);
    if (candidateComposing.current) return;
    if (
      wantedQuery.current === next &&
      (searchTimer.current !== undefined ||
        requestQuery.current === next ||
        readyQuery.current === next)
    )
      return;
    clearTimeout(searchTimer.current);
    candidateRequest.current?.abort();
    candidateRequest.current = null;
    requestQuery.current = null;
    wantedQuery.current = next;
    readyQuery.current = null;
    setResources([]);
    setResourceState("loading");
    setResourceError("");
    searchTimer.current = setTimeout(() => {
      searchTimer.current = undefined;
      if (roleOpen.current) void loadCandidates(next);
    }, CANDIDATE_SEARCH_DELAY_MS);
  };
  const openCandidates = (role: string, open: boolean) => {
    if (open) {
      roleOpen.current = role;
      lastRole.current = role;
      setOpenRole(role);
      clearTimeout(searchTimer.current);
      searchTimer.current = undefined;
      if (!candidateComposing.current) {
        setResourceSearch("");
        void loadCandidates("");
      }
    } else if (roleOpen.current === role) {
      candidateComposing.current = false;
      if (searchTimer.current !== undefined && !candidateRequest.current)
        setResourceState("idle");
      roleOpen.current = null;
      setOpenRole(null);
      setResourceSearch("");
      clearTimeout(searchTimer.current);
      searchTimer.current = undefined;
    }
  };
  const retryCandidates = () => {
    const role =
      roleOpen.current ??
      lastRole.current ??
      version?.definition.inputRequirements[0]?.key;
    if (!role) return;
    roleOpen.current = role;
    setOpenRole(role);
    setResourceSearch(wantedQuery.current);
    void loadCandidates(wantedQuery.current, true);
  };
  const start = async () => {
    if (inFlight.current || !version) return;
    if (!goal.trim()) {
      setError("请说明本次任务目标。");
      return;
    }
    if (missing.length) {
      setError(
        `请补齐必需资料：${missing.map((input) => input.label).join("、")}。`,
      );
      return;
    }
    if (!inputReady) {
      setError("请先完成输入适配方案，当前任务尚未启动。");
      return;
    }
    if (!model || !bootstrap?.canAgent || !bootstrap.workerOnline) {
      setError("智能体执行服务尚未就绪，请连接成功后再开始。");
      return;
    }
    const owner = identity.current,
      scope = requestScope();
    inFlight.current = true;
    setBusy(true);
    setError("");
    const body = {
      versionId: version.id,
      goal: goal.trim(),
      model,
      reviewerModel,
      ...(thinkingAvailable ? { reasoningEffort: effort } : {}),
      ...(bootstrap.budgets?.enabled
        ? {
            budgetProfile,
            ...(outputTokens !== undefined
              ? { maxOutputTokens: outputTokens }
              : {}),
          }
        : {}),
      inputs: Object.fromEntries(
        Object.entries(inputs).sort(([a], [b]) => a.localeCompare(b)),
      ),
      parameters: isLegacy ? { uploadBatchId: batchId } : (parameters ?? {}),
      inputAdapters: Object.fromEntries(
        (preparation?.plan?.items ?? [])
          .filter((item) => item.status === "convert" && item.versionId)
          .map((item) => [
            item.role,
            { versionId: item.versionId, parameters: item.parameters ?? {} },
          ]),
      ),
      ...(conversationId !== undefined ? { conversationId } : {}),
    };
    const fingerprint = canonicalReadKey([launch.definitionId, body]);
    if (retry.current?.fingerprint !== fingerprint)
      retry.current = { fingerprint, key: createUuid() };
    try {
      const flow = await businessFlowsApi.start(launch.definitionId, {
        ...body,
        idempotencyKey: retry.current.key,
      });
      scope();
      if (alive.current && identity.current === owner)
        await callbacks.current.onStarted(flow);
    } catch (reason) {
      if (
        alive.current &&
        identity.current === owner &&
        !(reason instanceof Error && reason.name === "AbortError")
      )
        setError(
          reason instanceof Error ? reason.message : "业务流暂未启动，请重试。",
        );
    } finally {
      if (alive.current && identity.current === owner) {
        inFlight.current = false;
        setBusy(false);
      }
    }
  };
  const canStart = Boolean(
    version &&
    model &&
    bootstrap?.canAgent &&
    bootstrap.workerOnline &&
    !busy &&
    !uploading &&
    inputReady &&
    !missing.length &&
    goal.trim(),
  );
  const SettingsTag = presentation === "task" ? "details" : "div";
  return (
    <section
      className="business-flow-launch-panel"
      aria-label={ui("业务流启动准备", "Business flow launch preparation")}
    >
      <header>
        <span className="business-flow-launch-icon">
          <BranchesOutlined />
        </span>
        <div>
          <small>
            {ui("任务准备", "PREPARE TASK")}
            {version ? ` · v${version.version}` : ""}
          </small>
          <strong>{launch.title}</strong>
        </div>
        <Button
          type="text"
          icon={<CloseOutlined />}
          aria-label={ui("取消业务流准备", "Cancel flow preparation")}
          disabled={busy}
          onClick={() => callbacks.current.onCancel()}
        />
      </header>
      {loading ? (
        <div className="business-flow-launch-loading">
          <Spin />
        </div>
      ) : error && !version ? (
        <Alert
          type="error"
          showIcon
          title={error}
          action={
            <Button
              size="small"
              aria-label={ui("重试读取业务流版本", "Retry flow version")}
              onClick={() => setAttempt((value) => value + 1)}
            >
              {ui("重试", "Retry")}
            </Button>
          }
        />
      ) : version ? (
        <>
          <div className="flow-launch-scroll">
            <div className="flow-launch-grid">
              <div className="flow-launch-form">
                {error && <Alert type="error" showIcon title={error} />}
                <label
                  className="business-flow-launch-field"
                  htmlFor="business-flow-launch-goal"
                >
                  {ui("本次任务目标", "Task goal")}
                  <Input.TextArea
                    id="business-flow-launch-goal"
                    value={goal}
                    disabled={busy}
                    onChange={(event) => setGoal(event.target.value)}
                    maxLength={12000}
                    autoSize={{ minRows: 2, maxRows: 5 }}
                  />
                </label>
                <SettingsTag className="business-flow-launch-settings">
                  {presentation === "task" && (
                    <summary>{ui("执行设置", "Execution settings")}</summary>
                  )}
                  <div className="business-flow-launch-roles">
                    <span>
                      <RobotOutlined />
                      {ui("任务执行", "Executor")}
                      <strong>
                        {modelOptions.find((option) => option.value === model)
                          ?.label ||
                          model ||
                          ui("尚未选择模型", "No model selected")}
                      </strong>
                    </span>
                    {needsReview && (
                      <label>
                        <AuditOutlined />
                        {ui("结果审核", "Independent reviewer")}
                        <Select
                          aria-label={ui("审核模型", "Reviewer model")}
                          value={reviewerModel || undefined}
                          options={
                            modelOptions.length
                              ? modelOptions
                              : model
                                ? [
                                    {
                                      value: model,
                                      label: model,
                                      disabled: false,
                                    },
                                  ]
                                : []
                          }
                          disabled={busy}
                          onChange={setReviewer}
                        />
                      </label>
                    )}
                  </div>
                  {thinkingAvailable && (
                    <ReasoningEffortControl
                      value={effort}
                      overridden={effort !== "medium"}
                      disabled={busy}
                      onChange={(value) => {
                        const selected = value ?? "medium";
                        setEffort(selected);
                        onReasoningEffortChange?.(selected);
                      }}
                    />
                  )}
                  {bootstrap?.budgets?.enabled && (
                    <div>
                      <TaskBudgetControl
                        canManage={bootstrap.canManage}
                        options={bootstrap.budgets}
                        profile={budgetProfile}
                        output={outputTokens}
                        serviceWindow={budgetWindow}
                        disabled={busy}
                        onProfile={(value) => {
                          setBudgetProfile(value);
                          setOutputTokens(undefined);
                        }}
                        onOutput={setOutputTokens}
                      />
                      <p className="business-flow-launch-note">
                        {ui(
                          "额度受所用模型窗口限制，每次请求分别计量；思考强度沿用上方所选档位。",
                          "Model windows bound this budget, counted per request. Thinking effort follows the selection above.",
                        )}
                      </p>
                    </div>
                  )}
                </SettingsTag>
                {isLegacy ? (
                  <Suspense fallback={<Spin />}>
                    <GenericWorkflowUploads
                      batchId={batchId}
                      model={model}
                      reasoningEffort={thinkingAvailable ? effort : undefined}
                      inputs={inputs}
                      onInputsChange={setInputs}
                      onActivityChange={setUploading}
                      disabled={busy}
                      uploadOnly
                      presentation="business-flow"
                      allowedRoles={version.definition.inputRequirements.map(
                        (input) => input.key,
                      )}
                      onCountChange={setMaterialCount}
                      onRestored={(result) => {
                        if (result.configuration) {
                          const valid = new Set(
                            result.items.map((item) => item.resourceId),
                          );
                          setInputs(
                            Object.fromEntries(
                              Object.entries(result.configuration.roles).filter(
                                ([, id]) =>
                                  valid.has(id) &&
                                  !result.unavailableResourceIds.includes(id),
                              ),
                            ),
                          );
                        }
                      }}
                    />
                  </Suspense>
                ) : version.definition.inputRequirements.length ? (
                  <div className="business-flow-launch-inputs">
                    <h3>{ui("任务资料", "Task data")}</h3>
                    {version.definition.inputRequirements.map((input) => (
                      <label
                        className="business-flow-launch-field"
                        key={input.key}
                        onCompositionStartCapture={() => {
                          candidateComposing.current = true;
                          clearTimeout(searchTimer.current);
                          searchTimer.current = undefined;
                          candidateRequest.current?.abort();
                          candidateRequest.current = null;
                          requestQuery.current = null;
                          readyQuery.current = null;
                        }}
                        onCompositionEndCapture={(event) => {
                          candidateComposing.current = false;
                          searchCandidates(
                            (event.target as HTMLInputElement).value,
                          );
                        }}
                      >
                        <span>
                          <DatabaseOutlined />
                          {input.label}
                          {input.required && (
                            <Tag variant="filled">{ui("必需", "Required")}</Tag>
                          )}
                        </span>
                        <Select
                          aria-label={`${input.label}：选择资料`}
                          mode={input.multiple ? "multiple" : undefined}
                          value={
                            input.multiple
                              ? Object.entries(inputs)
                                  .filter(
                                    ([key]) =>
                                      key === input.key ||
                                      key.startsWith(input.key + ":"),
                                  )
                                  .map(([, id]) => id)
                              : inputs[input.key]
                          }
                          showSearch={{
                            filterOption: false,
                            onSearch: searchCandidates,
                            searchValue:
                              openRole === input.key ? resourceSearch : "",
                          }}
                          open={openRole === input.key}
                          labelRender={({ value, label }) =>
                            candidateLabels.current.get(Number(value)) ??
                            label ??
                            ui("已选择资料", "Selected data")
                          }
                          allowClear={!input.required}
                          disabled={busy}
                          loading={resourceState === "loading"}
                          onOpenChange={(open) =>
                            openCandidates(input.key, open)
                          }
                          placeholder={ui(
                            "搜索资料名称或说明，空格分隔多个关键词",
                            "Search names or descriptions; separate required terms with spaces",
                          )}
                          options={resources.map((resource) => ({
                            value: resource.id,
                            label: resource.name,
                            description: resource.description,
                          }))}
                          optionRender={(option) => (
                            <ResourceSearchLabel
                              name={option.data.label}
                              description={option.data.description}
                              query={readyQuery.current ?? ""}
                            />
                          )}
                          notFoundContent={
                            resourceState === "loading" ? (
                              <Spin size="small" />
                            ) : (
                              resourceError ||
                              ui(
                                "没有匹配的资料，请调整关键词",
                                "No matching data; adjust your search",
                              )
                            )
                          }
                          onChange={(value: number | number[] | undefined) =>
                            setInputs((previous) => {
                              const next = { ...previous };
                              if (input.multiple) {
                                for (const key of Object.keys(next))
                                  if (
                                    key === input.key ||
                                    key.startsWith(input.key + ":")
                                  )
                                    delete next[key];
                                for (const id of Array.isArray(value)
                                  ? value
                                  : [])
                                  next[`${input.key}:${id}`] = id;
                              } else if (value === undefined)
                                delete next[input.key];
                              else if (typeof value === "number")
                                next[input.key] = value;
                              return next;
                            })
                          }
                        />
                        <small>
                          {input.description}
                          {input.requiredFields.length
                            ? ` ${ui("启动时核对字段：", "Fields checked on start: ")}${input.requiredFields.join("、")}`
                            : ""}
                        </small>
                      </label>
                    ))}
                  </div>
                ) : (
                  <p className="business-flow-launch-note">
                    {ui(
                      "本流程无需预先绑定固定资料。",
                      "This flow does not require fixed input bindings.",
                    )}
                  </p>
                )}
                {resourceError && (
                  <Alert
                    type="warning"
                    showIcon
                    title={resourceError}
                    action={
                      <Button size="small" onClick={retryCandidates}>
                        {ui("重试读取资料", "Retry data")}
                      </Button>
                    }
                  />
                )}
                <InputAdaptationReview
                  flowId={launch.definitionId}
                  request={inputRequest}
                  disabled={busy}
                  onChoices={setAdapterChoices}
                  onStatus={(key, ready, plan) =>
                    setPreparation({ key, ready, plan })
                  }
                />
                {missing.length > 0 && (
                  <p className="business-flow-launch-note is-required">
                    {ui("请补齐必需资料：", "Required inputs: ")}
                    {missing.map((input) => input.label).join("、")}
                  </p>
                )}
                {!bootstrap?.workerOnline && (
                  <Alert
                    type="info"
                    showIcon
                    title={ui(
                      "执行服务正在连接，已有资料选择会保留。",
                      "Connecting to the executor. Your input choices are retained.",
                    )}
                  />
                )}
              </div>
              <aside
                className="flow-launch-outline"
                aria-label={ui("本次执行路径", "Execution path")}
              >
                <details open={!compact}>
                  <summary>
                    {ui("执行路径", "Execution path")}
                    <span>
                      {version.definition.nodes.length} {ui("个节点", "nodes")}{" "}
                      <DownOutlined />
                    </span>
                  </summary>
                  <ol>
                    {version.definition.nodes.map((node, index) => (
                      <li key={node.id}>
                        <span className="flow-launch-node-number">
                          {index + 1}
                        </span>
                        <div>
                          <strong>{node.title}</strong>
                          {(node.review.ai || node.review.human) && (
                            <small>
                              {node.review.ai && (
                                <span>
                                  <AuditOutlined />{" "}
                                  {ui("独立审核", "Result review")}
                                </span>
                              )}
                              {node.review.human && (
                                <span>
                                  <UserOutlined />{" "}
                                  {ui("人工决定", "Human decision")}
                                </span>
                              )}
                            </small>
                          )}
                        </div>
                      </li>
                    ))}
                  </ol>
                </details>
                <p>
                  {ui(
                    "按发布版本执行，所有结果与审核意见保留在同一任务中。",
                    "Execution follows this version. Results and reviews stay in one task.",
                  )}
                </p>
              </aside>
            </div>
          </div>
          <footer>
            <span>
              {ui(
                uploading
                  ? "正在准备资料…"
                  : isLegacy
                    ? `已选 ${materialCount} 份资料`
                    : `已绑定 ${Object.keys(inputs).length} 份资料`,
                uploading
                  ? "Preparing data…"
                  : `${isLegacy ? materialCount : Object.keys(inputs).length} data sources selected`,
              )}
            </span>
            <Button
              disabled={busy}
              onClick={() => callbacks.current.onCancel()}
            >
              {ui("返回对话", "Back to conversation")}
            </Button>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              aria-label={ui("开始业务流", "Start business flow")}
              disabled={!canStart}
              loading={busy}
              onClick={() => void start()}
            >
              {ui("开始业务流", "Start flow")}
            </Button>
          </footer>
        </>
      ) : null}
    </section>
  );
}
