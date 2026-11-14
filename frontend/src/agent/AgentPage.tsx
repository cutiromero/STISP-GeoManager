import PlatformActions from "./PlatformActions";
import BusinessFlowActivity from "../businessflows/BusinessFlowActivity";
import BusinessFlowMonitor from "../businessflows/BusinessFlowMonitor";
import { workflowModelActivity } from "../api/workflowModelStream";
import BusinessFlowLaunch, {
  type BusinessFlowLaunchIntent,
} from "../businessflows/BusinessFlowLaunch";
import type { BusinessFlowRun } from "../api/generated/types.gen";
import { businessFlowsApi } from "../api/businessFlows";
import { watchAgentRun } from "../api/watchAgentRun";
import {
  App,
  Alert,
  Button,
  Drawer,
  Input,
  Layout,
  Modal,
  Space,
  Switch,
  Tag,
  Typography,
  Upload,
} from "antd";
import {
  MessageOutlined,
  RobotOutlined,
  PlusOutlined,
  SendOutlined,
  StopOutlined,
  ArrowDownOutlined,
  CopyOutlined,
  EditOutlined,
  PaperClipOutlined,
  MenuOutlined,
  CloseOutlined,
  NodeIndexOutlined,
} from "@ant-design/icons";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import WorkspaceHeader from "../components/WorkspaceHeader";
import { useAppContext } from "../contexts/AppContext";
import { useProjectContext } from "../projects/ProjectContext";
import { useComputeText } from "../compute/ui";
import { agentApi } from "../api/agent";
import { ApiError } from "../api/client";
import {
  assertAgentRun,
  assertConversationDetail,
  assertConversationList,
  assertRunPoll,
} from "../api/agentResponse";
import { downloadResponseDiagnostics } from "../api/responseDiagnostics";
import type {
  AgentBudgetProfileId,
  AgentConversation,
  AgentRun,
  AgentEvent,
  AgentAttachment,
  AgentWorkflow,
  AgentResearchScenario,
} from "../api/generated/types.gen";
import { createUuid } from "../utils/uuid";
import { useAgentBootstrapState } from "./useAgentBootstrap";
import SafeMarkdown from "./SafeMarkdown";
import RunEvidence from "./RunEvidence";
import RunComputeTasks from "./RunComputeTasks";
import ComputeIntentCard from "./ComputeIntentCard";
import InteractionCard from "./InteractionCard";
import ResearchIntentCard from "./ResearchIntentCard";
import LiveActivity, { ActivityMark } from "./LiveActivity";
import AnswerPreview from "./AnswerPreview";
import ConversationDeleteButton from "./ConversationDeleteButton";
import RunProcess from "./RunProcess";
import {
  runActivity,
  workflowActivity,
  type LiveActivity as ActivityState,
} from "./agentActivity";
import { researchDemoLaunch } from "./researchDemoLaunch";
import AgentResizeHandle from "./AgentResizeHandle";
import {
  defaultToolPreferences,
  type ToolPreferences,
} from "./AgentToolSelection";
import useAgentLayout from "./useAgentLayout";
import ReasoningEffortControl, {
  type ReasoningEffort,
} from "./ReasoningEffortControl";
import "./agent.css";

const active = (r: AgentRun) =>
  ["queued", "running", "waiting_compute"].includes(r.status);
const waiting = (r: AgentRun) =>
  ["waiting_input", "waiting_review"].includes(r.status);
const titleRefreshDelays = [1500, 2500, 3000, 3000];

function mergeRun(old: AgentRun[], next: AgentRun): AgentRun[] {
  const updated = old.map((run) => {
    if (run.id === next.id) return next;
    if (
      next.researchIntent &&
      run.researchIntent?.originRunId === next.researchIntent.originRunId
    )
      return { ...run, researchIntent: next.researchIntent };
    return run;
  });
  return updated.some((run) => run.id === next.id)
    ? updated
    : [...updated, next];
}

const exampleQuestions = [
  "这个项目里有哪些可用资料？",
  "请概括当前项目的数据内容和质量。",
  "这个项目有哪些可用算法，分别适合什么任务？",
  "请根据我的研究目标推荐分析步骤。",
];

// Same-named conversations stay distinguishable by when they were last used.
function conversationTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  const time = date.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });
  return date.toDateString() === today.toDateString()
    ? `今天 ${time}`
    : `${date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" })} ${time}`;
}

export default function AgentPage() {
  const project = useProjectContext();
  const { user } = useAppContext();
  return <AgentWorkspace key={`${user?.id}:${project?.current}`} />;
}

function AgentWorkspace() {
  const ui = useComputeText();
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAppContext();
  const project = useProjectContext();
  const layout = useAgentLayout(`agent-layout:${user?.id ?? "anon"}:agent`);
  const { message } = App.useApp();
  const {
    bootstrap,
    status: bootstrapStatus,
    error: bootstrapError,
    retry: retryBootstrap,
  } = useAgentBootstrapState();
  const [conversations, setConversations] = useState<AgentConversation[]>([]);
  const [current, setCurrent] = useState<AgentConversation | null>(null);
  // New conversations use the available agent capability. Historical records
  // retain their server mode and permissions inside the same workspace.
  const mode =
    current?.mode ??
    (bootstrap?.canAgent === false && bootstrap.canChat ? "chat" : "agent");
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [computeActivities, setComputeActivities] = useState<
    Record<number, ActivityState>
  >({});
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [prompt, setPrompt] = useState("");
  const [businessLaunch, setBusinessLaunch] =
    useState<BusinessFlowLaunchIntent>();
  useEffect(() => {
    const value = location.state?.businessFlowLaunch as
      | BusinessFlowLaunchIntent
      | undefined;
    if (
      mode === "agent" &&
      value &&
      Number.isSafeInteger(value.definitionId) &&
      value.definitionId > 0 &&
      Number.isSafeInteger(value.versionId) &&
      value.versionId > 0 &&
      typeof value.title === "string" &&
      typeof value.goal === "string"
    ) {
      setBusinessLaunch(value);
      navigate(location.pathname, { replace: true, state: null });
    }
  }, [location.state, mode, navigate, location.pathname]);
  const demoLaunch = useRef(
    mode === "agent"
      ? researchDemoLaunch(location.state?.researchDemo, project?.current)
      : null,
  );
  const demoStarted = useRef(false);
  useEffect(() => {
    if (!demoLaunch.current) return;
    setPrompt(demoLaunch.current.prompt);
    navigate(location.pathname, { replace: true, state: null });
  }, []);
  useEffect(() => {
    const prefill = location.state?.query;
    if (mode === "agent" && typeof prefill === "string" && prefill.trim()) {
      setPrompt(prefill);
      navigate(location.pathname, { replace: true, state: null });
    }
  }, [mode, location.state, location.pathname, navigate]);
  const [model, setModel] = useState("");
  const [thinkingMode, setThinkingMode] = useState<"fast" | "deep">("fast");
  const budgetProfile = bootstrap?.budgets?.defaultProfile ?? "normal";
  const [effortOverride, setEffortOverride] = useState<ReasoningEffort>();
  const requestedEffort =
    thinkingMode === "deep" ? (effortOverride ?? "medium") : undefined;
  const [query, setQuery] = useState("");
  const [archived, setArchived] = useState(false);
  const [error, setError] = useState("");
  const [historyLoading, setHistoryLoading] =
    useState<AgentConversation | null>(null);
  const [historyFailure, setHistoryFailure] = useState<{
    conversation: AgentConversation;
    message: string;
  } | null>(null);
  const [pollFailure, setPollFailure] = useState("");
  const [pollAttempt, setPollAttempt] = useState(0);
  const [titleRefresh, setTitleRefresh] = useState<{
    conversationId: number;
    sequence: number;
    title: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [showLatest, setShowLatest] = useState(false);
  const [toolPreferences, setToolPreferences] = useState<ToolPreferences>(
    location.state?.knowledgeSelection
      ? {
          ...defaultToolPreferences,
          knowledgeSelection: location.state.knowledgeSelection,
        }
      : defaultToolPreferences,
  );
  const handoffSelection = useRef(location.state?.knowledgeSelection);
  const [attachments, setAttachments] = useState<AgentAttachment[]>([]);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const [internetEnabled, setInternetEnabled] = useState(false);
  const [rename, setRename] = useState<AgentConversation | null>(null);
  const [renameText, setRenameText] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [researchWorkflow, setResearchWorkflow] = useState<{
    runId: number;
    workflow: AgentWorkflow;
  }>();
  const historyButton = useRef<HTMLButtonElement>(null);
  const historyCloseButton = useRef<HTMLButtonElement>(null);
  const alive = useRef(true);
  const sequence = useRef(0);
  const attachmentConversation = useRef<{
    sequence: number;
    request: Promise<AgentConversation>;
  } | null>(null);
  const pendingAttachmentUploads = useRef(0);
  const listSequence = useRef(0);
  const restoredConversation = useRef(false);
  const viewport = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  const lastScrollTop = useRef(0);
  const pendingScroll = useRef<number | null>(null);
  const revealedBusinessGate = useRef("");
  const failedSubmission = useRef<{
    id: number;
    key: string;
    prompt: string;
    model: string;
    thinkingMode: "fast" | "deep";
    reasoningEffort?: ReasoningEffort;
    attachmentIds: number[];
    internetEnabled: boolean;
    budgetProfile?: AgentBudgetProfileId;
    maxOutputTokens?: number;
    toolPreferences: ToolPreferences;
    demoScenario?: AgentResearchScenario;
  } | null>(null);
  const running = runs.find(active);
  const waitingRun = [...runs]
    .reverse()
    .find((run) => waiting(run) && !run.businessFlow);
  const businessBlocked = runs.find(
    (run) =>
      run.businessFlow &&
      !["succeeded", "failed", "cancelled", "interrupted"].includes(
        run.businessFlow.status,
      ),
  );
  const monitoredFlow = (
    businessBlocked ?? [...runs].reverse().find((run) => run.businessFlow)
  )?.businessFlow;
  const [inspectedFlowNode, setInspectedFlowNode] = useState<{
    flowId: string;
    nodeId: string;
    request: number;
  }>();
  const [blockedFlowId, setBlockedFlowId] = useState<string>();
  const taskLocked = Boolean(running || waitingRun || businessBlocked);
  const reviewPending =
    waitingRun?.interaction?.status === "pending" &&
    waitingRun.interaction.kind === "review";
  const textAnswerRetry = useRef<{ fingerprint: string; key: string } | null>(
    null,
  );
  const revealWaitingQuestion = (focus = false) => {
    if (!waitingRun?.interaction) return;
    const box = viewport.current;
    const card = box?.querySelector<HTMLElement>(
      `[data-question-id="${waitingRun.interaction.questionId}"]`,
    );
    if (!box || !card) return;
    box.scrollTop +=
      card.getBoundingClientRect().top - box.getBoundingClientRect().top - 24;
    followLatest.current = true;
    if (focus)
      card
        .querySelector<HTMLElement>("input, textarea, button")
        ?.focus({ preventScroll: true });
  };
  const latestResearch = [...runs].reverse().find((run) => run.researchIntent);
  const latestResearchRunId = useRef<number | undefined>(undefined);
  latestResearchRunId.current = latestResearch?.id;
  const pendingResearch = [...runs]
    .reverse()
    .find(
      (run) =>
        run.researchIntent &&
        ["working", "waiting"].includes(runActivity(run).state),
    );
  const lastRun = runs[runs.length - 1];
  const sidebarRun =
    running ??
    waitingRun ??
    (latestResearch?.id === lastRun?.id ? latestResearch : pendingResearch) ??
    lastRun;
  const currentResearchWorkflow =
    researchWorkflow?.runId === latestResearch?.id
      ? researchWorkflow?.workflow
      : undefined;
  const sidebarWorkflow =
    sidebarRun?.id === latestResearch?.id ? currentResearchWorkflow : undefined;
  const sidebarActivity = sidebarWorkflow
    ? workflowActivity(sidebarWorkflow)
    : sidebarRun
      ? runActivity(
          sidebarRun,
          sidebarRun.id === running?.id ? events : [],
          computeActivities[sidebarRun.id],
          sidebarRun.id === running?.id ? pollFailure : undefined,
        )
      : undefined;
  const conversationSequence = sequence.current;
  const sidebarTitle =
    sidebarWorkflow?.goal ?? sidebarRun?.researchIntent?.goal;
  const canUse = mode === "agent" ? bootstrap?.canAgent : bootstrap?.canChat;
  const models = (bootstrap?.models ?? []).filter(
    (m) => mode === "chat" || m.allowAgent,
  );
  const modelOnline = models.some(
    (m) => m.alias === model && m.status === "online",
  );
  const selectedModel = models.find((item) => item.alias === model);
  const deepThinkingAvailable =
    Boolean(bootstrap?.thinkingEnabled) &&
    Boolean(selectedModel?.supportsThinking);
  const modeLabel = ui("智能体", "Agent");
  const openBusinessFlows = () => navigate("/business-flows");
  const attachmentsAvailable = Boolean(bootstrap?.allowAttachments);
  const internetAvailable = Boolean(bootstrap?.internetEnabled);
  const conversationStorageKey = `agent-conversation:${user?.id ?? "anon"}:${project?.current ?? "1"}:agent`;
  const accessRejected =
    canUse === false ||
    bootstrapStatus === "unauthenticated" ||
    bootstrapStatus === "forbidden";

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      sequence.current++;
    };
  }, []);
  const clearRestrictedState = () => {
    sequence.current++;
    listSequence.current++;
    setResearchWorkflow(undefined);
    setRuns([]);
    setComputeActivities({});
    setEvents([]);
    setCurrent(null);
    setConversations([]);
    setHistoryLoading(null);
    setHistoryFailure(null);
    setPollFailure("");
  };
  const report = (e: unknown) => {
    if (!alive.current) return;
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
      clearRestrictedState();
    }
    if (
      alive.current &&
      !(e instanceof DOMException && e.name === "AbortError")
    )
      setError(
        e instanceof Error ? e.message : ui("操作失败", "Operation failed"),
      );
  };
  const updateRun = (next: AgentRun, replace = false) => {
    try {
      assertAgentRun(next);
      if (!replace && current && next.conversationId !== current.id)
        throw new Error("返回的任务与当前对话不一致，当前聊天记录已保留。");
      setRuns((old) => mergeRun(replace ? [] : old, next));
      return true;
    } catch (reason) {
      report(reason);
      return false;
    }
  };
  const acceptBusinessFlow = (flow: BusinessFlowRun) => {
    if (!alive.current || String(flow.projectId) !== project?.current) return;
    const status: AgentRun["status"] =
      flow.status === "waiting_approval"
        ? "waiting_review"
        : flow.status === "paused"
          ? "waiting_input"
          : ["succeeded", "failed", "cancelled", "interrupted"].includes(
                flow.status,
              )
            ? (flow.status as AgentRun["status"])
            : "waiting_compute";
    setRuns((old) =>
      old.map((run) =>
        run.id === flow.runId
          ? {
              ...run,
              businessFlow: flow,
              status,
              detail:
                flow.nodes.find((node) => node.nodeId === flow.currentNode)
                  ?.human.reason || run.detail,
            }
          : run,
      ),
    );
  };
  const startedBusinessFlow = async (flow: BusinessFlowRun) => {
    const owned = sequence.current;
    if (!flow.conversationId || !flow.runId)
      throw new Error("业务流缺少真实会话绑定");
    const detail = await agentApi.detail(flow.conversationId);
    if (!alive.current || sequence.current !== owned) return;
    assertConversationDetail(detail);
    if (
      String(detail.conversation.projectId) !== project?.current ||
      detail.conversation.mode !== "agent"
    )
      throw new Error("业务流与当前项目不一致");
    restoredConversation.current = true;
    setCurrent(detail.conversation);
    setRuns(detail.runs);
    setEvents([]);
    setBusinessLaunch(undefined);
    setPrompt("");
    try {
      sessionStorage.setItem(
        conversationStorageKey,
        String(flow.conversationId),
      );
    } catch {}
    void refreshList();
  };
  const refreshList = async () => {
    const seq = ++listSequence.current;
    try {
      const modes = (["agent", "chat"] as const).filter((item) =>
        item === "agent" ? bootstrap?.canAgent : bootstrap?.canChat,
      );
      const pages = await Promise.all(
        modes.map((item) => agentApi.conversations(item, query, archived)),
      );
      pages.forEach(assertConversationList);
      const items = [
        ...new Map(
          pages.flatMap((page) => page.items).map((item) => [item.id, item]),
        ).values(),
      ].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt) || 0);
      if (alive.current && seq === listSequence.current) {
        setConversations(items);
        return items;
      }
    } catch (e) {
      if (alive.current && seq === listSequence.current) report(e);
    }
  };
  useEffect(() => {
    if (accessRejected) {
      clearRestrictedState();
      return;
    }
    if (canUse !== true) return;
    const timer = setTimeout(() => {
      void refreshList();
    }, 200);
    return () => clearTimeout(timer);
  }, [
    bootstrap?.canAgent,
    bootstrap?.canChat,
    canUse,
    accessRejected,
    query,
    archived,
  ]);
  useEffect(() => {
    if (!bootstrap) return;
    const candidates = bootstrap.models.filter(
      (m) => mode === "chat" || m.allowAgent,
    );
    if (candidates.some((item) => item.alias === model)) return;
    const defaultModel =
      mode === "agent"
        ? bootstrap.defaultAgentModel
        : bootstrap.defaultChatModel;
    const demoModel = demoLaunch.current
      ? (candidates.find(
          (entry) => entry.alias === defaultModel && entry.status === "online",
        ) ?? candidates.find((entry) => entry.status === "online"))
      : undefined;
    setModel(
      demoModel?.alias ??
        (candidates.some((m) => m.alias === defaultModel)
          ? defaultModel
          : candidates[0]?.alias || ""),
    );
  }, [bootstrap, mode, model, user?.id]);
  useEffect(() => {
    setThinkingMode(deepThinkingAvailable ? "deep" : "fast");
  }, [deepThinkingAvailable]);
  useEffect(() => {
    if (!running || historyLoading) return;
    let disposed = false;
    const controller = new AbortController();
    const pollSequence = sequence.current;
    void watchAgentRun(
      running,
      bootstrap?.runStreamingEnabled ? agentApi : { poll: agentApi.poll },
      controller.signal,
      (data) => {
        if (disposed) return;
        setRuns((old) => mergeRun(old, data.run));
        setPollFailure("");
        setEvents((old) =>
          [
            ...old,
            ...data.events.filter(
              (e) =>
                !["answer_preview", "answer_delta"].includes(e.kind) &&
                !old.some((p) => p.id === e.id),
            ),
          ].slice(-80),
        );
        if (!active(data.run)) {
          void refreshList().then((items) => {
            const conversation = items?.find(
              (item) => item.id === data.run.conversationId,
            );
            if (
              data.run.status === "succeeded" &&
              runs.length === 1 &&
              runs[0]?.id === data.run.id &&
              conversation &&
              alive.current &&
              sequence.current === pollSequence
            )
              setTitleRefresh({
                conversationId: conversation.id,
                sequence: pollSequence,
                title: conversation.title,
              });
          });
        }
      },
      (error) => {
        if (!disposed)
          setPollFailure(
            error instanceof Error ? error.message : "正在恢复连接",
          );
      },
    ).catch((e) => {
      if (disposed) return;
      if (e instanceof Error && e.name === "AbortError") {
        setPollFailure("实时连接已中断，请重试更新当前任务状态");
        return;
      }
      if (e instanceof ApiError && [401, 403, 404].includes(e.status)) {
        clearRestrictedState();
        report(e);
      } else {
        setPollFailure(
          e instanceof Error
            ? e.message
            : "暂时无法更新回答，当前聊天记录已保留。",
        );
      }
    });
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [
    running?.id,
    historyLoading,
    pollAttempt,
    bootstrap?.runStreamingEnabled,
  ]);
  useEffect(() => {
    if (
      !titleRefresh ||
      accessRejected ||
      current?.id !== titleRefresh.conversationId
    )
      return;
    let disposed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout>;
    const valid = () =>
      !disposed && alive.current && sequence.current === titleRefresh.sequence;
    const refreshTitle = async () => {
      if (!valid()) return;
      try {
        // Titles arrive after the answer; fetch metadata, not full run history.
        const data = await agentApi.conversations(mode, "", false);
        if (!valid()) return;
        assertConversationList(data);
        const next = data.items.find(
          (item) => item.id === titleRefresh.conversationId,
        );
        if (!next) return;
        setConversations((old) =>
          old.map((item) => (item.id === next.id ? next : item)),
        );
        setCurrent((old) => (old?.id === next.id ? next : old));
        if (next.title !== titleRefresh.title) return;
      } catch (error) {
        if (!valid()) return;
        if (
          error instanceof ApiError &&
          [401, 403, 404].includes(error.status)
        ) {
          if (error.status !== 404) report(error);
          return;
        }
      }
      if (valid() && attempt < titleRefreshDelays.length)
        timer = setTimeout(refreshTitle, titleRefreshDelays[attempt++]);
    };
    timer = setTimeout(refreshTitle, titleRefreshDelays[attempt++]);
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [titleRefresh, current?.id, accessRejected]);
  useLayoutEffect(() => {
    const box = viewport.current;
    if (box && pendingScroll.current !== null) {
      const question = box.querySelector<HTMLElement>(
        `[data-run-id="${pendingScroll.current}"]`,
      );
      if (question) {
        box.scrollTop +=
          question.getBoundingClientRect().top -
          box.getBoundingClientRect().top -
          16;
        pendingScroll.current = null;
        followLatest.current =
          box.scrollHeight - box.scrollTop - box.clientHeight < 96;
        return;
      }
    }
    if (box && followLatest.current) box.scrollTop = box.scrollHeight;
  }, [runs, events]);
  useLayoutEffect(() => {
    revealWaitingQuestion();
  }, [waitingRun?.interaction?.questionId, waitingRun?.interaction?.revision]);
  useLayoutEffect(() => {
    const run = [...runs]
      .reverse()
      .find((item) => item.businessFlow?.status === "waiting_approval");
    const flow = run?.businessFlow;
    const node = flow?.nodes.find((item) => item.nodeId === flow.currentNode);
    if (!run || !flow || !node?.human.required) {
      revealedBusinessGate.current = "";
      return;
    }
    const key = `${current?.id}:${run.id}:${flow.currentNode}:${node.attempt}`;
    if (revealedBusinessGate.current === key) return;
    const box = viewport.current;
    const turn = box?.querySelector<HTMLElement>(`[data-run-id="${run.id}"]`);
    const decision = turn?.querySelector<HTMLElement>(
      ".business-flow-human-review, .business-flow-human-decision",
    );
    if (!box || !decision) return;
    followLatest.current = false;
    pendingScroll.current = null;
    box.scrollTop +=
      decision.getBoundingClientRect().top -
      box.getBoundingClientRect().top -
      24;
    lastScrollTop.current = box.scrollTop;
    revealedBusinessGate.current = key;
    setShowLatest(box.scrollHeight - box.scrollTop - box.clientHeight >= 96);
  }, [current?.id, runs]);
  useEffect(() => {
    const container = viewport.current;
    if (!container) return;
    const observer = new ResizeObserver(() => {
      const box = viewport.current;
      if (box && followLatest.current) box.scrollTop = box.scrollHeight;
    });
    observer.observe(container);
    for (const turn of container.querySelectorAll(".agent-turn"))
      observer.observe(turn);
    return () => observer.disconnect();
  }, [runs.length]);

  const open = async (
    c: AgentConversation,
    preloaded?: Awaited<ReturnType<typeof agentApi.detail>>,
  ) => {
    setBusinessLaunch(undefined);
    const seq = ++sequence.current;
    setHistoryLoading(c);
    setHistoryFailure(null);
    setError("");
    setShowHistory(false);
    failedSubmission.current = null;
    try {
      const detail = preloaded ?? (await agentApi.detail(c.id));
      if (alive.current && seq === sequence.current) {
        assertConversationDetail(detail);
        if (
          detail.conversation.id !== c.id ||
          detail.conversation.projectId !== c.projectId ||
          detail.conversation.mode !== c.mode
        )
          throw new Error(
            "返回的历史记录与所选会话不一致，当前聊天记录已保留。",
          );
        setResearchWorkflow(undefined);
        revealedBusinessGate.current = "";
        followLatest.current = true;
        setComputeActivities({});
        setEvents([]);
        setPollFailure("");
        setCurrent(detail.conversation);
        setRuns(detail.runs);
        setToolPreferences({
          ...defaultToolPreferences,
          ...(handoffSelection.current
            ? { knowledgeSelection: handoffSelection.current }
            : {}),
        });
        try {
          sessionStorage.setItem(
            conversationStorageKey,
            String(detail.conversation.id),
          );
        } catch {
          // Session storage can be disabled by strict browser privacy settings.
        }
      }
    } catch (e) {
      if (!alive.current || seq !== sequence.current) return;
      if (e instanceof DOMException && e.name === "AbortError") return;
      if (e instanceof ApiError && [401, 403].includes(e.status)) {
        report(e);
      } else if (e instanceof ApiError && e.status === 404) {
        if (current?.id === c.id) {
          setCurrent(null);
          setRuns([]);
          setEvents([]);
          setComputeActivities({});
          setResearchWorkflow(undefined);
        }
        setConversations((old) => old.filter((item) => item.id !== c.id));
        setError(e.message);
      } else {
        setHistoryFailure({
          conversation: c,
          message: e instanceof Error ? e.message : "暂时无法读取历史记录。",
        });
      }
    } finally {
      if (alive.current && seq === sequence.current) setHistoryLoading(null);
    }
  };
  useEffect(() => {
    const query = new URLSearchParams(location.search);
    const conversationId = Number(query.get("conversationId"));
    if (!canUse || !Number.isSafeInteger(conversationId) || conversationId < 1)
      return;
    if (
      query.get("projectTagId") &&
      query.get("projectTagId") !== project?.current
    ) {
      setError("会话链接不属于当前项目。");
      return;
    }
    restoredConversation.current = true;
    const seq = ++sequence.current;
    let stopped = false;
    void agentApi
      .detail(conversationId)
      .then((detail) => {
        if (stopped || !alive.current || sequence.current !== seq) return;
        assertConversationDetail(detail);
        if (
          String(detail.conversation.projectId) !== project?.current ||
          !(detail.conversation.mode === "agent"
            ? bootstrap?.canAgent
            : bootstrap?.canChat)
        )
          throw new Error("会话不属于当前项目或模块。");
        const runId = Number(query.get("runId"));
        if (detail.runs.some((run) => run.id === runId))
          pendingScroll.current = runId;
        void open(detail.conversation, detail);
      })
      .catch((error) => {
        if (!stopped && alive.current && sequence.current === seq)
          report(error);
      });
    return () => {
      stopped = true;
    };
  }, [
    canUse,
    location.search,
    project?.current,
    bootstrap?.canAgent,
    bootstrap?.canChat,
  ]);
  useEffect(() => {
    if (
      !canUse ||
      businessLaunch ||
      demoLaunch.current ||
      restoredConversation.current ||
      current ||
      conversations.length === 0
    )
      return;
    // Restore once after the first list response. New conversation and
    // archive/delete actions must not immediately reopen the old session.
    restoredConversation.current = true;
    let preferredId = 0;
    try {
      preferredId = Number(sessionStorage.getItem(conversationStorageKey) || 0);
    } catch {
      preferredId = 0;
    }
    const preferred =
      conversations.find((item) => item.id === preferredId) ?? conversations[0];
    if (preferred) void open(preferred);
  }, [canUse, businessLaunch, conversationStorageKey, conversations, current]);
  const send = async (text = prompt, demoScenario?: AgentResearchScenario) => {
    if (
      !canUse ||
      busy ||
      historyLoading ||
      businessBlocked ||
      running ||
      uploadingAttachment ||
      !text.trim() ||
      !modelOnline
    )
      return;
    if (waitingRun?.interaction?.status === "pending" && !demoScenario) {
      const question = waitingRun.interaction;
      if (question.kind === "review") {
        message.info(
          "请在当前审核卡中明确选择，再确认并继续；补充意见可以填在卡片下方。",
        );
        return;
      }
      const seq = sequence.current;
      const fingerprint = JSON.stringify([
        waitingRun.id,
        question.questionId,
        question.revision,
        text,
      ]);
      if (textAnswerRetry.current?.fingerprint !== fingerprint) {
        textAnswerRetry.current = { fingerprint, key: createUuid() };
      }
      setBusy(true);
      setError("");
      try {
        const next = await agentApi.answerInteraction(waitingRun.id, {
          action: "answer",
          questionId: question.questionId,
          revision: question.revision,
          submissionKey: textAnswerRetry.current.key,
          answers: {},
          text,
        });
        if (!alive.current || seq !== sequence.current) return;
        if (!updateRun(next)) return;
        setPrompt("");
        setEvents([]);
        followLatest.current = true;
        void refreshList();
      } catch (failure) {
        report(failure);
        try {
          const latest = await agentApi.poll(waitingRun.id);
          if (alive.current && seq === sequence.current) {
            assertRunPoll(latest);
            updateRun(latest.run);
          }
        } catch (reason) {
          if (alive.current && seq === sequence.current) report(reason);
        }
      } finally {
        if (alive.current && seq === sequence.current) setBusy(false);
      }
      return;
    }
    const genericRun = !demoScenario
      ? [...runs].reverse().find((item) => item.researchIntent)?.researchIntent
      : undefined;
    if (
      genericRun?.scenario === "geology_generic" &&
      (["clarifying", "waiting_approval"].includes(genericRun.status) ||
        /^(进度|当前进度|查看进度|结果|查看结果|查看报告)$/.test(text.trim()))
    ) {
      const seq = sequence.current;
      setBusy(true);
      setError("");
      try {
        const next = await agentApi.updateResearchIntent(
          genericRun.originRunId,
          {
            action: "answer",
            revision: genericRun.revision,
            answer: text,
          },
        );
        if (alive.current && seq === sequence.current) {
          updateRun(next);
          setPrompt("");
        }
      } catch (reason) {
        report(reason);
      } finally {
        if (alive.current && seq === sequence.current) setBusy(false);
      }
      return;
    }
    const clarification = !demoScenario
      ? [...runs]
          .reverse()
          .find((run) => run.researchIntent?.status === "clarifying")
          ?.researchIntent
      : undefined;
    setBusy(true);
    setError("");
    const seq = sequence.current;
    try {
      const c = demoScenario
        ? await agentApi.create(mode)
        : (current ?? (await agentApi.create(mode)));
      if (!alive.current || seq !== sequence.current) return;
      setCurrent(c);
      try {
        sessionStorage.setItem(conversationStorageKey, String(c.id));
      } catch {
        // Session storage is only a UX hint; the server remains authoritative.
      }
      const previous = failedSubmission.current;
      if (clarification) {
        const run = await agentApi.updateResearchIntent(
          clarification.originRunId,
          {
            action: "answer",
            revision: clarification.revision,
            answer: text,
          },
        );
        if (!alive.current || seq !== sequence.current) return;
        pendingScroll.current = run.id;
        if (!updateRun(run)) return;
        setPrompt("");
        setEvents([]);
        void refreshList();
        return;
      }
      const same =
        previous?.id === c.id &&
        previous.prompt === text &&
        previous.model === model &&
        previous.demoScenario === demoScenario &&
        previous.thinkingMode === thinkingMode &&
        previous.reasoningEffort === requestedEffort &&
        JSON.stringify(previous.attachmentIds) ===
          JSON.stringify(attachments.map((item) => item.id)) &&
        previous.internetEnabled === (internetEnabled && internetAvailable) &&
        previous.budgetProfile ===
          (bootstrap?.budgets?.enabled ? budgetProfile : undefined) &&
        previous.maxOutputTokens === undefined &&
        JSON.stringify(previous.toolPreferences) ===
          JSON.stringify(toolPreferences);
      const submission = same
        ? previous
        : {
            id: c.id,
            key: demoScenario
              ? (demoLaunch.current?.token ?? createUuid())
              : createUuid(),
            prompt: text,
            model,
            thinkingMode,
            reasoningEffort: requestedEffort,
            attachmentIds: attachments.map((item) => item.id),
            internetEnabled: internetEnabled && internetAvailable,
            budgetProfile: bootstrap?.budgets?.enabled
              ? budgetProfile
              : undefined,
            maxOutputTokens: undefined,
            toolPreferences,
            demoScenario,
          };
      failedSubmission.current = submission;
      const run = await agentApi.submit(c.id, {
        model,
        prompt: text,
        idempotencyKey: submission.key,
        ...(demoScenario ? { demoScenario } : {}),
        ...(bootstrap?.budgets?.enabled
          ? { budgetProfile, maxOutputTokens: undefined }
          : {}),
        thinkingMode,
        reasoningEffort: requestedEffort,
        resourceIds: [],
        ...(mode === "agent" ? toolPreferences : {}),
        attachmentIds: attachments.map((item) => item.id),
        internetEnabled: internetEnabled && internetAvailable,
      });
      if (!alive.current || seq !== sequence.current) return;
      pendingScroll.current = run.id;
      if (!updateRun(run, Boolean(demoScenario))) return;
      setPrompt("");
      setEvents([]);
      failedSubmission.current = null;
      handoffSelection.current = null;
      void refreshList();
    } catch (e) {
      report(e);
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  useEffect(() => {
    if (
      !demoLaunch.current ||
      demoStarted.current ||
      !canUse ||
      !modelOnline ||
      busy
    )
      return;
    demoStarted.current = true;
    restoredConversation.current = true;
    void send(demoLaunch.current.prompt, demoLaunch.current.scenario);
  }, [canUse, modelOnline, busy]);
  const reset = () => {
    restoredConversation.current = true;
    sequence.current++;
    demoLaunch.current = null;
    setCurrent(null);
    setResearchWorkflow(undefined);
    followLatest.current = true;
    setRuns([]);
    setComputeActivities({});
    setEvents([]);
    setError("");
    setHistoryLoading(null);
    setHistoryFailure(null);
    setPollFailure("");
    setPrompt("");
    setBusinessLaunch(undefined);
    setAttachments([]);
    setInternetEnabled(false);
    setToolPreferences(defaultToolPreferences);
    handoffSelection.current = null;
    failedSubmission.current = null;
    try {
      sessionStorage.removeItem(conversationStorageKey);
    } catch {
      // Ignore unavailable browser storage.
    }
  };
  const uploadAttachment = async (file: File) => {
    if (
      !attachmentsAvailable ||
      uploadingAttachment ||
      !canUse ||
      current?.archived
    )
      return;
    setUploadingAttachment(true);
    pendingAttachmentUploads.current++;
    const seq = sequence.current;
    try {
      if (!current && attachmentConversation.current?.sequence !== seq) {
        attachmentConversation.current = {
          sequence: seq,
          request: agentApi.create(mode),
        };
      }
      const conversation =
        current ?? (await attachmentConversation.current!.request);
      if (!alive.current || seq !== sequence.current) return;
      if (!current) {
        setCurrent(conversation);
        void refreshList();
      }
      const item = await agentApi.uploadAttachment(conversation.id, file);
      if (!alive.current || seq !== sequence.current) return;
      setAttachments((old) => [
        ...old.filter((entry) => entry.id !== item.id),
        item,
      ]);
      message.success(ui("附件已上传", "Attachment uploaded"));
    } catch (e) {
      report(e);
    } finally {
      pendingAttachmentUploads.current--;
      if (!pendingAttachmentUploads.current) {
        attachmentConversation.current = null;
        setUploadingAttachment(false);
      }
    }
  };
  const copy = async (text: string) => {
    try {
      const { copyText } = await import("../utils/clipboard");
      await copyText(text);
      message.success(ui("已复制", "Copied"));
    } catch (e) {
      report(e);
    }
  };
  const stopResponse = async () => {
    if (!running || stopping) return;
    const seq = sequence.current;
    setStopping(true);
    try {
      if (running.businessFlow) {
        const result = await businessFlowsApi.cancel(running.businessFlow.id);
        if (alive.current && seq === sequence.current)
          acceptBusinessFlow(result);
        return;
      }
      const result = await agentApi.cancel(running.id);
      if (alive.current && seq === sequence.current) updateRun(result);
    } catch (error) {
      report(error);
    } finally {
      if (alive.current) setStopping(false);
    }
  };
  const statusLabel: Record<string, string> = {
    queued: ui("排队中", "Queued"),
    running: ui("生成中", "Generating"),
    waiting_input: ui("等待您回答", "Waiting for your answer"),
    waiting_review: ui("等待您审核", "Waiting for your review"),
    waiting_compute: ui("算法计算中", "Calculating"),
    succeeded: ui("已完成", "Completed"),
    failed: ui("未完成", "Incomplete"),
    cancelled: ui("已停止", "Stopped"),
    interrupted: ui("已中断", "Interrupted"),
  };
  const sidebar = (
    <aside
      id="agent-conversation-sidebar"
      aria-label={ui("会话侧栏", "Conversation sidebar")}
      className="agent-sidebar"
      style={{ width: layout.narrow ? undefined : layout.sidebar }}
    >
      <div className="agent-sidebar-heading">
        <span className="agent-sidebar-symbol">
          <RobotOutlined />
        </span>
        <div>
          <Typography.Title level={4}>{ui("智能体", "Agent")}</Typography.Title>
          <span>{ui("项目研究助手", "Research workspace")}</span>
        </div>
        <Button
          ref={historyCloseButton}
          className="agent-sidebar-close"
          type="text"
          icon={<CloseOutlined />}
          aria-label={ui("关闭会话列表", "Close conversations")}
          onClick={() => setShowHistory(false)}
        />
      </div>
      <Button
        className="agent-new-conversation"
        block
        icon={<PlusOutlined />}
        disabled={!canUse || busy}
        onClick={reset}
      >
        {ui("新建会话", "New conversation")}
      </Button>
      <Input.Search
        aria-label={ui("搜索会话", "Search conversations")}
        placeholder={ui("搜索会话", "Search conversations")}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="agent-history-heading">
        <span>{ui("会话记录", "Conversations")}</span>
        <Space size={6}>
          <Switch
            size="small"
            aria-label={ui("查看已归档会话", "Show archived conversations")}
            checked={archived}
            onChange={setArchived}
          />
          {ui("已归档", "Archived")}
        </Space>
      </div>
      <div className="agent-history">
        {conversations.map((c) => (
          <div
            className={`agent-history-item ${current?.id === c.id ? "selected" : ""}`}
            key={c.id}
          >
            <button
              className="agent-history-title"
              title={c.title}
              aria-current={current?.id === c.id ? "true" : undefined}
              disabled={busy}
              onClick={() => void open(c)}
            >
              {current?.id === c.id && sidebarActivity && (
                <ActivityMark state={sidebarActivity.state} />
              )}
              {c.title}
              <time className="agent-history-time" dateTime={c.updatedAt}>
                {conversationTime(c.updatedAt)}
              </time>
            </button>
            <Space size={0} className="agent-history-actions">
              <Button
                size="small"
                type="text"
                aria-label={ui("重命名", "Rename")}
                icon={<EditOutlined />}
                onClick={() => {
                  setTitleRefresh(null);
                  setRename(c);
                  setRenameText(c.title);
                }}
              />
              <Button
                size="small"
                type="text"
                onClick={() =>
                  void agentApi
                    .update(c.id, { archived: !c.archived })
                    .then(() => {
                      if (current?.id === c.id) reset();
                      return refreshList();
                    })
                    .catch(report)
                }
              >
                {c.archived ? ui("恢复", "Restore") : ui("归档", "Archive")}
              </Button>
              <ConversationDeleteButton
                conversation={c}
                onDeleted={async () => {
                  if (current?.id === c.id) reset();
                  await refreshList();
                }}
                onError={report}
              />
            </Space>
          </div>
        ))}
      </div>
      {canUse && sidebarActivity && (
        <section className="agent-sidebar-task" aria-label="当前任务">
          <span className="agent-sidebar-task-eyebrow">当前任务</span>
          <LiveActivity
            activity={sidebarActivity}
            title={sidebarTitle}
            compact
          />
        </section>
      )}
      {bootstrap?.canManage && (
        <Button onClick={() => navigate("/admin/agent")}>
          {ui("智能体管理", "Agent settings")}
        </Button>
      )}
    </aside>
  );
  return (
    <Layout className="agent-shell">
      <WorkspaceHeader
        activeTab="warning"
        canBrowseData={Boolean(user?.permissions.canBrowseData)}
      />
      <div className="agent-workspace">
        {layout.narrow ? (
          <Drawer
            placement="left"
            open={showHistory}
            onClose={() => setShowHistory(false)}
            closable={false}
            size="default"
            styles={{
              wrapper: { width: "min(320px, calc(100vw - 44px))" },
              body: { padding: 16 },
            }}
            classNames={{ root: "agent-history-drawer" }}
            aria-label={ui("会话侧栏", "Conversation sidebar")}
            afterOpenChange={(open) => {
              if (open) historyCloseButton.current?.focus();
              else historyButton.current?.focus();
            }}
          >
            {sidebar}
          </Drawer>
        ) : (
          sidebar
        )}
        {!layout.narrow && (
          <AgentResizeHandle
            orientation="vertical"
            label={ui("调整会话侧栏宽度", "Resize conversation sidebar")}
            hint={ui(
              "左右拖动或按方向键调整，双击恢复",
              "Drag or use arrow keys to resize; double-click to reset",
            )}
            controls="agent-conversation-sidebar"
            value={layout.sidebar}
            min={layout.sidebarMin}
            max={layout.sidebarMax}
            defaultValue={layout.defaults.sidebar}
            onChange={layout.setSidebar}
          />
        )}
        <main
          className={`agent-main${businessLaunch && canUse ? " is-preparing-flow" : ""}`}
          inert={showHistory && layout.narrow}
        >
          <div className="agent-toolbar">
            <div className="agent-toolbar-heading">
              <Button
                ref={historyButton}
                className="agent-history-toggle"
                type="text"
                icon={<MenuOutlined />}
                aria-label={ui("会话", "Conversations")}
                aria-expanded={showHistory}
                aria-controls="agent-conversation-sidebar"
                onClick={() => setShowHistory(!showHistory)}
              >
                {ui("会话", "History")}
              </Button>
              <div className="agent-conversation-heading">
                <span>{modeLabel}</span>
                <strong title={current?.title}>
                  {current?.title ?? modeLabel}
                </strong>
              </div>
            </div>
            <Tag className="agent-project-badge">
              {project?.projects.find((p) => String(p.id) === project.current)
                ?.name ?? ui("当前项目", "Current project")}
            </Tag>
          </div>
          {businessLaunch && canUse && (
            <BusinessFlowLaunch
              launch={businessLaunch}
              model={model}
              reasoningEffort={effortOverride ?? "medium"}
              onReasoningEffortChange={(value) => {
                setEffortOverride(value);
                setThinkingMode("deep");
              }}
              compact={layout.narrow}
              conversationId={
                current?.archived || taskLocked ? undefined : current?.id
              }
              onStarted={startedBusinessFlow}
              onCancel={() => setBusinessLaunch(undefined)}
            />
          )}
          {error && (
            <Alert
              title={error}
              type="error"
              showIcon
              closable
              onClose={() => setError("")}
              action={
                <Button size="small" onClick={downloadResponseDiagnostics}>
                  {ui("下载异常诊断", "Download diagnostics")}
                </Button>
              }
            />
          )}
          {historyLoading && (
            <Typography.Text role="status" aria-live="polite">
              {ui("正在加载会话：", "Loading conversation: ")}
              {historyLoading.title}
            </Typography.Text>
          )}
          {historyFailure && (
            <Alert
              type="warning"
              showIcon
              title={ui(
                "暂时无法加载所选历史",
                "Unable to load selected history",
              )}
              description={
                <>
                  {historyFailure.message}
                  <p>
                    {ui(
                      "当前聊天记录已保留，请重试加载。",
                      "Current messages are retained. Retry loading the history.",
                    )}
                  </p>
                </>
              }
              action={
                <Space wrap>
                  <Button
                    size="small"
                    onClick={() => void open(historyFailure.conversation)}
                  >
                    {ui("重试加载历史", "Retry history")}
                  </Button>
                  <Button size="small" onClick={downloadResponseDiagnostics}>
                    {ui("下载异常诊断", "Download diagnostics")}
                  </Button>
                </Space>
              }
            />
          )}
          {pollFailure && (
            <Alert
              type="warning"
              showIcon
              title={pollFailure}
              description={ui(
                "当前回答已保留，正在重新连接。",
                "The current answer is retained. Reconnecting.",
              )}
              action={
                <Space wrap>
                  <Button
                    size="small"
                    onClick={() => setPollAttempt((value) => value + 1)}
                  >
                    {ui("重试更新回答", "Retry answer update")}
                  </Button>
                  <Button size="small" onClick={downloadResponseDiagnostics}>
                    {ui("下载异常诊断", "Download diagnostics")}
                  </Button>
                </Space>
              }
            />
          )}
          {!bootstrap && bootstrapStatus === "error" && (
            <Alert
              type="warning"
              title={
                bootstrapError ||
                ui("连接失败，请重试。", "Connection failed. Please retry.")
              }
              action={
                <Button onClick={retryBootstrap}>
                  {ui("重试连接", "Retry connection")}
                </Button>
              }
            />
          )}
          {bootstrapStatus === "unauthenticated" && (
            <Alert
              type="warning"
              title={ui(
                "登录状态已失效，请重新登录。",
                "Your session has expired. Please sign in again.",
              )}
            />
          )}
          {(canUse === false || bootstrapStatus === "forbidden") && (
            <Alert
              type="info"
              title={ui(
                "当前账号未获准使用此功能，请联系超级管理员。",
                "This feature is unavailable for this account. Contact your administrator.",
              )}
            />
          )}
          {bootstrap && canUse && !bootstrap.workerOnline && (
            <Alert
              type="warning"
              title={ui(
                "模型服务工作进程未就绪，历史记录仍可查看。",
                "The model worker is unavailable. You can still view history.",
              )}
            />
          )}
          <div
            className="agent-messages"
            hidden={Boolean(businessLaunch && canUse)}
            ref={viewport}
            onScroll={(event) => {
              const box = event.currentTarget;
              if (box.scrollTop < lastScrollTop.current - 1)
                followLatest.current = false;
              if (box.scrollHeight - box.scrollTop - box.clientHeight < 96)
                followLatest.current = true;
              setShowLatest(!followLatest.current);
              lastScrollTop.current = box.scrollTop;
            }}
          >
            {!runs.length && !historyLoading && !historyFailure && (
              <div className="agent-welcome">
                <RobotOutlined />
                <Typography.Title level={2}>
                  {ui(
                    "从项目数据中寻找答案",
                    "Find answers in your project data",
                  )}
                </Typography.Title>
                <p>
                  {ui(
                    "直接提问，智能体将按需查找当前项目的授权资料与可用算法；完整任务可从业务流开始。",
                    "Ask a question to discover authorized project data and algorithms, or start a task from business flows.",
                  )}
                </p>
                <div
                  className="agent-example-questions"
                  aria-label={ui("示例问题", "Example questions")}
                >
                  {exampleQuestions.map((question) => (
                    <Button key={question} onClick={() => setPrompt(question)}>
                      {question}
                    </Button>
                  ))}
                  {bootstrap?.canAgent && (
                    <Button type="primary" onClick={openBusinessFlows}>
                      {ui(
                        "从业务流开始任务",
                        "Start a task with a business flow",
                      )}
                    </Button>
                  )}
                </div>
              </div>
            )}
            {runs.map((r) => (
              <section className="agent-turn" key={r.id} data-run-id={r.id}>
                <div className="agent-user-message">{r.prompt}</div>
                <div className="agent-assistant-message">
                  <Space className="agent-answer-heading">
                    <RobotOutlined />
                    <strong>MH-Agent</strong>
                    {r.status !== "succeeded" && (
                      <span
                        className={`agent-answer-status${active(r) ? " is-active" : ""}`}
                      >
                        {statusLabel[r.status]}
                      </span>
                    )}
                  </Space>
                  {r.businessFlow && (
                    <BusinessFlowActivity
                      flow={r.businessFlow}
                      modelActivity={workflowModelActivity(r)}
                      onChanged={acceptBusinessFlow}
                      inspectNode={
                        inspectedFlowNode?.flowId === r.businessFlow.id
                          ? inspectedFlowNode
                          : undefined
                      }
                      onAccessBlocked={() =>
                        setBlockedFlowId(r.businessFlow!.id)
                      }
                    />
                  )}
                  {r.attachments.length > 0 && (
                    <div className="agent-run-attachments">
                      {r.attachments.map((item) =>
                        item.kind === "image" && item.previewUrl ? (
                          <a
                            key={item.id}
                            href={item.previewUrl}
                            target="_blank"
                            rel="noreferrer"
                          >
                            <img
                              src={item.previewUrl}
                              alt={item.fileName}
                              className="agent-attachment-preview"
                            />
                          </a>
                        ) : (
                          <Tag key={item.id} icon={<PaperClipOutlined />}>
                            {item.fileName}
                          </Tag>
                        ),
                      )}
                    </div>
                  )}
                  {r.contextTruncated && (
                    <p className="agent-muted">
                      {ui(
                        "本轮已裁剪较早历史。",
                        "Older context was shortened for this turn.",
                      )}
                    </p>
                  )}
                  {!r.businessFlow &&
                    !(
                      r.researchIntent?.scenario === "geology_generic" &&
                      r.researchIntent.workflowId
                    ) && (
                      <RunProcess
                        run={r}
                        events={r.id === running?.id ? events : []}
                        disconnected={
                          r.id === running?.id ? pollFailure : undefined
                        }
                      />
                    )}
                  {!r.businessFlow &&
                    !(
                      r.researchIntent?.scenario === "geology_generic" &&
                      r.researchIntent.workflowId
                    ) &&
                    (!(mode === "agent" && r.computeIntent?.taskId) ||
                      r.evidence.some((item) =>
                        ["read_compute_output", "get_compute_task"].includes(
                          item.tool,
                        ),
                      )) && (
                      <>
                        <AnswerPreview run={r} />
                        <SafeMarkdown text={r.answer} />
                      </>
                    )}
                  {mode === "agent" &&
                    r.computeIntent &&
                    r.interaction?.status !== "pending" && (
                      <ComputeIntentCard
                        runId={r.id}
                        intent={r.computeIntent}
                        onChanged={(next) => {
                          if (
                            alive.current &&
                            conversationSequence === sequence.current
                          )
                            updateRun(next);
                        }}
                      />
                    )}
                  {mode === "agent" &&
                    r.researchIntent &&
                    !runs.some(
                      (later) =>
                        later.id > r.id &&
                        later.researchIntent?.originRunId ===
                          r.researchIntent?.originRunId,
                    ) && (
                      <ResearchIntentCard
                        run={{ ...r, researchIntent: r.researchIntent }}
                        onWorkflowChange={(workflow) =>
                          setResearchWorkflow((previous) => {
                            if (latestResearchRunId.current !== r.id)
                              return previous;
                            return workflow
                              ? { runId: r.id, workflow }
                              : previous?.runId === r.id
                                ? undefined
                                : previous;
                          })
                        }
                        onRestart={openBusinessFlows}
                        onChanged={(next) => {
                          if (
                            !alive.current ||
                            conversationSequence !== sequence.current
                          )
                            return;
                          if (!updateRun(next)) return;
                          if (
                            next.id !== r.id &&
                            !runs.some((old) => old.id === next.id)
                          ) {
                            pendingScroll.current = next.id;
                            void refreshList();
                          }
                        }}
                      />
                    )}
                  <InteractionCard
                    run={r}
                    disabled={Boolean(current?.archived) || busy}
                    onChanged={(next) => {
                      if (
                        !alive.current ||
                        conversationSequence !== sequence.current
                      )
                        return;
                      followLatest.current = true;
                      setEvents([]);
                      updateRun(next);
                      void refreshList();
                    }}
                  />

                  {mode === "agent" &&
                    (r.computeIntent?.taskId ||
                      r.evidence.some((item) =>
                        [
                          "execute_operator",
                          "get_compute_task",
                          "import_compute_result",
                        ].includes(item.tool),
                      )) && (
                      <RunComputeTasks
                        runId={r.id}
                        refreshKey={r.updatedAt}
                        activityTaskId={r.computeIntent?.taskId ?? undefined}
                        onActivityChange={(activity) => {
                          if (
                            !alive.current ||
                            conversationSequence !== sequence.current
                          )
                            return;
                          setComputeActivities((old) => {
                            const previous = old[r.id];
                            if (
                              previous?.state === activity.state &&
                              previous.label === activity.label &&
                              previous.detail === activity.detail
                            )
                              return old;
                            return { ...old, [r.id]: activity };
                          });
                        }}
                      />
                    )}
                  <PlatformActions
                    actions={r.platformActions}
                    projectId={Number(project?.current ?? 1)}
                  />
                  <RunEvidence
                    items={r.evidence}
                    canManage={Boolean(bootstrap?.canManage)}
                  />
                  {!r.businessFlow && r.detail && r.status !== "succeeded" && (
                    <Alert
                      className="agent-run-notice"
                      type={r.status === "failed" ? "error" : "info"}
                      title={r.detail}
                      showIcon
                    />
                  )}
                  {!active(r) &&
                    !waiting(r) &&
                    !r.computeIntent &&
                    !r.researchIntent &&
                    !r.businessFlow && (
                      <Space className="agent-answer-actions">
                        <Button
                          size="small"
                          icon={<CopyOutlined />}
                          disabled={!r.answer}
                          onClick={() => void copy(r.answer)}
                        >
                          {ui("复制", "Copy")}
                        </Button>
                        <Button
                          size="small"
                          disabled={taskLocked || busy || !modelOnline}
                          onClick={() => void send(r.prompt)}
                        >
                          {r.status === "succeeded"
                            ? ui("重新生成", "Regenerate")
                            : ui("重试", "Retry")}
                        </Button>
                      </Space>
                    )}
                </div>
              </section>
            ))}
          </div>
          {!businessLaunch && showLatest && runs.length > 0 && (
            <div className="agent-latest-bar">
              <Button
                icon={<ArrowDownOutlined />}
                onClick={() => {
                  followLatest.current = true;
                  setShowLatest(false);
                  if (viewport.current)
                    viewport.current.scrollTop = viewport.current.scrollHeight;
                }}
              >
                {ui("回到最新", "Jump to latest")}
              </Button>
            </div>
          )}
          {canUse && !businessLaunch && (
            <div className="agent-composer">
              <AgentResizeHandle
                orientation="horizontal"
                label={ui("调整输入框高度", "Resize message input")}
                hint={ui(
                  "上下拖动或按方向键调整，双击恢复",
                  "Drag or use arrow keys to resize; double-click to reset",
                )}
                controls="agent-message-input"
                value={layout.input}
                min={layout.inputMin}
                max={layout.inputMax}
                defaultValue={layout.defaults.input}
                onChange={layout.setInput}
              />
              <div className="agent-composer-content">
                <div className="agent-composer-context">
                  {waitingRun?.interaction?.status === "pending" && (
                    <div
                      className="agent-answer-target"
                      id="agent-answer-target"
                    >
                      <MessageOutlined />
                      <span>
                        <strong>
                          {waitingRun.interaction.kind === "review"
                            ? ui(
                                "请在问题卡中审核",
                                "Review in the question card",
                              )
                            : ui(
                                "在下方回答当前问题",
                                "Answer the current question below",
                              )}
                        </strong>
                        <span>{waitingRun.interaction.title}</span>
                      </span>
                      <Button
                        type="link"
                        onClick={() => revealWaitingQuestion(true)}
                      >
                        {ui("查看问题", "View question")}
                      </Button>
                    </div>
                  )}
                  {attachments.length > 0 && (
                    <div className="agent-attachments-row">
                      {attachments.map((item) => (
                        <Tag
                          key={item.id}
                          closable={!taskLocked && !busy}
                          onClose={() =>
                            setAttachments((old) =>
                              old.filter((entry) => entry.id !== item.id),
                            )
                          }
                        >
                          {item.fileName}
                        </Tag>
                      ))}
                    </div>
                  )}
                </div>
                <div className="agent-input-row">
                  <Input.TextArea
                    id="agent-message-input"
                    aria-label={ui("输入消息", "Message")}
                    aria-describedby={
                      waitingRun?.interaction?.status === "pending"
                        ? "agent-answer-target"
                        : undefined
                    }
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    style={{ height: layout.input, resize: "none" }}
                    maxLength={bootstrap?.budgets?.maxPromptCharacters ?? 12000}
                    disabled={!canUse || current?.archived}
                    placeholder={
                      businessBlocked && !running
                        ? ui(
                            "请在业务流中处理当前决定，或新建会话继续其他工作",
                            "Continue in the flow, or open a new conversation",
                          )
                        : waitingRun
                          ? ui(
                              "可直接补充回答，或在上方问题卡中选择并继续",
                              "Answer here, or use the question card above",
                            )
                          : ui(
                              "输入问题，Enter 发送，Shift+Enter 换行",
                              "Ask a question. Enter to send, Shift+Enter for a new line",
                            )
                    }
                    onKeyDown={(e) => {
                      if (
                        e.key === "Enter" &&
                        !e.shiftKey &&
                        !e.nativeEvent.isComposing
                      ) {
                        e.preventDefault();
                        void send();
                      }
                    }}
                  />
                </div>
                <div className="agent-composer-footer">
                  <div className="agent-composer-tools">
                    {bootstrap?.canAgent && (
                      <Button
                        type="text"
                        icon={<NodeIndexOutlined />}
                        aria-label={ui("业务流", "Business flows")}
                        onClick={() => navigate("/business-flows")}
                      >
                        业务流
                      </Button>
                    )}
                    {attachmentsAvailable && (
                      <Upload
                        className="agent-upload-tool"
                        accept=".pdf,.docx,.txt,.md,.csv,.png,.jpg,.jpeg,.webp"
                        multiple
                        showUploadList={false}
                        beforeUpload={(file) => {
                          void uploadAttachment(file);
                          return false;
                        }}
                        disabled={
                          taskLocked ||
                          busy ||
                          uploadingAttachment ||
                          current?.archived
                        }
                      >
                        <Button
                          type="text"
                          icon={<PaperClipOutlined />}
                          aria-label={ui("上传文档", "Upload document")}
                          loading={uploadingAttachment}
                        >
                          {ui("上传文档", "Upload document")}
                        </Button>
                      </Upload>
                    )}
                    {deepThinkingAvailable && (
                      <ReasoningEffortControl
                        value={effortOverride ?? "medium"}
                        overridden={effortOverride !== undefined}
                        effortEnabled
                        disabled={taskLocked || busy}
                        onChange={(value) => setEffortOverride(value)}
                      />
                    )}
                  </div>
                  {running ? (
                    <Button
                      className="agent-send-button"
                      aria-label={ui("停止回答", "Stop response")}
                      title={ui("停止回答", "Stop response")}
                      icon={<StopOutlined />}
                      loading={stopping}
                      disabled={stopping}
                      onClick={() => void stopResponse()}
                    />
                  ) : reviewPending ? (
                    <Button
                      type="primary"
                      className="agent-send-button agent-review-button"
                      icon={<NodeIndexOutlined />}
                      aria-label={ui("查看审核项", "Review pending items")}
                      title={ui(
                        "请在审核卡中选择后继续",
                        "Choose items in the review card to continue",
                      )}
                      disabled={busy || Boolean(historyLoading)}
                      onClick={() => revealWaitingQuestion(true)}
                    >
                      {ui("查看审核", "Review")}
                    </Button>
                  ) : (
                    <Button
                      type="primary"
                      className="agent-send-button"
                      aria-label={
                        waitingRun
                          ? ui("提交回答", "Submit answer")
                          : ui("发送", "Send")
                      }
                      title={
                        waitingRun
                          ? ui("提交回答", "Submit answer")
                          : ui("发送", "Send")
                      }
                      icon={<SendOutlined />}
                      loading={busy}
                      disabled={
                        !canUse ||
                        Boolean(businessBlocked) ||
                        Boolean(historyLoading) ||
                        uploadingAttachment ||
                        !modelOnline ||
                        !bootstrap?.workerOnline ||
                        !prompt.trim() ||
                        current?.archived
                      }
                      onClick={() => void send()}
                    />
                  )}
                </div>
              </div>
            </div>
          )}
        </main>
        {canUse &&
          !businessLaunch &&
          !historyLoading &&
          !historyFailure &&
          monitoredFlow &&
          monitoredFlow.conversationId === current?.id && (
            <BusinessFlowMonitor
              key={monitoredFlow.id}
              flow={monitoredFlow}
              accessBlocked={blockedFlowId === monitoredFlow.id}
              onLocate={(nodeId) => {
                setInspectedFlowNode({
                  flowId: monitoredFlow.id,
                  nodeId,
                  request: Date.now(),
                });
                const box = viewport.current;
                const card = Array.from(
                  box?.querySelectorAll<HTMLElement>(
                    "[data-business-flow-id]",
                  ) ?? [],
                ).find(
                  (element) =>
                    element.dataset.businessFlowId === monitoredFlow.id,
                );
                if (box && card) {
                  box.scrollTop +=
                    card.getBoundingClientRect().top -
                    box.getBoundingClientRect().top -
                    24;
                  followLatest.current = false;
                }
              }}
            />
          )}
      </div>
      <Modal
        open={Boolean(rename)}
        title={ui("重命名会话", "Rename conversation")}
        onCancel={() => setRename(null)}
        onOk={() => {
          if (rename)
            void agentApi
              .update(rename.id, { title: renameText })
              .then((c) => {
                if (current?.id === c.id) setCurrent(c);
                setRename(null);
                return refreshList();
              })
              .catch(report);
        }}
      >
        <Input
          value={renameText}
          onChange={(e) => setRenameText(e.target.value)}
          maxLength={120}
        />
      </Modal>
    </Layout>
  );
}
