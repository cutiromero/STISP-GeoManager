import {
  App,
  Alert,
  Button,
  Collapse,
  Drawer,
  Input,
  Layout,
  Modal,
  Popconfirm,
  Popover,
  Select,
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
  CopyOutlined,
  EditOutlined,
  DeleteOutlined,
  PaperClipOutlined,
  MenuOutlined,
  CloseOutlined,
  BulbOutlined,
  DownOutlined,
  NodeIndexOutlined,
} from "@ant-design/icons";
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import WorkspaceHeader from "../components/WorkspaceHeader";
import { useAppContext } from "../contexts/AppContext";
import { useProjectContext } from "../projects/ProjectContext";
import { useComputeText } from "../compute/ui";
import { agentApi } from "../api/agent";
import type {
  AgentBudgetProfileId,
  AgentConversation,
  AgentRun,
  AgentResource,
  AgentEvent,
  AgentAttachment,
  AgentWorkflow,
} from "../api/generated/types.gen";
import { createUuid } from "../utils/uuid";
import { useAgentBootstrap } from "./useAgentBootstrap";
import SafeMarkdown from "./SafeMarkdown";
import TaskBudgetControl from "./TaskBudgetControl";
import RunEvidence from "./RunEvidence";
import RunComputeTasks from "./RunComputeTasks";
import ComputeIntentCard from "./ComputeIntentCard";
import WorkflowPanel from "./WorkflowPanel";
import AgentResizeHandle from "./AgentResizeHandle";
import AgentToolSelection, {
  defaultToolPreferences,
  preferencesFromRun,
  selectionError,
  type ToolPreferences,
} from "./AgentToolSelection";
import useAgentLayout from "./useAgentLayout";
import ReasoningEffortControl, {
  type ReasoningEffort,
} from "./ReasoningEffortControl";
import "./agent.css";

const active = (r: AgentRun) => r.status === "queued" || r.status === "running";

export default function AgentPage() {
  const project = useProjectContext();
  const { user } = useAppContext();
  const location = useLocation();
  const mode = location.pathname.endsWith("workbench") ? "agent" : "chat";
  return (
    <AgentWorkspace
      key={`${user?.id}:${project?.current}:${mode}`}
      mode={mode}
    />
  );
}

function AgentWorkspace({ mode }: { mode: "chat" | "agent" }) {
  const ui = useComputeText();
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAppContext();
  const project = useProjectContext();
  const layout = useAgentLayout(`agent-layout:${user?.id ?? "anon"}:${mode}`);
  const { message } = App.useApp();
  const bootstrap = useAgentBootstrap();
  const [conversations, setConversations] = useState<AgentConversation[]>([]);
  const [current, setCurrent] = useState<AgentConversation | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [prompt, setPrompt] = useState("");
  useEffect(() => {
    const prefill = location.state?.query;
    if (mode === "agent" && typeof prefill === "string" && prefill.trim()) {
      setPrompt(prefill);
      navigate(location.pathname, { replace: true, state: null });
    }
  }, [mode, location.state, location.pathname, navigate]);
  const [model, setModel] = useState("");
  const [thinkingMode, setThinkingMode] = useState<"fast" | "deep">("fast");
  const [budgetProfile, setBudgetProfile] =
    useState<AgentBudgetProfileId>("normal");
  const [outputOverride, setOutputOverride] = useState<number>();
  const [effortOverride, setEffortOverride] = useState<ReasoningEffort>();
  const defaultEffort =
    (bootstrap?.budgets?.enabled
      ? bootstrap.budgets.profiles.find(
          (item) => item.budgetProfile === budgetProfile,
        )?.reasoningEffort
      : bootstrap?.defaultReasoningEffort) ?? "medium";
  const requestedEffort = thinkingMode === "deep" ? effortOverride : undefined;
  useEffect(() => {
    if (bootstrap?.budgets) setBudgetProfile(bootstrap.budgets.defaultProfile);
  }, [bootstrap?.budgets?.defaultProfile]);
  const [query, setQuery] = useState("");
  const [archived, setArchived] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [resources, setResources] = useState<AgentResource[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
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
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [workflowOpen, setWorkflowOpen] = useState(false);
  const [workflowStatus, setWorkflowStatus] =
    useState<AgentWorkflow["status"]>();
  const historyButton = useRef<HTMLButtonElement>(null);
  const historyCloseButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!showHistory || !layout.narrow) return;
    historyCloseButton.current?.focus();
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setShowHistory(false);
    };
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("keydown", close);
      historyButton.current?.focus();
    };
  }, [showHistory, layout.narrow]);
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
  const pendingScroll = useRef<number | null>(null);
  const failedSubmission = useRef<{
    id: number;
    key: string;
    prompt: string;
    model: string;
    selected: number[];
    thinkingMode: "fast" | "deep";
    reasoningEffort?: ReasoningEffort;
    attachmentIds: number[];
    internetEnabled: boolean;
    budgetProfile?: AgentBudgetProfileId;
    maxOutputTokens?: number;
    toolPreferences: ToolPreferences;
  } | null>(null);
  const running = runs.find(active);
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
  const attachmentsAvailable = Boolean(bootstrap?.allowAttachments);
  const internetAvailable = Boolean(bootstrap?.internetEnabled);
  const conversationStorageKey = `agent-conversation:${user?.id ?? "anon"}:${project?.current ?? "1"}:${mode}`;

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      sequence.current++;
    };
  }, []);
  const report = (e: unknown) => {
    if (
      alive.current &&
      !(e instanceof DOMException && e.name === "AbortError")
    )
      setError(
        e instanceof Error ? e.message : ui("操作失败", "Operation failed"),
      );
  };
  const refreshList = async () => {
    const seq = ++listSequence.current;
    try {
      const data = await agentApi.conversations(mode, query, archived);
      if (alive.current && seq === listSequence.current)
        setConversations(data.items);
    } catch (e) {
      report(e);
    }
  };
  useEffect(() => {
    if (!canUse) {
      setRuns([]);
      setEvents([]);
      setCurrent(null);
      setConversations([]);
      return;
    }
    const timer = setTimeout(() => {
      void refreshList();
    }, 200);
    return () => clearTimeout(timer);
  }, [mode, canUse, query, archived]);
  useEffect(() => {
    if (!bootstrap || model) return;
    const preferred = localStorage.getItem(`agent-model:${user?.id}:${mode}`);
    const candidates = bootstrap.models.filter(
      (m) => mode === "chat" || m.allowAgent,
    );
    const defaultModel =
      mode === "agent"
        ? bootstrap.defaultAgentModel
        : bootstrap.defaultChatModel;
    setModel(
      candidates.some((m) => m.alias === preferred)
        ? preferred!
        : defaultModel || candidates[0]?.alias || "",
    );
  }, [bootstrap, mode, model, user?.id]);
  useEffect(() => {
    const preferred = localStorage.getItem(
      `agent-thinking:${user?.id}:${mode}`,
    );
    const next =
      preferred === "deep" && deepThinkingAvailable ? "deep" : "fast";
    setThinkingMode(next);
  }, [deepThinkingAvailable, mode, user?.id]);
  useEffect(() => {
    if (!deepThinkingAvailable && thinkingMode !== "fast")
      setThinkingMode("fast");
  }, [deepThinkingAvailable, thinkingMode]);
  useEffect(() => {
    if (mode !== "agent" || !canUse) return;
    void agentApi
      .resources()
      .then((r) => {
        if (alive.current) setResources(r.items);
      })
      .catch(report);
  }, [mode, canUse]);
  useEffect(() => {
    if (!running) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let cursor = 0;
    const poll = async () => {
      try {
        const data = await agentApi.poll(running.id, cursor);
        if (disposed) return;
        cursor = data.cursor;
        setRuns((old) => old.map((r) => (r.id === data.run.id ? data.run : r)));
        setEvents((old) =>
          [
            ...old,
            ...data.events.filter((e) => !old.some((p) => p.id === e.id)),
          ].slice(-80),
        );
        if (active(data.run))
          timer = setTimeout(
            poll,
            document.hidden ? 3000 : data.run.status === "queued" ? 1500 : 800,
          );
        else void refreshList();
      } catch (e) {
        if (disposed) return;
        // Do not retain restricted content after any authorization/read failure.
        setRuns([]);
        setEvents([]);
        report(e);
      }
    };
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [running?.id]);
  useEffect(() => {
    if (!current || running || !canUse) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const reauthorize = async () => {
      try {
        const data = await agentApi.detail(current.id);
        if (!disposed) setRuns(data.runs);
      } catch (e) {
        if (!disposed) {
          setRuns([]);
          setEvents([]);
          report(e);
        }
      }
      if (!disposed) timer = setTimeout(reauthorize, 15000);
    };
    timer = setTimeout(reauthorize, 15000);
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [current?.id, running?.id, canUse]);
  useEffect(() => {
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
        return;
      }
    }
    if (box && box.scrollHeight - box.scrollTop - box.clientHeight < 250)
      box.scrollTop = box.scrollHeight;
  }, [runs, events]);

  const open = async (c: AgentConversation) => {
    const seq = ++sequence.current;
    setCurrent(c);
    setRuns([]);
    setEvents([]);
    setError("");
    setShowHistory(false);
    failedSubmission.current = null;
    try {
      const detail = await agentApi.detail(c.id);
      if (alive.current && seq === sequence.current) {
        setCurrent(detail.conversation);
        setRuns(detail.runs);
        if (mode === "agent") {
          const latest = detail.runs[detail.runs.length - 1];
          const restored = preferencesFromRun(latest);
          setToolPreferences(
            handoffSelection.current
              ? { ...restored, knowledgeSelection: handoffSelection.current }
              : restored,
          );
          setSelected(latest?.resourceIds ?? []);
        }
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
      if (seq === sequence.current) report(e);
    }
  };
  useEffect(() => {
    if (
      !canUse ||
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
  }, [canUse, conversationStorageKey, conversations, current]);
  const send = async (text = prompt) => {
    if (
      !canUse ||
      busy ||
      running ||
      uploadingAttachment ||
      !text.trim() ||
      !modelOnline
    )
      return;
    const invalidSelection =
      mode === "agent" ? selectionError(toolPreferences, selected) : "";
    if (invalidSelection) {
      setError(invalidSelection);
      return;
    }
    setBusy(true);
    setError("");
    const seq = sequence.current;
    try {
      const c = current ?? (await agentApi.create(mode));
      if (!alive.current || seq !== sequence.current) return;
      setCurrent(c);
      try {
        sessionStorage.setItem(conversationStorageKey, String(c.id));
      } catch {
        // Session storage is only a UX hint; the server remains authoritative.
      }
      const previous = failedSubmission.current;
      const same =
        previous?.id === c.id &&
        previous.prompt === text &&
        previous.model === model &&
        JSON.stringify(previous.selected) === JSON.stringify(selected) &&
        previous.thinkingMode === thinkingMode &&
        previous.reasoningEffort === requestedEffort &&
        JSON.stringify(previous.attachmentIds) ===
          JSON.stringify(attachments.map((item) => item.id)) &&
        previous.internetEnabled === (internetEnabled && internetAvailable) &&
        previous.budgetProfile ===
          (bootstrap?.budgets?.enabled ? budgetProfile : undefined) &&
        previous.maxOutputTokens ===
          (bootstrap?.budgets?.enabled ? outputOverride : undefined) &&
        JSON.stringify(previous.toolPreferences) ===
          JSON.stringify(toolPreferences);
      const submission = same
        ? previous
        : {
            id: c.id,
            key: createUuid(),
            prompt: text,
            model,
            selected,
            thinkingMode,
            reasoningEffort: requestedEffort,
            attachmentIds: attachments.map((item) => item.id),
            internetEnabled: internetEnabled && internetAvailable,
            budgetProfile: bootstrap?.budgets?.enabled
              ? budgetProfile
              : undefined,
            maxOutputTokens: bootstrap?.budgets?.enabled
              ? outputOverride
              : undefined,
            toolPreferences,
          };
      failedSubmission.current = submission;
      const run = await agentApi.submit(c.id, {
        model,
        prompt: text,
        idempotencyKey: submission.key,
        ...(bootstrap?.budgets?.enabled
          ? { budgetProfile, maxOutputTokens: outputOverride }
          : {}),
        thinkingMode,
        reasoningEffort: requestedEffort,
        resourceIds:
          mode === "agent" && toolPreferences.dataSelectionMode === "manual"
            ? selected
            : [],
        ...(mode === "agent" ? toolPreferences : {}),
        attachmentIds: attachments.map((item) => item.id),
        internetEnabled: internetEnabled && internetAvailable,
      });
      if (!alive.current || seq !== sequence.current) return;
      pendingScroll.current = run.id;
      setRuns((old) => [...old.filter((r) => r.id !== run.id), run]);
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
  const reset = () => {
    sequence.current++;
    setCurrent(null);
    setRuns([]);
    setEvents([]);
    setError("");
    setPrompt("");
    setAttachments([]);
    setInternetEnabled(false);
    setSelected([]);
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
      setToolsOpen(false);
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
  const statusLabel: Record<string, string> = {
    queued: ui("排队中", "Queued"),
    running: ui("生成中", "Generating"),
    succeeded: ui("已完成", "Completed"),
    failed: ui("未完成", "Incomplete"),
    cancelled: ui("已停止", "Stopped"),
    interrupted: ui("已中断", "Interrupted"),
  };
  return (
    <Layout className="agent-shell">
      <WorkspaceHeader
        activeTab="warning"
        canBrowseData={Boolean(user?.permissions.canBrowseData)}
      />
      <div className="agent-workspace">
        {showHistory && layout.narrow && (
          <button
            className="agent-history-backdrop"
            tabIndex={-1}
            aria-label={ui("收起会话侧栏", "Dismiss conversation sidebar")}
            onClick={() => setShowHistory(false)}
          />
        )}
        <aside
          id="agent-conversation-sidebar"
          aria-label={ui("会话侧栏", "Conversation sidebar")}
          className={`agent-sidebar ${showHistory ? "agent-sidebar-open" : ""}`}
          style={{ width: layout.narrow ? undefined : layout.sidebar }}
        >
          <div className="agent-sidebar-heading">
            <span className="agent-sidebar-symbol">
              <RobotOutlined />
            </span>
            <div>
              <Typography.Title level={4}>
                {ui("智能体", "Agent")}
              </Typography.Title>
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
          <div className="agent-mode-nav">
            {bootstrap?.canChat && (
              <Button
                block
                icon={<MessageOutlined />}
                type={mode === "chat" ? "primary" : "text"}
                disabled={!bootstrap?.canChat}
                onClick={() => navigate("/agent/chat")}
              >
                {ui("模型对话", "Model chat")}
              </Button>
            )}
            {bootstrap?.canAgent && (
              <Button
                block
                icon={<RobotOutlined />}
                type={mode === "agent" ? "primary" : "text"}
                disabled={!bootstrap?.canAgent}
                onClick={() => navigate("/agent/workbench")}
              >
                {ui("数据智能体", "Data agent")}
              </Button>
            )}
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
                  {c.title}
                </button>
                <Space size={0} className="agent-history-actions">
                  <Button
                    size="small"
                    type="text"
                    aria-label={ui("重命名", "Rename")}
                    icon={<EditOutlined />}
                    onClick={() => {
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
                  <Popconfirm
                    title={ui(
                      "删除会话及其分析记录？",
                      "Delete this conversation and its evidence?",
                    )}
                    onConfirm={() =>
                      agentApi
                        .remove(c.id)
                        .then(() => {
                          if (current?.id === c.id) reset();
                          return refreshList();
                        })
                        .catch(report)
                    }
                  >
                    <Button
                      size="small"
                      type="text"
                      danger
                      aria-label={ui("删除", "Delete")}
                      icon={<DeleteOutlined />}
                    />
                  </Popconfirm>
                </Space>
              </div>
            ))}
          </div>
          {bootstrap?.canManage && (
            <Button onClick={() => navigate("/admin/agent")}>
              {ui("智能体管理", "Agent settings")}
            </Button>
          )}
        </aside>
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
        <main className="agent-main" inert={showHistory && layout.narrow}>
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
                <span>
                  {mode === "chat"
                    ? ui("模型对话", "Model chat")
                    : ui("数据智能体", "Data agent")}
                </span>
                <strong title={current?.title}>
                  {current?.title ??
                    (mode === "chat"
                      ? ui("模型对话", "Model chat")
                      : ui("数据智能体", "Data agent"))}
                </strong>
              </div>
            </div>
            <Tag className="agent-project-badge">
              {project?.projects.find((p) => String(p.id) === project.current)
                ?.name ?? ui("当前项目", "Current project")}
            </Tag>
          </div>
          {error && (
            <Alert
              title={error}
              type="error"
              showIcon
              closable
              onClose={() => setError("")}
            />
          )}
          {bootstrap && !canUse && (
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
          <div className="agent-messages" ref={viewport}>
            {!runs.length && (
              <div className="agent-welcome">
                <RobotOutlined />
                <Typography.Title level={2}>
                  {mode === "chat"
                    ? ui("有什么想讨论的？", "What would you like to discuss?")
                    : ui(
                        "从项目数据中寻找答案",
                        "Find answers in your project data",
                      )}
                </Typography.Title>
                <p>
                  {mode === "chat"
                    ? ui(
                        "选择本地模型，开始一段对话。",
                        "Choose a local model to start a conversation.",
                      )
                    : ui(
                        "自动发现当前项目中您有权访问的数据，读取、统计并提供依据。",
                        "Discover authorized project data, calculate statistics and inspect the evidence.",
                      )}
                </p>
                {mode === "agent" && (
                  <Button
                    onClick={() =>
                      setPrompt(
                        ui(
                          "请查找当前项目中可分析的表格，说明字段和数据质量。",
                          "Find tables in this project and describe their fields and data quality.",
                        ),
                      )
                    }
                  >
                    {ui("查看项目数据概况", "Explore project data")}
                  </Button>
                )}
              </div>
            )}
            {runs.map((r) => (
              <section className="agent-turn" key={r.id} data-run-id={r.id}>
                <div className="agent-user-message">{r.prompt}</div>
                <div className="agent-assistant-message">
                  <Space className="agent-answer-heading">
                    <RobotOutlined />
                    <strong>
                      {r.computeIntent
                        ? ui("平台计算助手", "Platform compute assistant")
                        : (bootstrap?.models.find((m) => m.alias === r.model)
                            ?.name ?? r.model)}
                    </strong>
                    {r.status !== "succeeded" && (
                      <span
                        className={`agent-answer-status${active(r) ? " is-active" : ""}`}
                      >
                        {statusLabel[r.status]}
                      </span>
                    )}
                  </Space>
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
                  {!r.computeIntent &&
                    (r.thinkingMode === "deep" || r.thinkingText) && (
                      <Collapse
                        size="small"
                        className="agent-thinking-panel"
                        defaultActiveKey={active(r) ? ["thinking"] : []}
                        items={[
                          {
                            key: "thinking",
                            label: active(r)
                              ? ui(
                                  "模型思考过程（生成中）",
                                  "Model reasoning (generating)",
                                )
                              : `${ui("模型思考过程", "Model reasoning")}${r.thinkingDurationMs ? ` · ${(r.thinkingDurationMs / 1000).toFixed(1)}s` : ""}`,
                            children: (
                              <pre className="agent-thinking-content">
                                {r.id === running?.id
                                  ? events
                                      .filter((e) => e.kind === "thinking")
                                      .map((e) => e.text)
                                      .join("") ||
                                    ui(
                                      "正在等待模型返回思考内容…",
                                      "Waiting for the model reasoning stream…",
                                    )
                                  : r.thinkingText ||
                                    ui(
                                      "本次未保存到思考片段，请结合运行状态查看原因。",
                                      "No reasoning segments were saved. See the run status below.",
                                    )}
                              </pre>
                            ),
                          },
                        ]}
                      />
                    )}
                  {!(mode === "agent" && r.computeIntent?.taskId) && (
                    <SafeMarkdown text={r.answer} />
                  )}
                  {mode === "agent" && r.computeIntent && (
                    <ComputeIntentCard
                      runId={r.id}
                      intent={r.computeIntent}
                      onChanged={(next) =>
                        setRuns((old) =>
                          old.map((item) =>
                            item.id === next.id ? next : item,
                          ),
                        )
                      }
                    />
                  )}
                  {active(r) && !r.answer && (
                    <p className="agent-live-progress" role="status">
                      <span aria-hidden="true" />
                      {r.status === "queued"
                        ? ui("正在等待模型…", "Waiting for the model…")
                        : r.id === running?.id &&
                            events.some((event) =>
                              event.kind.startsWith("tool_"),
                            )
                          ? ui(
                              "正在查阅资料并处理数据…",
                              "Reviewing sources and processing data…",
                            )
                          : ui("正在组织回答…", "Preparing your answer…")}
                    </p>
                  )}
                  {mode === "agent" &&
                    (r.computeIntent?.taskId ||
                      r.evidence.some((item) =>
                        [
                          "execute_operator",
                          "get_compute_task",
                          "import_compute_result",
                        ].includes(item.tool),
                      )) && (
                      <RunComputeTasks runId={r.id} refreshKey={r.updatedAt} />
                    )}
                  <RunEvidence
                    items={r.evidence}
                    canManage={Boolean(bootstrap?.canManage)}
                  />
                  {r.detail && r.status !== "succeeded" && (
                    <Alert
                      className="agent-run-notice"
                      type={r.status === "failed" ? "error" : "info"}
                      title={r.detail}
                      showIcon
                    />
                  )}
                  {!active(r) && !r.computeIntent && (
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
                        disabled={Boolean(running) || busy || !modelOnline}
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
          {canUse && (
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
                {attachments.length > 0 && (
                  <div className="agent-attachments-row">
                    {attachments.map((item) => (
                      <Tag
                        key={item.id}
                        closable={!running && !busy}
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
                <div className="agent-input-row">
                  <Input.TextArea
                    id="agent-message-input"
                    aria-label={ui("输入消息", "Message")}
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    style={{ height: layout.input, resize: "none" }}
                    maxLength={bootstrap?.budgets?.maxPromptCharacters ?? 12000}
                    disabled={!canUse || current?.archived}
                    placeholder={ui(
                      "输入问题，Enter 发送，Shift+Enter 换行",
                      "Ask a question. Enter to send, Shift+Enter for a new line",
                    )}
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
                    {mode === "agent" && bootstrap && (
                      <AgentToolSelection
                        bootstrap={bootstrap}
                        resources={resources}
                        selected={selected}
                        value={toolPreferences}
                        disabled={
                          Boolean(running) ||
                          busy ||
                          !canUse ||
                          Boolean(current?.archived)
                        }
                        onChange={setToolPreferences}
                        onResources={setSelected}
                      />
                    )}
                    {(attachmentsAvailable || internetAvailable) && (
                      <Popover
                        trigger="click"
                        placement="topLeft"
                        title={ui("工具与数据", "Tools and data")}
                        open={toolsOpen}
                        onOpenChange={setToolsOpen}
                        content={
                          <div
                            className="agent-tools-panel"
                            onKeyDown={(event) => {
                              if (event.key === "Escape") setToolsOpen(false);
                            }}
                          >
                            {attachmentsAvailable && (
                              <Upload
                                accept=".pdf,.doc,.docx,.txt,.md,.csv,image/*"
                                multiple
                                showUploadList={false}
                                beforeUpload={(file) => {
                                  void uploadAttachment(file);
                                  return false;
                                }}
                                disabled={
                                  Boolean(running) ||
                                  busy ||
                                  uploadingAttachment ||
                                  current?.archived
                                }
                              >
                                <Button
                                  icon={<PaperClipOutlined />}
                                  loading={uploadingAttachment}
                                >
                                  {ui(
                                    "上传文档或图片",
                                    "Upload document or image",
                                  )}
                                </Button>
                              </Upload>
                            )}
                            {internetAvailable && (
                              <label className="agent-tool-switch">
                                <span>
                                  {ui("联网检索", "Internet retrieval")}
                                </span>
                                <Switch
                                  aria-label={ui(
                                    "联网检索",
                                    "Internet retrieval",
                                  )}
                                  size="small"
                                  checked={internetEnabled}
                                  disabled={Boolean(running) || busy}
                                  onChange={setInternetEnabled}
                                />
                              </label>
                            )}
                          </div>
                        }
                      >
                        <Button
                          type="text"
                          icon={<PlusOutlined />}
                          aria-label={ui("工具与数据", "Tools and data")}
                          aria-expanded={toolsOpen}
                        >
                          {ui("工具", "Tools")}
                          {internetEnabled && (
                            <span
                              className="agent-tool-indicator"
                              aria-label={ui("已联网", "Internet on")}
                            />
                          )}
                        </Button>
                      </Popover>
                    )}
                    <Popover
                      trigger="click"
                      placement="topLeft"
                      title={ui("模型与回答设置", "Model and answer settings")}
                      open={settingsOpen}
                      onOpenChange={setSettingsOpen}
                      content={
                        <div
                          className="agent-settings-panel"
                          onKeyDown={(event) => {
                            if (event.key === "Escape") setSettingsOpen(false);
                          }}
                        >
                          <label className="agent-tool-field">
                            <strong>{ui("使用模型", "Model")}</strong>
                            <Select
                              aria-label={ui("选择模型", "Choose model")}
                              value={model || undefined}
                              disabled={Boolean(running) || busy}
                              onChange={(value) => {
                                setModel(value);
                                if (
                                  !models.find((item) => item.alias === value)
                                    ?.supportsThinking
                                )
                                  setThinkingMode("fast");
                                localStorage.setItem(
                                  `agent-model:${user?.id}:${mode}`,
                                  value,
                                );
                              }}
                              placeholder={ui("选择模型", "Choose model")}
                              options={models.map((item) => ({
                                value: item.alias,
                                label: `${item.name} · ${item.status === "online" ? ui("在线", "Online") : item.status === "offline" ? ui("离线", "Offline") : ui("待检测", "Unchecked")}${item.supportsVision ? ` · ${ui("支持图片", "Vision")}` : ""}`,
                              }))}
                            />
                          </label>
                          {bootstrap?.budgets?.enabled && selectedModel && (
                            <TaskBudgetControl
                              canManage={Boolean(bootstrap.canManage)}
                              options={bootstrap.budgets}
                              profile={budgetProfile}
                              output={outputOverride}
                              serviceWindow={selectedModel.contextWindowTokens}
                              disabled={Boolean(running) || busy}
                              onProfile={(value) => {
                                setBudgetProfile(value);
                                setOutputOverride(undefined);
                                setEffortOverride(undefined);
                                if (
                                  value === "reasoning" &&
                                  deepThinkingAvailable
                                ) {
                                  setThinkingMode("deep");
                                  localStorage.setItem(
                                    `agent-thinking:${user?.id}:${mode}`,
                                    "deep",
                                  );
                                }
                              }}
                              onOutput={setOutputOverride}
                            />
                          )}
                        </div>
                      }
                    >
                      <Button
                        type="text"
                        className="agent-model-trigger"
                        aria-label={ui(
                          "模型与回答设置",
                          "Model and answer settings",
                        )}
                        aria-expanded={settingsOpen}
                      >
                        <span>
                          {selectedModel?.name ??
                            ui("选择模型", "Choose model")}
                        </span>
                        <DownOutlined />
                      </Button>
                    </Popover>
                    {deepThinkingAvailable && (
                      <>
                        <Button
                          type="text"
                          icon={<BulbOutlined />}
                          className={
                            thinkingMode === "deep" ? "agent-tool-active" : ""
                          }
                          aria-pressed={thinkingMode === "deep"}
                          disabled={Boolean(running) || busy}
                          onClick={() => {
                            const next =
                              thinkingMode === "deep" ? "fast" : "deep";
                            setThinkingMode(next);
                            localStorage.setItem(
                              `agent-thinking:${user?.id}:${mode}`,
                              next,
                            );
                          }}
                        >
                          {ui("深度思考", "Deep thinking")}
                        </Button>
                        {thinkingMode === "deep" && (
                          <ReasoningEffortControl
                            value={effortOverride ?? defaultEffort}
                            overridden={effortOverride !== undefined}
                            disabled={Boolean(running) || busy}
                            onChange={setEffortOverride}
                          />
                        )}
                      </>
                    )}
                    {mode === "agent" && (
                      <Button
                        type="text"
                        icon={<NodeIndexOutlined />}
                        className={
                          workflowStatus === "waiting_approval"
                            ? "agent-workflow-attention"
                            : ""
                        }
                        onClick={() => setWorkflowOpen(true)}
                      >
                        {ui("科研工作流", "Workflow")}
                        {workflowStatus === "waiting_approval" && (
                          <span>{ui("待确认", "Review")}</span>
                        )}
                        {workflowStatus &&
                          ["queued", "running", "waiting_compute"].includes(
                            workflowStatus,
                          ) && <span>{ui("进行中", "Running")}</span>}
                      </Button>
                    )}
                  </div>
                  {running ? (
                    <Button
                      className="agent-send-button"
                      aria-label={ui("停止", "Stop")}
                      title={ui("停止", "Stop")}
                      icon={<StopOutlined />}
                      onClick={() =>
                        void agentApi
                          .cancel(running.id)
                          .then((r) =>
                            setRuns((old) =>
                              old.map((item) => (item.id === r.id ? r : item)),
                            ),
                          )
                          .catch(report)
                      }
                    />
                  ) : (
                    <Button
                      type="primary"
                      className="agent-send-button"
                      aria-label={ui("发送", "Send")}
                      title={ui("发送", "Send")}
                      icon={<SendOutlined />}
                      loading={busy}
                      disabled={
                        !canUse ||
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
      </div>
      {mode === "agent" && canUse && (
        <Drawer
          title={ui("科研工作流", "Research workflow")}
          open={workflowOpen}
          onClose={() => setWorkflowOpen(false)}
          forceRender
          size={640}
          classNames={{ root: "agent-workflow-drawer" }}
        >
          <WorkflowPanel
            model={model}
            resourceIds={selected}
            embedded
            onStatusChange={setWorkflowStatus}
          />
        </Drawer>
      )}
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
