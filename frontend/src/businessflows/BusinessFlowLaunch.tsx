import {
  AuditOutlined,
  CloseOutlined,
  DatabaseOutlined,
  PlayCircleOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import { Alert, Button, Input, Select, Spin, Tag } from "antd";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type {
  AgentResource,
  BusinessFlowRun,
  BusinessFlowVersion,
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
import "./business-flows.css";

// Candidate reads are bounded metadata. Search is remote and shared by all roles.
const CANDIDATE_SEARCH_DELAY_MS = 280;
const MAX_CANDIDATE_LABELS = 256;
const GenericWorkflowUploads = lazy(
  () => import("../agent/GenericWorkflowUploads"),
);
export type BusinessFlowLaunchIntent = {
  definitionId: number;
  versionId: number;
  title: string;
  goal: string;
};
export default function BusinessFlowLaunch({
  launch,
  model,
  conversationId,
  onStarted,
  onCancel,
}: {
  launch: BusinessFlowLaunchIntent;
  model: string;
  conversationId?: number;
  onStarted: (flow: BusinessFlowRun) => void | Promise<void>;
  onCancel: () => void;
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
  const [reviewer, setReviewer] = useState<string>();
  const [batchId, setBatchId] = useState(() => createUuid().replace(/-/g, ""));
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [resources, setResources] = useState<AgentResource[]>([]);
  const [resourceState, setResourceState] = useState<
    "idle" | "loading" | "ready" | "error"
  >("idle");
  const [resourceError, setResourceError] = useState("");
  const [resourceSearch, setResourceSearch] = useState("");
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
    setInputs({});
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
  const needsReview = Boolean(
    version?.definition.nodes.some((node) => node.review.ai),
  );
  const reviewerModel = reviewer ?? model;
  const modelOptions = (bootstrap?.models ?? [])
    .filter((value) => value.allowAgent)
    .map((value) => ({
      value: value.alias,
      label: value.name,
      disabled: value.status !== "online",
    }));
  const missing =
    version?.definition.inputRequirements.filter(
      (input) => input.required && !inputs[input.key],
    ) ?? [];
  const loadCandidates = async (query = wantedQuery.current, force = false) => {
    if (!roleOpen.current || !alive.current) return;
    query = query.trim().slice(0, 120);
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
    const next = query.trim().slice(0, 120);
    setResourceSearch(query);
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
      setResourceSearch("");
      clearTimeout(searchTimer.current);
      searchTimer.current = undefined;
      void loadCandidates("");
    } else if (roleOpen.current === role) {
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
      inputs: Object.fromEntries(
        Object.entries(inputs).sort(([a], [b]) => a.localeCompare(b)),
      ),
      parameters: isLegacy ? { uploadBatchId: batchId } : {},
      ...(conversationId !== undefined ? { conversationId } : {}),
    };
    const fingerprint = JSON.stringify([launch.definitionId, body]);
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
          reason instanceof Error
            ? reason.message
            : "业务流暂未启动，请重试；同一次操作不会重复创建任务。",
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
    !missing.length &&
    goal.trim(),
  );
  return (
    <section
      className="business-flow-launch-panel"
      aria-label={ui("业务流启动准备", "Business flow launch preparation")}
    >
      <header>
        <span className="business-flow-launch-icon">
          <RobotOutlined />
        </span>
        <div>
          <small>
            {ui("业务流", "BUSINESS FLOW")}
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
          <div className="business-flow-launch-roles">
            <span>
              <RobotOutlined />
              {ui("执行智能体", "Executor")}
              <strong>
                {modelOptions.find((option) => option.value === model)?.label ||
                  model ||
                  ui("尚未选择模型", "No model selected")}
              </strong>
            </span>
            {needsReview && (
              <label>
                <AuditOutlined />
                {ui("独立审核智能体", "Independent reviewer")}
                <Select
                  aria-label={ui("审核模型", "Reviewer model")}
                  value={reviewerModel || undefined}
                  options={
                    modelOptions.length
                      ? modelOptions
                      : model
                        ? [{ value: model, label: model, disabled: false }]
                        : []
                  }
                  disabled={busy}
                  onChange={setReviewer}
                />
              </label>
            )}
          </div>
          {needsReview && (
            <p className="business-flow-launch-note">
              {ui(
                "审核使用独立的上下文和判断。可以复用同一模型，但不会继承执行智能体的批准权限，也不能代您作决定。",
                "The reviewer uses an independent context and judgment. It may use the same model, but cannot inherit executor approvals or decide for you.",
              )}
            </p>
          )}
          {isLegacy ? (
            <Suspense fallback={<Spin />}>
              <GenericWorkflowUploads
                batchId={batchId}
                model={model}
                inputs={inputs}
                onInputsChange={setInputs}
                onActivityChange={setUploading}
                disabled={busy}
                uploadOnly
                onRestored={(result) => {
                  if (result.configuration)
                    setInputs(result.configuration.roles);
                }}
              />
            </Suspense>
          ) : version.definition.inputRequirements.length ? (
            <div className="business-flow-launch-inputs">
              {version.definition.inputRequirements.map((input) => (
                <label className="business-flow-launch-field" key={input.key}>
                  <span>
                    <DatabaseOutlined />
                    {input.label}
                    {input.required && (
                      <Tag variant="filled">{ui("必需", "Required")}</Tag>
                    )}
                  </span>
                  <Select
                    aria-label={`${input.label}：选择资料`}
                    value={inputs[input.key]}
                    showSearch={{
                      filterOption: false,
                      onSearch: searchCandidates,
                      searchValue: openRole === input.key ? resourceSearch : "",
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
                    onOpenChange={(open) => openCandidates(input.key, open)}
                    placeholder={ui(
                      "输入名称搜索当前项目的授权资料",
                      "Search authorized project data by name",
                    )}
                    options={resources
                      .filter((resource) =>
                        (input.dataTypes as readonly string[]).includes(
                          resource.dataType,
                        ),
                      )
                      .map((resource) => ({
                        value: resource.id,
                        label: resource.name,
                      }))}
                    notFoundContent={
                      resourceState === "loading" ? (
                        <Spin size="small" />
                      ) : (
                        resourceError || ui("暂无匹配资料", "No matching data")
                      )
                    }
                    onChange={(value) =>
                      setInputs((previous) => {
                        const next = { ...previous };
                        if (value === undefined) delete next[input.key];
                        else next[input.key] = value;
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
          <footer>
            <span>
              {ui(
                "按已发布版本执行，审核与人工节点遵循流程定义。",
                "Execution follows the published version, including its review and human gates.",
              )}
            </span>
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
