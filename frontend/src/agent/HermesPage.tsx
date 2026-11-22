import {
  ApiOutlined,
  ArrowDownOutlined,
  CloseOutlined,
  DeleteOutlined,
  GlobalOutlined,
  HistoryOutlined,
  NodeIndexOutlined,
  PlusOutlined,
  RobotOutlined,
  SendOutlined,
  StopOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Flex,
  Input,
  Popconfirm,
  Popover,
  Segmented,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ApiError, requestEventStream, requestJson } from "../api/client";
import type {
  HermesCapabilities,
  HermesMessage as Message,
  HermesMessageList,
  HermesRunAdmission,
  HermesRunStatus,
  HermesSession as Session,
  HermesSessionEnvelope,
  HermesSessionList,
  HermesSkill,
  HermesSkillList,
  HermesToolset,
  HermesToolsetList,
} from "../api/generated";
import { useComputeText } from "../compute/ui";
import { useAppContext } from "../contexts/AppContext";
import { useProjectContext } from "../projects/ProjectContext";
import AgentPage from "./AgentPage";
import AgentWorkspaceLayout, {
  AgentComposerFrame,
  conversationTime,
} from "./AgentWorkspaceLayout";
import SafeMarkdown from "./SafeMarkdown";
import useAgentLayout from "./useAgentLayout";

const api = "/api/agent/hermes";
const terminalStatuses = new Set([
  "completed",
  "failed",
  "cancelled",
  "interrupted",
]);

type Mode = "agent" | "chat";
type Progress = { id: string; name: string; status: string };
type Control = {
  kind: "clarify" | "approval";
  request_id: string;
  execution_generation: number;
  question: string;
  choices: string[];
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function errorText(error: unknown) {
  const detail =
    error instanceof ApiError
      ? record(record(error.data).error).message
      : undefined;
  return typeof detail === "string"
    ? detail
    : error instanceof Error
      ? error.message
      : "请求失败";
}

function pendingControl(value: unknown): Control | undefined {
  const event = record(value);
  const kind =
    event.kind ??
    (event.event === "clarify.request"
      ? "clarify"
      : event.event === "approval.request"
        ? "approval"
        : undefined);
  if (
    (kind !== "clarify" && kind !== "approval") ||
    typeof event.prompt_id !== "string" ||
    typeof event.execution_generation !== "number"
  )
    return undefined;
  const question =
    kind === "clarify" ? event.question : event.description || event.command;
  return {
    kind,
    request_id: event.prompt_id,
    execution_generation: event.execution_generation,
    question:
      typeof question === "string"
        ? question
        : kind === "clarify"
          ? "请补充信息"
          : "请确认操作",
    choices: Array.isArray(event.choices)
      ? event.choices.filter(
          (choice) =>
            typeof choice === "string" &&
            (kind === "clarify" || choice === "once" || choice === "deny"),
        )
      : [],
  };
}

export default function HermesPage() {
  const { user } = useAppContext();
  const project = useProjectContext();
  const location = useLocation();
  const runtime = new URLSearchParams(location.search).get("runtime");
  const mode = location.pathname === "/agent/chat" ? "chat" : "agent";
  const state = record(location.state);
  const platformWorkflow = Boolean(
    state.businessFlowLaunch ||
    state.researchDemo ||
    new URLSearchParams(location.search).has("conversationId"),
  );
  if (!user) return <AgentPage />;
  if (runtime !== "hermes" || platformWorkflow)
    return <AgentPage runtimeSwitch={<RuntimeSwitch modern={false} />} />;
  return (
    <AgentRoute
      key={JSON.stringify([user.id, project?.current, mode])}
      mode={mode}
    />
  );
}

function RuntimeSwitch({ modern }: { modern: boolean }) {
  const ui = useComputeText();
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <Segmented
      size="small"
      aria-label={ui("智能体运行版本", "Agent runtime")}
      value={modern ? "hermes" : "classic"}
      options={[
        { value: "classic", label: ui("经典版", "Classic") },
        { value: "hermes", label: ui("新版", "New") },
      ]}
      onChange={(value) => {
        const query = new URLSearchParams(location.search);
        query.delete("conversationId");
        query.delete("runId");
        if (value === "hermes") query.set("runtime", "hermes");
        else query.delete("runtime");
        navigate({ pathname: location.pathname, search: query.toString() });
      }}
    />
  );
}

function AgentRoute({ mode }: { mode: Mode }) {
  const [runtime, setRuntime] = useState<"checking" | "hermes" | "unavailable">(
    "checking",
  );
  const [error, setError] = useState("");
  const [activeMode, setActiveMode] = useState(mode);
  const [publicWebAvailable, setPublicWebAvailable] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    requestJson<HermesCapabilities>(`${api}/v1/capabilities`, {
      signal: controller.signal,
    })
      .then((caps) => {
        setPublicWebAvailable(caps.public_web_enabled === true);
        if (
          mode === "agent" &&
          Array.isArray(caps.session_modes) &&
          !caps.session_modes.includes("agent") &&
          caps.session_modes.includes("chat")
        )
          setActiveMode("chat");
        setRuntime("hermes");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setError(errorText(error));
        setRuntime("unavailable");
      });
    return () => controller.abort();
  }, [mode]);
  if (runtime === "checking") return <Spin aria-label="加载智能体" />;
  if (runtime === "unavailable")
    return (
      <div style={{ padding: 24 }}>
        <RuntimeSwitch modern />
        <Alert
          type="error"
          showIcon
          message={error || "新版 MH-agent 暂不可用"}
        />
      </div>
    );
  return (
    <Workspace
      mode={activeMode}
      publicWebAvailable={activeMode === "agent" && publicWebAvailable}
    />
  );
}

function Workspace({
  mode,
  publicWebAvailable,
}: {
  mode: Mode;
  publicWebAvailable: boolean;
}) {
  const ui = useComputeText();
  const { user } = useAppContext();
  const layout = useAgentLayout(`agent-layout:${user?.id ?? "anon"}:agent`);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selection, setSelection] = useState<{ key: string; id?: string }>();
  const [showHistory, setShowHistory] = useState(false);
  const [query, setQuery] = useState("");
  const historyCloseButton = useRef<HTMLButtonElement>(null);
  const draftNumber = useRef(0);
  const [error, setError] = useState("");
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const selected = sessions.find((session) => session.id === selection?.id);
  useEffect(() => {
    const controller = new AbortController();
    requestJson<HermesSessionList>(`${api}/api/sessions?mode=${mode}`, {
      signal: controller.signal,
    })
      .then(({ data, has_more }) => {
        setSessions(data);
        setHasMore(has_more);
        setSelection(
          (current) =>
            current ??
            (data[0] ? { key: data[0].id, id: data[0].id } : { key: "draft" }),
        );
      })
      .catch((failure: unknown) => {
        if (controller.signal.aborted) return;
        setError(errorText(failure));
        setSelection((current) => current ?? { key: "draft" });
      });
    return () => controller.abort();
  }, [mode]);

  async function create(key: string, internetEnabled: boolean) {
    const { session } = await requestJson<HermesSessionEnvelope>(
      `${api}/api/sessions`,
      {
        method: "POST",
        body: { mode, ...(internetEnabled ? { internet_enabled: true } : {}) },
      },
    );
    setSessions((previous) => [session, ...previous]);
    setSelection((current) =>
      current?.key === key ? { ...current, id: session.id } : current,
    );
    return session;
  }

  async function moreSessions() {
    setLoadingMore(true);
    try {
      const result = await requestJson<HermesSessionList>(
        `${api}/api/sessions?mode=${mode}&offset=${sessions.length}`,
      );
      setSessions((items) => [
        ...items,
        ...result.data.filter(
          (item) => !items.some((previous) => previous.id === item.id),
        ),
      ]);
      setHasMore(result.has_more);
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setLoadingMore(false);
    }
  }

  function newSession() {
    setError("");
    setSelection({ key: `draft-${++draftNumber.current}` });
    setShowHistory(false);
  }

  function track(id: string, runId: string, input: string) {
    const replace = (session: Session) =>
      session.id === id
        ? {
            ...session,
            last_run_id: runId,
            title:
              session.last_run_id === null && session.title === "新会话"
                ? input.replace(/\s+/g, " ").slice(0, 60)
                : session.title,
          }
        : session;
    setSessions((items) => items.map(replace));
  }

  async function remove(session: Session) {
    setError("");
    try {
      await requestJson(`${api}/api/sessions/${session.id}`, {
        method: "DELETE",
      });
      setSessions((items) => items.filter((item) => item.id !== session.id));
      setSelection((current) =>
        current?.id === session.id ? { key: "draft" } : current,
      );
    } catch (failure) {
      setError(errorText(failure));
    }
  }

  const matches = query.trim().toLocaleLowerCase();
  const visibleSessions = sessions.filter((session) =>
    session.title.toLocaleLowerCase().includes(matches),
  );
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
          <span>
            {ui("会话按项目查看", "Conversations are organized by project")}
          </span>
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
        onClick={newSession}
      >
        {ui("新建会话", "New conversation")}
      </Button>
      <Input.Search
        aria-label={ui("搜索会话", "Search conversations")}
        placeholder={ui("搜索会话", "Search conversations")}
        allowClear
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <div className="agent-history-heading">
        {ui("会话记录", "Conversations")}
      </div>
      {error && <Alert type="error" message={error} showIcon />}
      <div className="agent-history">
        {visibleSessions.map((session) => {
          const timestamp =
            typeof session.last_active === "number"
              ? new Date(session.last_active * 1000).toISOString()
              : undefined;
          return (
            <div
              key={session.id}
              className={`agent-history-item${selected?.id === session.id ? " selected" : ""}`}
            >
              <button
                className="agent-history-title"
                title={session.title}
                aria-current={selected?.id === session.id ? "true" : undefined}
                onClick={() => {
                  if (selection?.id !== session.id)
                    setSelection({ key: session.id, id: session.id });
                  setShowHistory(false);
                }}
              >
                {session.title}
                {timestamp && (
                  <time className="agent-history-time" dateTime={timestamp}>
                    {conversationTime(timestamp)}
                  </time>
                )}
              </button>
              <Space className="agent-history-actions" size={0}>
                <Popconfirm
                  title={ui("删除这段会话？", "Delete this conversation?")}
                  onConfirm={() => remove(session)}
                >
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    aria-label={ui("删除会话", "Delete conversation")}
                  />
                </Popconfirm>
              </Space>
            </div>
          );
        })}
        {hasMore && (
          <Button
            type="link"
            loading={loadingMore}
            onClick={() => void moreSessions()}
          >
            {ui("更多会话", "More conversations")}
          </Button>
        )}
      </div>
      <Link to="/agent/history" className="agent-muted">
        <HistoryOutlined /> {ui("原有记录", "Previous conversations")}
      </Link>
    </aside>
  );

  return (
    <AgentWorkspaceLayout
      layout={layout}
      sidebar={sidebar}
      historyOpen={showHistory}
      onHistoryOpen={setShowHistory}
      historyCloseButton={historyCloseButton}
      modeLabel={
        mode === "agent" ? ui("智能体", "Agent") : ui("快速对话", "Chat")
      }
      title={selected?.title}
      actions={<RuntimeSwitch modern />}
    >
      {selection ? (
        <Thread
          key={selection.key}
          mode={mode}
          session={selected}
          onCreate={(internetEnabled) => create(selection.key, internetEnabled)}
          onSessionChange={(updated) =>
            setSessions((items) =>
              items.map((item) =>
                item.id === updated.id
                  ? { ...item, internet_enabled: updated.internet_enabled }
                  : item,
              ),
            )
          }
          publicWebAvailable={publicWebAvailable}
          onRun={track}
          layout={layout}
        />
      ) : (
        <div className="agent-messages">
          <Spin aria-label={ui("加载会话", "Loading conversations")} />
        </div>
      )}
    </AgentWorkspaceLayout>
  );
}

function Welcome({ mode }: { mode: Mode }) {
  const ui = useComputeText();
  const navigate = useNavigate();
  return (
    <div className="agent-welcome">
      <RobotOutlined />
      <Typography.Title level={2}>
        {mode === "agent"
          ? ui("从项目数据中寻找答案", "Find answers in your project data")
          : ui("开始一段对话", "Start a conversation")}
      </Typography.Title>
      {mode === "agent" && (
        <p>
          {ui(
            "可以直接提问，或从已发布的科研业务流开始任务。",
            "Ask a question or start a task from a published research workflow.",
          )}
        </p>
      )}
      <div className="agent-example-questions">
        {mode === "agent" && (
          <Button onClick={() => navigate("/business-flows")}>
            {ui("从业务流开始任务", "Start a task with a business flow")}
          </Button>
        )}
      </div>
    </div>
  );
}

function Discovery({ publicWebAvailable }: { publicWebAvailable: boolean }) {
  const ui = useComputeText();
  const [visible, setVisible] = useState(false);
  const [skills, setSkills] = useState<HermesSkill[]>();
  const [toolsets, setToolsets] = useState<HermesToolset[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function open() {
    if (loading || skills) return;
    setLoading(true);
    try {
      const [skillList, toolsetList] = await Promise.all([
        requestJson<HermesSkillList>(`${api}/v1/skills`),
        requestJson<HermesToolsetList>(`${api}/v1/toolsets`),
      ]);
      setSkills(skillList.data);
      setToolsets(
        toolsetList.data.filter(
          (toolset) =>
            toolset.enabled &&
            toolset.configured !== false &&
            (toolset.name !== "web" || publicWebAvailable),
        ),
      );
      setError("");
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setLoading(false);
    }
  }
  const toolsetLabels: Record<string, [string, string]> = {
    skills: ["技能查阅", "Skill discovery"],
    clarify: ["澄清问题", "Clarifying questions"],
    web: ["公开网页检索", "Public web research"],
    todo: ["会话任务清单", "Conversation task list"],
    stisp_business_flows: ["科研业务流", "Research workflows"],
    stisp_project_data: ["项目资料与知识", "Project data and knowledge"],
  };
  return (
    <Popover
      placement="topLeft"
      trigger="click"
      open={visible}
      title={ui("技能与工具", "Skills and tools")}
      onOpenChange={(next) => {
        setVisible(next);
        if (next) void open();
      }}
      content={
        <div className="agent-tools-panel">
          {loading && (
            <Spin
              size="small"
              aria-label={ui("加载技能与工具", "Loading skills and tools")}
            />
          )}
          {error && (
            <Alert
              type="error"
              message={error}
              action={
                <Button type="link" size="small" onClick={() => void open()}>
                  {ui("重试", "Retry")}
                </Button>
              }
            />
          )}
          {skills && (
            <>
              <section className="agent-tool-field">
                <Typography.Text strong>{ui("技能", "Skills")}</Typography.Text>
                {skills.length === 0 && (
                  <p>{ui("暂无可用技能", "No skills available")}</p>
                )}
                {skills.map((skill) => (
                  <div key={skill.name}>
                    <Typography.Text code>{skill.name}</Typography.Text>
                    <p>{skill.description}</p>
                  </div>
                ))}
              </section>
              <section className="agent-tool-field">
                <Typography.Text strong>
                  {ui("工具集", "Toolsets")}
                </Typography.Text>
                {toolsets.length === 0 && (
                  <p>{ui("暂无可用工具集", "No toolsets available")}</p>
                )}
                {toolsets.map((toolset) => {
                  const label = toolsetLabels[toolset.name];
                  return (
                    <div key={toolset.name}>
                      <Typography.Text>
                        {label ? ui(label[0], label[1]) : toolset.label}
                      </Typography.Text>
                      <Flex gap={4} wrap>
                        {toolset.tools.map((tool) => (
                          <Typography.Text code key={tool}>
                            {tool}
                          </Typography.Text>
                        ))}
                      </Flex>
                    </div>
                  );
                })}
              </section>
            </>
          )}
        </div>
      }
    >
      <Button
        type="text"
        icon={<ApiOutlined />}
        aria-label={ui("技能与工具", "Skills and tools")}
        aria-expanded={visible}
        className={visible ? "agent-tool-active" : undefined}
      >
        {ui("技能与工具", "Skills and tools")}
      </Button>
    </Popover>
  );
}

function workflowId(message: Message) {
  if (message.role !== "tool" || message.tool_name !== "start_business_flow")
    return undefined;
  try {
    const content = record(
      typeof message.content === "string"
        ? JSON.parse(message.content)
        : message.content,
    );
    return typeof content.workflowId === "string" &&
      /^[0-9a-f-]{36}$/.test(content.workflowId)
      ? content.workflowId
      : undefined;
  } catch {
    return undefined;
  }
}

function Thread({
  mode,
  session,
  onCreate,
  onSessionChange,
  onRun,
  publicWebAvailable,
  layout,
}: {
  mode: Mode;
  session?: Session;
  onCreate: (internetEnabled: boolean) => Promise<Session>;
  onSessionChange: (session: Session) => void;
  onRun: (sessionId: string, runId: string, input: string) => void;
  publicWebAvailable: boolean;
  layout: ReturnType<typeof useAgentLayout>;
}) {
  const ui = useComputeText();
  const navigate = useNavigate();
  const location = useLocation();
  const prefill = record(location.state).query;
  const [prompt, setPrompt] = useState(
    typeof prefill === "string" ? prefill : "",
  );
  const [messages, setMessages] = useState<Message[]>([]);
  const [runId, setRunId] = useState(session?.last_run_id ?? null);
  const [pendingInput, setPendingInput] = useState("");
  const [answer, setAnswer] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [commentary, setCommentary] = useState("");
  const [steps, setSteps] = useState<Progress[]>([]);
  const [control, setControl] = useState<Control>();
  const [clarification, setClarification] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(Boolean(runId));
  const [retry, setRetry] = useState(0);
  const [checkingHistory, setCheckingHistory] = useState(Boolean(session));
  const [draftInternet, setDraftInternet] = useState(false);
  const [changingInternet, setChangingInternet] = useState(false);
  const internetEnabled =
    publicWebAvailable && (session?.internet_enabled ?? draftInternet);
  const [showLatest, setShowLatest] = useState(false);
  const cursor = useRef(-1);
  const initialSessionId = useRef(session?.id);
  const viewport = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  const lastScrollTop = useRef(0);
  const submission = useRef<{ input: string; key: string } | undefined>(
    undefined,
  );
  const project = useProjectContext();

  async function toggleInternet() {
    if (!session) {
      setDraftInternet(!internetEnabled);
      return;
    }
    setChangingInternet(true);
    try {
      const { session: updated } = await requestJson<HermesSessionEnvelope>(
        `${api}/api/sessions/${session.id}`,
        {
          method: "PATCH",
          body: { internet_enabled: !internetEnabled },
        },
      );
      onSessionChange(updated);
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setChangingInternet(false);
    }
  }

  function scrollToLatest() {
    const box = viewport.current;
    if (!box) return;
    followLatest.current = true;
    setShowLatest(false);
    box.scrollTop = box.scrollHeight;
    lastScrollTop.current = box.scrollTop;
  }

  useLayoutEffect(() => {
    if (followLatest.current && viewport.current) {
      const box = viewport.current;
      box.scrollTop = box.scrollHeight;
      lastScrollTop.current = box.scrollTop;
    }
  }, [
    messages,
    pendingInput,
    answer,
    reasoning,
    commentary,
    steps,
    control,
    busy,
    error,
  ]);

  async function history(sessionId: string, signal: AbortSignal) {
    const { data } = await requestJson<HermesMessageList>(
      `${api}/api/sessions/${sessionId}/messages`,
      { signal },
    );
    setMessages(data);
    return data;
  }

  useEffect(() => {
    if (!initialSessionId.current) return;
    const controller = new AbortController();
    void history(initialSessionId.current, controller.signal)
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(errorText(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setCheckingHistory(false);
      });
    return () => controller.abort();
  }, []);

  const sessionId = session?.id;
  useEffect(() => {
    if (!runId || !sessionId) return;
    const controller = new AbortController();
    const { signal } = controller;
    const url = `${api}/v1/runs/${runId}`;
    async function connect(id: string) {
      setBusy(true);
      let last: unknown;
      try {
        for (let attempt = 0; attempt < 3; attempt++) {
          const state = await requestJson<HermesRunStatus>(url, { signal });
          if (terminalStatuses.has(state.status)) {
            if (state.error) setError(state.error);
            const saved = await history(id, signal);
            const persisted =
              state.output &&
              saved.some(
                (message) =>
                  message.role === "assistant" &&
                  message.content === state.output,
              );
            if (persisted) setAnswer("");
            else if (state.output) setAnswer(state.output);
            setPendingInput("");
            setControl(undefined);
            setBusy(false);
            setRunId(null);
            return;
          }
          setControl(state.pending_controls?.map(pendingControl).find(Boolean));
          try {
            await requestEventStream(
              `${url}/events?last_seq=${cursor.current}`,
              (_, raw) => {
                const event = record(raw);
                const seq = event.seq;
                if (typeof seq === "number") {
                  if (seq <= cursor.current) return;
                  cursor.current = seq;
                }
                if (
                  event.event === "message.delta" &&
                  typeof event.delta === "string"
                ) {
                  const delta = event.delta;
                  setAnswer((text) => text + delta);
                }
                if (
                  event.event === "message.interim" &&
                  typeof event.text === "string"
                ) {
                  const text = event.text;
                  setCommentary((previous) =>
                    [previous, text].filter(Boolean).join("\n\n"),
                  );
                  if (event.already_streamed) setAnswer("");
                }
                if (
                  event.event === "tool.started" ||
                  event.event === "tool.completed"
                ) {
                  const name =
                    typeof event.tool === "string" ? event.tool : "工具";
                  const id =
                    typeof event.tool_call_id === "string"
                      ? event.tool_call_id
                      : name;
                  const status =
                    event.event === "tool.started"
                      ? "运行中"
                      : event.error
                        ? "失败"
                        : "已完成";
                  setSteps((previous) => [
                    ...previous.filter((step) => step.id !== id),
                    { id, name, status },
                  ]);
                }
                if (
                  event.event === "reasoning.available" &&
                  typeof event.text === "string"
                ) {
                  const text = event.text;
                  setReasoning((previous) => previous + text);
                }
                const updated = pendingControl(event);
                if (updated) setControl(updated);
                if (
                  event.event === "clarify.settled" ||
                  event.event === "approval.settled"
                )
                  setControl(undefined);
                if (event.event === "replay.truncated") setAnswer("");
              },
              signal,
            );
          } catch (failure) {
            signal.throwIfAborted();
            last = failure;
          }
        }
        throw last ?? new Error("实时连接中断，运行仍可恢复");
      } catch (failure) {
        if (!signal.aborted) {
          if (failure instanceof ApiError && failure.status === 404) {
            setBusy(false);
            setRunId(null);
          } else {
            setError(errorText(failure));
          }
        }
      }
    }
    void connect(sessionId);
    return () => controller.abort();
  }, [runId, retry, sessionId]);

  async function send() {
    const input = prompt.trim();
    if (!input || busy || checkingHistory || changingInternet) return;
    if (submission.current?.input !== input)
      submission.current = {
        input,
        key: Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
          byte.toString(16).padStart(2, "0"),
        ).join(""),
      };
    setError("");
    setBusy(true);
    try {
      const target = session ?? (await onCreate(internetEnabled));
      const run = await requestJson<HermesRunAdmission>(`${api}/v1/runs`, {
        method: "POST",
        body: { input, session_id: target.id },
        idempotencyKey: submission.current.key,
      });
      cursor.current = -1;
      scrollToLatest();
      submission.current = undefined;
      setPrompt("");
      setPendingInput(input);
      setAnswer("");
      setReasoning("");
      setCommentary("");
      setSteps([]);
      onRun(target.id, run.run_id, input);
      setRunId(run.run_id);
    } catch (failure) {
      setBusy(false);
      setError(errorText(failure));
    }
  }

  async function controlRun(
    action: "stop" | "clarify" | "approval",
    reply = clarification,
  ) {
    if (!runId) return;
    try {
      await requestJson(`${api}/v1/runs/${runId}/${action}`, {
        method: "POST",
        body:
          action === "stop"
            ? {}
            : {
                request_id: control?.request_id,
                execution_generation: control?.execution_generation,
                ...(action === "clarify"
                  ? { answer: reply }
                  : { choice: reply }),
              },
      });
      if (action !== "stop") {
        setControl(undefined);
        setClarification("");
      }
    } catch (failure) {
      setError(errorText(failure));
    }
  }

  const active = Boolean(pendingInput || busy || answer || control);
  return (
    <>
      <div
        className="agent-messages"
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
        {checkingHistory && (
          <Spin aria-label={ui("加载会话", "Loading conversation")} />
        )}
        {!checkingHistory && !messages.length && !active && (
          <Welcome mode={mode} />
        )}
        {messages.map((message) => {
          const workflow = workflowId(message);
          if (workflow) {
            const query = new URLSearchParams({
              run: workflow,
              projectTagId: String(project?.current ?? ""),
            });
            return (
              <div className="agent-run-notice" key={message.id}>
                <Link to={`/business-flows?${query}`}>
                  {ui("查看业务流运行", "View workflow run")}
                </Link>
              </div>
            );
          }
          if (
            message.display_kind === "hidden" ||
            typeof message.content !== "string" ||
            !message.content
          )
            return null;
          if (message.role === "user")
            return (
              <div className="agent-user-message" key={message.id}>
                {message.content}
              </div>
            );
          if (message.role !== "assistant") return null;
          return (
            <section className="agent-turn" key={message.id}>
              <div className="agent-assistant-message">
                <AssistantHeading />
                <SafeMarkdown text={message.content} links />
              </div>
            </section>
          );
        })}
        {active && (
          <>
            {pendingInput && (
              <div className="agent-user-message">{pendingInput}</div>
            )}
            <section className="agent-turn agent-assistant-message">
              <AssistantHeading
                status={
                  busy
                    ? control
                      ? ui("等待您回答", "Waiting for your reply")
                      : ui("生成中", "Generating")
                    : undefined
                }
              />
              {steps.length > 0 && (
                <Flex gap="small" wrap className="agent-run-notice">
                  {steps.map((step) => (
                    <Tag
                      color={step.status === "失败" ? "error" : undefined}
                      key={step.id}
                    >
                      {step.name} · {step.status}
                    </Tag>
                  ))}
                </Flex>
              )}
              {commentary && (
                <div className="agent-muted">
                  <SafeMarkdown text={commentary} />
                </div>
              )}
              {reasoning && (
                <Collapse
                  bordered={false}
                  size="small"
                  className="agent-thinking-panel"
                  items={[
                    {
                      key: "reasoning",
                      label: ui("推理过程", "Reasoning"),
                      children: (
                        <div className="agent-thinking-content">
                          <SafeMarkdown text={reasoning} />
                        </div>
                      ),
                    },
                  ]}
                />
              )}
              {answer && (
                <div aria-live="polite">
                  <SafeMarkdown text={answer} links />
                </div>
              )}
              {control && (
                <Card
                  className="agent-run-notice"
                  size="small"
                  title={control.question}
                >
                  <Flex gap="small" wrap>
                    {control.choices.map((choice) => (
                      <Button
                        key={choice}
                        onClick={() => {
                          if (control.kind === "approval")
                            void controlRun("approval", choice);
                          else
                            setClarification((current) =>
                              current ? `${current}, ${choice}` : choice,
                            );
                        }}
                      >
                        {control.kind !== "approval"
                          ? choice
                          : choice === "once"
                            ? ui("批准一次", "Approve once")
                            : ui("拒绝", "Deny")}
                      </Button>
                    ))}
                    {control.kind === "clarify" && (
                      <>
                        <Input
                          aria-label={ui("补充信息", "Additional information")}
                          value={clarification}
                          onChange={(event) =>
                            setClarification(event.target.value)
                          }
                        />
                        <Button
                          disabled={!clarification.trim()}
                          onClick={() => void controlRun("clarify")}
                        >
                          {ui("提交", "Submit")}
                        </Button>
                      </>
                    )}
                  </Flex>
                </Card>
              )}
            </section>
          </>
        )}
        {error && (
          <Alert
            className="agent-run-notice"
            type="error"
            showIcon
            message={error}
            action={
              runId && (
                <Button
                  onClick={() => {
                    setError("");
                    setRetry((attempt) => attempt + 1);
                  }}
                >
                  {ui("恢复连接", "Reconnect")}
                </Button>
              )
            }
          />
        )}
      </div>
      {showLatest && (
        <div className="agent-latest-bar">
          <Button icon={<ArrowDownOutlined />} onClick={scrollToLatest}>
            {ui("回到最新", "Jump to latest")}
          </Button>
        </div>
      )}
      <AgentComposerFrame layout={layout}>
        <div className="agent-input-row">
          <Input.TextArea
            id="agent-message-input"
            aria-label={ui("输入消息", "Message")}
            placeholder={ui(
              "输入问题，Enter 发送，Shift+Enter 换行",
              "Ask a question. Enter to send, Shift+Enter for a new line",
            )}
            value={prompt}
            style={{ height: layout.input, resize: "none" }}
            maxLength={12000}
            onChange={(event) => setPrompt(event.target.value)}
            onPressEnter={(event) => {
              if (event.shiftKey || event.nativeEvent.isComposing) return;
              event.preventDefault();
              void send();
            }}
          />
        </div>
        <div className="agent-composer-footer">
          <div className="agent-composer-tools">
            {mode === "agent" && (
              <Button
                type="text"
                onClick={() => navigate("/business-flows")}
                icon={<NodeIndexOutlined />}
              >
                {ui("业务流", "Business flows")}
              </Button>
            )}
            <Discovery publicWebAvailable={publicWebAvailable} />
            {publicWebAvailable && (
              <Button
                type="text"
                icon={<GlobalOutlined />}
                aria-label={ui("联网检索", "Web research")}
                aria-pressed={internetEnabled}
                title={ui(
                  "开启后将公开检索词或网址发送给搜索服务",
                  "Sends public queries or URLs to the search service",
                )}
                className={internetEnabled ? "agent-tool-active" : undefined}
                loading={changingInternet}
                onClick={() => void toggleInternet()}
              >
                {ui("联网检索", "Web research")}
              </Button>
            )}
          </div>
          {busy && runId ? (
            <Button
              className="agent-send-button"
              icon={<StopOutlined />}
              aria-label={ui("停止回答", "Stop response")}
              title={ui("停止回答", "Stop response")}
              onClick={() => void controlRun("stop")}
            />
          ) : (
            <Button
              type="primary"
              className="agent-send-button"
              icon={<SendOutlined />}
              aria-label={ui("发送", "Send")}
              title={ui("发送", "Send")}
              onClick={() => void send()}
              disabled={
                checkingHistory || busy || changingInternet || !prompt.trim()
              }
            />
          )}
        </div>
      </AgentComposerFrame>
    </>
  );
}

function AssistantHeading({ status }: { status?: string }) {
  return (
    <Space className="agent-answer-heading">
      <RobotOutlined />
      <strong>MH-Agent</strong>
      {status && (
        <span className="agent-answer-status is-active">{status}</span>
      )}
    </Space>
  );
}
