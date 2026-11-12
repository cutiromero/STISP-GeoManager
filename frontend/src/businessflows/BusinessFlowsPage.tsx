import {
  ApartmentOutlined,
  AuditOutlined,
  BranchesOutlined,
  DatabaseOutlined,
  FileDoneOutlined,
  MenuOutlined,
  PlusOutlined,
  RightOutlined,
  ReloadOutlined,
  RobotOutlined,
  SearchOutlined,
  UserOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Drawer,
  Empty,
  Input,
  Layout,
  Select,
  Space,
  Spin,
  Tag,
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import WorkspaceHeader from "../components/WorkspaceHeader";
import { ApiError } from "../api/client";
import { downloadResponseDiagnostics } from "../api/responseDiagnostics";
import { useAppContext } from "../contexts/AppContext";
import { useProjectContext } from "../projects/ProjectContext";
import { useAgentBootstrapState } from "../agent/useAgentBootstrap";
import { useComputeText } from "../compute/ui";
import { requestScope } from "../projects/session";
import { businessFlowsApi } from "../api/businessFlows";
import type {
  BusinessFlowDefinition,
  BusinessFlowDetail,
  BusinessFlowNode,
  BusinessFlowSpec,
  BusinessFlowSummary,
} from "../api/generated/types.gen";
import BusinessFlowGraph from "./BusinessFlowGraph";
import BusinessFlowEditor from "./BusinessFlowEditor";
import "./business-flows.css";

const dataTypes: Record<string, string> = {
  vector: "矢量",
  raster: "栅格",
  table: "数据表",
  document: "文档",
  image: "图片",
  gene: "基因数据",
};
export default function BusinessFlowsPage() {
  const ui = useComputeText();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { user } = useAppContext();
  const project = useProjectContext();
  const { bootstrap } = useAgentBootstrapState();
  const [searchParams, setSearchParams] = useSearchParams();
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const scope = `${user?.id ?? "anonymous"}:${project?.current ?? ""}`;
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const [catalogScope, setCatalogScope] = useState(scope);
  const [catalogItems, setItems] = useState<BusinessFlowSummary[]>([]);
  const items = catalogScope === scope ? catalogItems : [];
  const [canManageValue, setCanManage] = useState(false);
  const canManage = catalogScope === scope && canManageValue;
  const [nextOffset, setNextOffset] = useState<number>();
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState("");
  const listSequence = useRef(0);
  const moreRequest = useRef<AbortController | null>(null);
  const [initialSelection, setInitialSelection] = useState<{
    scope: string;
    id?: number;
  }>({ scope });
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [listAttempt, setListAttempt] = useState(0);
  const [detailValue, setDetail] = useState<BusinessFlowDetail | null>(null);
  const [detailScope, setDetailScope] = useState(scope);
  const [detailError, setDetailError] = useState("");
  const [detailAttempt, setDetailAttempt] = useState(0);
  const [detailLoading, setDetailLoading] = useState(false);
  const [queryValue, setQuery] = useState({ scope, value: "" });
  const query = queryValue.scope === scope ? queryValue.value : "";
  const normalizedQuery = query.trim().slice(0, 120);
  const [nodeId, setNodeId] = useState<string>();
  const [goal, setGoal] = useState("");
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [editor, setEditor] = useState<"create" | "version" | null>(null);
  const selected = Number(searchParams.get("flow"));
  const selectedId =
    initialSelection.scope === scope
      ? Number.isSafeInteger(selected) && selected > 0
        ? selected
        : initialSelection.id
      : undefined;
  const detail =
    detailScope === scope && detailValue?.flow.id === selectedId
      ? detailValue
      : null;
  const visible = useMemo(
    () =>
      items.filter((item) =>
        `${item.name} ${item.description} ${item.code}`
          .toLowerCase()
          .includes(query.trim().toLowerCase()),
      ),
    [items, query],
  );
  const previousScope = useRef(scope);
  useEffect(() => {
    if (previousScope.current === scope) return;
    previousScope.current = scope;
    setInitialSelection({ scope });
    setSearchParams({});
    setGoal("");
    setNodeId(undefined);
    setEditor(null);
    setCatalogOpen(false);
  }, [scope, setSearchParams]);
  useEffect(() => {
    const owned = ++listSequence.current;
    const controller = new AbortController();
    moreRequest.current?.abort();
    moreRequest.current = null;
    setLoadingMore(false);
    setMoreError("");
    setNextOffset(undefined);
    setLoading(true);
    setListError("");
    if (catalogScope !== scope) {
      setCatalogScope(scope);
      setItems([]);
      setCanManage(false);
    }
    const load = () => {
      void businessFlowsApi
        .list({
          q: normalizedQuery,
          offset: 0,
          limit: 50,
          signal: controller.signal,
        })
        .then((result) => {
          if (
            controller.signal.aborted ||
            currentScope.current !== scope ||
            owned !== listSequence.current
          )
            return;
          setCatalogScope(scope);
          setItems(result.items);
          setCanManage(result.canManage);
          setNextOffset(result.nextOffset);
          setInitialSelection((previous) =>
            previous.scope === scope && previous.id !== undefined
              ? previous
              : { scope, id: result.items[0]?.id },
          );
        })
        .catch((error) => {
          if (
            !controller.signal.aborted &&
            currentScope.current === scope &&
            owned === listSequence.current
          )
            setListError(
              error instanceof Error ? error.message : "无法读取业务流目录",
            );
        })
        .finally(() => {
          if (
            !controller.signal.aborted &&
            currentScope.current === scope &&
            owned === listSequence.current
          )
            setLoading(false);
        });
    };
    const timer = setTimeout(load, normalizedQuery ? 280 : 0);
    return () => {
      clearTimeout(timer);
      controller.abort();
      moreRequest.current?.abort();
    };
  }, [scope, normalizedQuery, listAttempt]);
  const loadMore = async () => {
    if (nextOffset === undefined || loading || moreRequest.current) return;
    const controller = new AbortController();
    moreRequest.current = controller;
    const owned = listSequence.current;
    setLoadingMore(true);
    setMoreError("");
    try {
      const result = await businessFlowsApi.list({
        q: normalizedQuery,
        offset: nextOffset,
        limit: 50,
        signal: controller.signal,
      });
      if (
        controller.signal.aborted ||
        currentScope.current !== scope ||
        owned !== listSequence.current
      )
        return;
      setItems((previous) => [
        ...new Map(
          [...previous, ...result.items].map((item) => [item.id, item]),
        ).values(),
      ]);
      setNextOffset(result.nextOffset);
      setCanManage(result.canManage);
    } catch (error) {
      if (
        !controller.signal.aborted &&
        currentScope.current === scope &&
        owned === listSequence.current
      )
        setMoreError(
          error instanceof Error ? error.message : "暂时无法读取更多业务流",
        );
    } finally {
      if (moreRequest.current === controller) {
        moreRequest.current = null;
        if (alive.current) setLoadingMore(false);
      }
    }
  };
  useEffect(() => {
    if (detailScope !== scope || detailValue?.flow.id !== selectedId) {
      setDetail(null);
      setGoal("");
      setNodeId(undefined);
    }
    setDetailScope(scope);
    setDetailLoading(false);
    setDetailError("");
    if (selectedId === undefined) return;
    const controller = new AbortController();
    setDetailLoading(true);
    void businessFlowsApi
      .detail(selectedId, { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted && currentScope.current === scope)
          setDetail(result);
      })
      .catch((error) => {
        if (!controller.signal.aborted && currentScope.current === scope) {
          if (
            error instanceof ApiError &&
            [401, 403, 404].includes(error.status)
          )
            setDetail(null);
          setDetailError(
            error instanceof Error ? error.message : "无法读取业务流详情",
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && currentScope.current === scope)
          setDetailLoading(false);
      });
    return () => controller.abort();
  }, [selectedId, scope, detailAttempt]);
  const requestedVersion = Number(searchParams.get("version"));
  const version =
    detail?.versions.find((item) => item.id === requestedVersion) ??
    detail?.version;
  const spec = version?.definition;
  // Identical per-input notes are shown once in the section heading.
  const inputNotes = spec?.inputRequirements ?? [];
  const firstInputNote = inputNotes[0]?.description;
  const sharedInputNote =
    inputNotes.length > 1 &&
    firstInputNote &&
    inputNotes.every(
      (input) =>
        input.description === firstInputNote && !input.requiredFields.length,
    )
      ? firstInputNote
      : "";
  const node = spec?.nodes.find((item) => item.id === nodeId) ?? spec?.nodes[0];
  const aiCount = spec?.nodes.filter((item) => item.review.ai).length ?? 0;
  const humanCount =
    spec?.nodes.filter((item) => item.review.human || item.kind === "human")
      .length ?? 0;
  const choose = (id: number) => {
    setSearchParams({ flow: String(id) });
    setCatalogOpen(false);
  };
  const canStart = Boolean(
    user &&
    bootstrap?.canAgent &&
    detail?.flow.isActive &&
    version?.status === "published",
  );
  const launch = () => {
    if (!detail || !version || !canStart) return;
    navigate(`/agent/workbench?projectTagId=${project?.current ?? "1"}`, {
      state: {
        businessFlowLaunch: {
          definitionId: detail.flow.id,
          versionId: version.id,
          title: detail.flow.name,
          goal: goal.trim() || detail.flow.description || detail.flow.name,
        },
      },
    });
  };
  const save = async (
    metadata: Pick<BusinessFlowDefinition, "code" | "name" | "description">,
    definition: BusinessFlowSpec,
  ) => {
    const ensureScope = requestScope();
    const ensureCurrent = () => {
      ensureScope();
      if (!alive.current) throw new DOMException("页面已关闭", "AbortError");
    };
    const result =
      editor === "version" && detail
        ? await businessFlowsApi.publish(detail.flow.id, {
            definition,
            updatedAt: detail.flow.updatedAt,
          })
        : await businessFlowsApi.create({
            ...metadata,
            definition,
            isActive: true,
          });
    ensureCurrent();
    setEditor(null);
    setDetail(result);
    setDetailScope(scope);
    setSearchParams({
      flow: String(result.flow.id),
      ...(result.version ? { version: String(result.version.id) } : {}),
    });
    setListAttempt((value) => value + 1);
    message.success(ui("业务流版本已发布", "Business flow version published"));
  };
  const catalog = (
    <aside
      className="business-flow-catalog"
      aria-label={ui("业务流目录", "Business flow catalog")}
    >
      <div className="business-flow-catalog-heading">
        <h1>{ui("业务流", "Business flows")}</h1>
        <p>
          {ui(
            "把数据、算子与专业判断组织成可靠的科研路径。",
            "Organize data, operators and professional decisions into a reliable research path.",
          )}
        </p>
      </div>
      <Input
        prefix={<SearchOutlined />}
        className="business-flow-catalog-search"
        placeholder={ui("查找科研流程", "Find a research flow")}
        aria-label={ui("搜索业务流", "Search business flows")}
        allowClear
        value={query}
        maxLength={120}
        onChange={(event) => setQuery({ scope, value: event.target.value })}
      />
      {canManage && (
        <Button icon={<PlusOutlined />} onClick={() => setEditor("create")}>
          {ui("登记业务流", "Register a flow")}
        </Button>
      )}
      <div className="business-flow-catalog-list">
        {loading && (items.length === 0 || visible.length === 0) ? (
          <div className="business-flow-loading">
            <Spin />
          </div>
        ) : listError ? (
          <Alert
            type="error"
            showIcon
            title={listError}
            action={
              <Button
                size="small"
                aria-label={ui("重试", "Retry")}
                onClick={() => setListAttempt((value) => value + 1)}
              >
                {ui("重试", "Retry")}
              </Button>
            }
          />
        ) : visible.length ? (
          visible.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`business-flow-catalog-card${selectedId === item.id ? " is-selected" : ""}`}
              aria-current={selectedId === item.id ? "true" : undefined}
              onClick={() => choose(item.id)}
            >
              <span className="business-flow-card-top">
                <span className="business-flow-card-symbol">
                  <ApartmentOutlined />
                </span>
                <strong>{item.name}</strong>
                <span className="business-flow-card-version">
                  {item.version
                    ? `v${item.version}`
                    : ui("未发布", "Unpublished")}
                </span>
              </span>
              <p>
                {item.description ||
                  ui(
                    "已登记的科研任务流程。",
                    "A registered research workflow.",
                  )}
              </p>
              <span className="business-flow-card-foot">
                <span>
                  <BranchesOutlined />
                  {item.nodeCount}
                  {ui(" 个节点", " nodes")}
                </span>
                {item.aiReviewCount > 0 && (
                  <span>
                    <AuditOutlined />
                    {item.aiReviewCount}
                  </span>
                )}
                {item.humanReviewCount > 0 && (
                  <span className="has-human">
                    <UserOutlined />
                    {item.humanReviewCount}
                  </span>
                )}
                {!item.isActive && <span>{ui("已停用", "Inactive")}</span>}
              </span>
            </button>
          ))
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              query
                ? ui("没有匹配的业务流", "No matching flows")
                : ui(
                    "当前项目尚未登记业务流",
                    "No flows registered in this project",
                  )
            }
          />
        )}
        {loading && visible.length > 0 && (
          <Spin
            size="small"
            aria-label={ui("正在查找业务流", "Finding flows")}
          />
        )}
        {moreError && <Alert type="error" showIcon title={moreError} />}
        {nextOffset !== undefined && !loading && (
          <Button block loading={loadingMore} onClick={() => void loadMore()}>
            {ui(
              moreError ? "重试加载更多" : "加载更多业务流",
              moreError ? "Retry loading more" : "Load more flows",
            )}
          </Button>
        )}
      </div>
    </aside>
  );
  return (
    <Layout className="business-flows-shell">
      <WorkspaceHeader
        activeTab="businessFlows"
        canBrowseData={Boolean(user?.permissions.canBrowseData)}
      />
      <div className="business-flows-workspace">
        {catalog}
        <main className="business-flow-main">
          {detailLoading && !detail ? (
            <div className="business-flow-loading">
              <Spin />
            </div>
          ) : detailError && !detail ? (
            <div className="business-flow-empty-state">
              <Alert
                showIcon
                type="error"
                title={ui("业务流暂时无法打开", "Flow could not be opened")}
                description={detailError}
                action={
                  <Space wrap>
                    <Button
                      onClick={() => setDetailAttempt((value) => value + 1)}
                    >
                      {ui("重新加载", "Retry")}
                    </Button>
                    <Button type="text" onClick={downloadResponseDiagnostics}>
                      {ui("下载诊断", "Download diagnostics")}
                    </Button>
                  </Space>
                }
              />
            </div>
          ) : detail && version && spec ? (
            <>
              {detailError && (
                <Alert
                  type="warning"
                  title={ui(
                    "暂时无法更新，已保留当前流程",
                    "Update unavailable; current flow retained",
                  )}
                  description={detailError}
                  action={
                    <Button
                      onClick={() => setDetailAttempt((value) => value + 1)}
                    >
                      {ui("重新加载", "Retry")}
                    </Button>
                  }
                />
              )}
              <header className="business-flow-main-header">
                <div className="business-flow-topline">
                  <Space>
                    <Button
                      className="business-flow-mobile-trigger"
                      type="text"
                      icon={<MenuOutlined />}
                      aria-label={ui("流程目录", "Flow catalog")}
                      onClick={() => setCatalogOpen(true)}
                    >
                      {ui("流程目录", "Flow catalog")}
                    </Button>
                    <span className="business-flow-eyebrow">
                      <ApartmentOutlined />
                      {ui("科研任务的执行路径", "A guided research workflow")}
                    </span>
                  </Space>
                  <Space wrap>
                    <Button
                      type="text"
                      icon={<ReloadOutlined />}
                      aria-label={ui("刷新业务流", "Refresh flow")}
                      loading={detailLoading}
                      onClick={() => setDetailAttempt((value) => value + 1)}
                    />
                    <Tag variant="filled">{ui("已发布", "Published")}</Tag>
                    <Select
                      aria-label={ui("选择流程版本", "Select flow version")}
                      value={version.id}
                      options={detail.versions.map((item) => ({
                        value: item.id,
                        label: `v${item.version}`,
                      }))}
                      onChange={(id) =>
                        setSearchParams({
                          flow: String(detail.flow.id),
                          version: String(id),
                        })
                      }
                    />
                    <Button
                      type="primary"
                      className="business-flow-launch"
                      disabled={!canStart}
                      onClick={launch}
                    >
                      {ui("开始业务流", "Start flow")}
                    </Button>
                    {detail.canManage && (
                      <Button onClick={() => setEditor("version")}>
                        {ui("发布新版本", "Publish new version")}
                      </Button>
                    )}
                  </Space>
                </div>
                <h2>{detail.flow.name}</h2>
                <p className="business-flow-description">
                  {detail.flow.description}
                </p>
                <div className="business-flow-facts">
                  <span>
                    <BranchesOutlined />
                    {spec.nodes.length}
                    {ui(" 个执行节点", " execution nodes")}
                  </span>
                  <span>
                    <AuditOutlined />
                    {aiCount
                      ? ui(
                          `${aiCount} 处独立 AI 审核`,
                          `${aiCount} independent AI reviews`,
                        )
                      : ui("无需 AI 审核", "No AI review required")}
                  </span>
                  <span className={humanCount ? "is-human" : ""}>
                    <UserOutlined />
                    {humanCount
                      ? ui(
                          `${humanCount} 处人工决定`,
                          `${humanCount} human decisions`,
                        )
                      : ui("无需人工确认", "No human approval required")}
                  </span>
                  <span>
                    <DatabaseOutlined />
                    {spec.inputRequirements.length}
                    {ui(" 类输入资料", " input roles")}
                  </span>
                </div>
              </header>
              <div className="business-flow-main-body">
                {!detail.flow.isActive && (
                  <Alert
                    type="warning"
                    showIcon
                    title={ui(
                      "此业务流已停用，已有记录仍可查看。",
                      "This flow is inactive. Existing records remain available.",
                    )}
                    style={{ marginBottom: 20 }}
                  />
                )}
                <div className="business-flow-section-heading">
                  <h3>{ui("流程全貌", "Workflow at a glance")}</h3>
                  <p>
                    {ui(
                      "选择节点查看职责与审核边界",
                      "Select a node for responsibilities and review rules",
                    )}
                  </p>
                </div>
                <div className="business-flow-overview-grid">
                  <section className="business-flow-diagram-panel">
                    <BusinessFlowGraph
                      nodes={spec.nodes}
                      compact
                      selectedNode={node?.id}
                      onSelectNode={(next) => setNodeId(next.id)}
                    />
                  </section>
                  <FlowInspector node={node} spec={spec} />
                </div>
                <section className="business-flow-contracts">
                  {spec.skill && (
                    <details>
                      <summary>
                        {ui("配套执行技能", "Workflow skill")} ·{" "}
                        {spec.skill.title}
                      </summary>
                      <p>{spec.skill.instructions}</p>
                      {node && spec.skill.nodeInstructions?.[node.id] && (
                        <p>{spec.skill.nodeInstructions[node.id]}</p>
                      )}
                    </details>
                  )}
                  <div className="business-flow-section-heading">
                    <h3>{ui("开始前需要的资料", "Required inputs")}</h3>
                    <p>
                      {sharedInputNote ||
                        ui(
                          "启动时绑定本项目的授权资料",
                          "Bind authorized project data when starting",
                        )}
                    </p>
                  </div>
                  {spec.inputRequirements.length ? (
                    <div className="business-flow-inputs">
                      {spec.inputRequirements.map((input) => (
                        <div className="business-flow-input" key={input.key}>
                          <DatabaseOutlined />
                          <div>
                            <strong>{input.label}</strong>
                            <small
                              className={
                                input.required ? "is-required" : undefined
                              }
                            >
                              {input.required
                                ? ui("必需", "Required")
                                : ui("可选", "Optional")}
                            </small>
                            {!sharedInputNote && (
                              <p>
                                {input.description ||
                                  input.dataTypes
                                    .map((value) => dataTypes[value] ?? value)
                                    .join(" / ")}
                                {input.requiredFields.length
                                  ? ` · ${ui("需包含字段：", "Required fields: ")}${input.requiredFields.join("、")}`
                                  : ""}
                              </p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="business-flow-empty">
                      {ui(
                        "不需要预先绑定固定资料，可按任务目标读取已授权的项目信息。",
                        "No fixed input binding is required. Authorized project information can be used for the task.",
                      )}
                    </p>
                  )}
                </section>
                {spec.outputRequirements.length > 0 && (
                  <section className="business-flow-contracts">
                    <div className="business-flow-section-heading">
                      <h3>{ui("预期交付", "Expected deliverables")}</h3>
                    </div>
                    <Space wrap>
                      {spec.outputRequirements.map((output) => (
                        <Tag key={output} icon={<FileDoneOutlined />}>
                          {output}
                        </Tag>
                      ))}
                    </Space>
                  </section>
                )}
                <section className="business-flow-start">
                  <label htmlFor="business-flow-goal">
                    {ui(
                      "这次希望完成什么任务",
                      "What would you like to accomplish?",
                    )}
                  </label>
                  <div className="business-flow-start-row">
                    <Input.TextArea
                      id="business-flow-goal"
                      value={goal}
                      onChange={(event) => setGoal(event.target.value)}
                      autoSize={{ minRows: 2, maxRows: 4 }}
                      maxLength={12000}
                      placeholder={detail.flow.description || detail.flow.name}
                    />
                    <Button
                      type="primary"
                      icon={<RightOutlined />}
                      aria-label={ui("交给智能体执行", "Run with the agent")}
                      disabled={!canStart}
                      title={
                        !canStart
                          ? ui(
                              "登录并获得智能体权限后可发起业务流",
                              "Sign in with agent access to start a flow",
                            )
                          : undefined
                      }
                      onClick={launch}
                    >
                      {ui("交给智能体执行", "Run with the agent")}
                    </Button>
                  </div>
                  <p>
                    {ui(
                      "进入智能体后选择资料和模型。执行、独立审核与人工决定会沿同一条流程显示。",
                      "Choose data and models in the agent. Execution, independent review and human decisions appear along the same flow.",
                    )}
                  </p>
                </section>
              </div>
            </>
          ) : (
            <div className="business-flow-empty-state">
              <div>
                <Button
                  className="business-flow-mobile-trigger"
                  icon={<MenuOutlined />}
                  aria-label={ui("流程目录", "Flow catalog")}
                  onClick={() => setCatalogOpen(true)}
                >
                  {ui("打开流程目录", "Open flow catalog")}
                </Button>
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={
                    loading
                      ? ui("正在读取业务流…", "Loading flows…")
                      : ui(
                          "选择业务流，查看它的科研路径",
                          "Choose a flow to explore its research path",
                        )
                  }
                />
              </div>
            </div>
          )}
        </main>
      </div>
      <Drawer
        title={ui("业务流目录", "Business flow catalog")}
        placement="left"
        open={catalogOpen}
        onClose={() => setCatalogOpen(false)}
        size="default"
        classNames={{ root: "business-flow-catalog-drawer" }}
        styles={{ wrapper: { width: "min(340px, 92vw)" } }}
      >
        <div style={{ height: "100%", display: "flex" }}>{catalog}</div>
      </Drawer>
      {editor && (
        <BusinessFlowEditor
          open
          flow={editor === "version" ? detail?.flow : undefined}
          version={editor === "version" ? version : undefined}
          onClose={() => setEditor(null)}
          onSave={save}
        />
      )}
    </Layout>
  );
}

function FlowInspector({
  node,
  spec,
}: {
  node?: BusinessFlowNode;
  spec: BusinessFlowSpec;
}) {
  const ui = useComputeText();
  if (!node) return null;
  const roles = spec.inputRequirements.filter((role) =>
    node.dataRoles.includes(role.key),
  );
  return (
    <aside
      className="business-flow-inspector"
      aria-label={ui(
        "节点职责与审核边界",
        "Node responsibilities and review rules",
      )}
    >
      <span className="business-flow-inspector-eyebrow">
        <RobotOutlined />
        {ui("节点详情", "NODE DETAILS")}
      </span>
      <h4>{node.title}</h4>
      <p>{node.description}</p>
      {node.instruction && (
        <section className="business-flow-inspector-section">
          <strong>{ui("处理要求", "Processing requirements")}</strong>
          <p>{node.instruction}</p>
        </section>
      )}
      {roles.length > 0 && (
        <section className="business-flow-inspector-section">
          <strong>{ui("使用资料", "Inputs used")}</strong>
          <Space wrap>
            {roles.map((role) => (
              <Tag key={role.key}>{role.label}</Tag>
            ))}
          </Space>
        </section>
      )}
      {node.inputBindings && Object.keys(node.inputBindings).length > 0 && (
        <section className="business-flow-inspector-section">
          <strong>{ui("算子数据来自哪里", "Operator input sources")}</strong>
          <ul>
            {Object.entries(node.inputBindings).map(([key, value]) => (
              <li key={key}>
                {key} ←{" "}
                {"role" in value
                  ? (spec.inputRequirements.find(
                      (input) => input.key === value.role,
                    )?.label ?? value.role)
                  : `${spec.nodes.find((source) => source.id === value.nodeId)?.title ?? value.nodeId} · ${value.outputKey}`}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="business-flow-inspector-section">
        <strong>
          {ui("通过这个节点的方式", "How this node is completed")}
        </strong>
        {node.review.ai && (
          <div className="business-flow-review-rule">
            <AuditOutlined />
            <div>
              {ui(
                "独立审核智能体检查实际结果与依据。未通过时保留具体原因，自动返修由本节点的上限控制。",
                "An independent agent checks actual results and evidence. Rejections retain specific reasons; automatic revisions follow this node’s limit.",
              )}
              {node.review.maxRevisions > 0 && (
                <span>
                  {" "}
                  {ui(
                    `最多自动返修 ${node.review.maxRevisions} 次。`,
                    `Up to ${node.review.maxRevisions} automatic revisions.`,
                  )}
                </span>
              )}
            </div>
          </div>
        )}
        {(node.review.human || node.kind === "human") && (
          <div className="business-flow-review-rule is-human">
            <UserOutlined />
            <span>
              {ui(
                "此处必须由您作决定。执行与审核智能体都不能代替您的批准。",
                "Your decision is required here. Neither agent can approve on your behalf.",
              )}
            </span>
          </div>
        )}
        {!node.review.ai && !node.review.human && node.kind !== "human" && (
          <div className="business-flow-review-rule">
            <FileDoneOutlined />
            <span>
              {ui(
                "完成本节点要求后自动进入下一步，无需额外确认。",
                "The flow continues automatically when this node's requirements are met.",
              )}
            </span>
          </div>
        )}
      </section>
    </aside>
  );
}
