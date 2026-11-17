import {
  Alert,
  App,
  Button,
  Card,
  Collapse,
  Drawer,
  Empty,
  Select,
  Space,
  Spin,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { AuditOutlined, ReloadOutlined } from "@ant-design/icons";
import { useEffect, useRef, useState } from "react";
import { agentOperationsApi } from "../api/agentOperations";
import type {
  AgentCapabilityCatalog,
  AgentOperation,
  AgentToolCallList,
} from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";

export default function PlatformOperationsPanel({
  projectId,
  accountId,
  runIds,
  inline = false,
}: {
  projectId: number;
  accountId: number;
  runIds: number[];
  inline?: boolean;
}) {
  const ui = useComputeText();
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("operations");
  const [selectedRun, setSelectedRun] = useState<number>();
  const [operations, setOperations] = useState<AgentOperation[]>([]);
  const [capabilities, setCapabilities] = useState<AgentCapabilityCatalog>();
  const [calls, setCalls] = useState<AgentToolCallList>();
  const [loading, setLoading] = useState(false);
  const [deciding, setDeciding] = useState<string>();
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [now, setNow] = useState(Date.now());
  const sequence = useRef(0);
  const write = useRef<AbortController | null>(null);
  const runId =
    selectedRun && runIds.includes(selectedRun)
      ? selectedRun
      : runIds[runIds.length - 1];
  const scope = `${accountId}:${projectId}:${runIds.join(",")}`;

  useEffect(() => {
    setOpen(false);
    setOperations([]);
    setCalls(undefined);
    setCapabilities(undefined);
    setSelectedRun(undefined);
    setError("");
    setDeciding(undefined);
    sequence.current += 1;
    write.current?.abort();
    return () => {
      sequence.current += 1;
      write.current?.abort();
    };
  }, [scope]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const current = ++sequence.current;
    setError("");
    setLoading(true);
    setNow(Date.now());
    const load = async () => {
      if (tab === "capabilities") {
        const result = await agentOperationsApi.capabilities(
          projectId,
          controller.signal,
        );
        if (sequence.current === current) setCapabilities(result);
      } else if (runId) {
        if (tab === "calls") {
          const result = await agentOperationsApi.calls(
            runId,
            projectId,
            0,
            controller.signal,
          );
          if (sequence.current === current) setCalls(result);
        } else {
          const result = await agentOperationsApi.list(
            runId,
            projectId,
            controller.signal,
          );
          if (sequence.current === current) setOperations(result.items);
        }
      }
    };
    void load()
      .catch((e) => {
        if (sequence.current === current && !controller.signal.aborted) {
          setOperations([]);
          setCalls(undefined);
          setCapabilities(undefined);
          setError(
            e instanceof Error
              ? e.message
              : ui("读取失败，请重试", "Could not load. Try again."),
          );
        }
      })
      .finally(() => {
        if (sequence.current === current) setLoading(false);
      });
    return () => {
      controller.abort();
      sequence.current += 1;
    };
  }, [open, tab, runId, projectId, refresh, scope]);

  useEffect(() => {
    if (!open) return;
    const timer = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(timer);
  }, [open]);

  const decide = async (
    operation: AgentOperation,
    decision: "confirm" | "reject",
  ) => {
    if (deciding || operation.projectId !== projectId) return;
    const controller = new AbortController();
    write.current = controller;
    const current = sequence.current;
    setDeciding(operation.id);
    setError("");
    try {
      const result = await agentOperationsApi.decide(
        operation,
        decision,
        projectId,
        controller.signal,
      );
      if (sequence.current !== current || controller.signal.aborted) return;
      setOperations((items) =>
        items.map((item) => (item.id === result.id ? result : item)),
      );
      if (result.status === "confirmed")
        void message.success(
          ui("已完成您确认的操作", "Your confirmed operation is complete"),
        );
      else if (result.status === "rejected")
        void message.info(
          ui("已拒绝，未执行操作", "Rejected. No operation was performed."),
        );
    } catch (e) {
      if (sequence.current === current && !controller.signal.aborted) {
        setError(
          e instanceof Error
            ? e.message
            : ui(
                "操作未完成，请刷新核对真实状态",
                "Refresh to verify the actual state",
              ),
        );
        setOperations((items) =>
          items.map((item) =>
            item.id === operation.id ? { ...item, canConfirm: false } : item,
          ),
        );
      }
    } finally {
      if (sequence.current === current) setDeciding(undefined);
    }
  };

  const moreCalls = async () => {
    if (!runId || !calls || calls.nextOffset === null || loading) return;
    const current = sequence.current;
    setLoading(true);
    try {
      const result = await agentOperationsApi.calls(
        runId,
        projectId,
        calls.nextOffset,
      );
      if (sequence.current === current)
        setCalls((previous) => ({
          ...result,
          items: [...(previous?.items ?? []), ...result.items],
        }));
    } catch (e) {
      if (sequence.current === current)
        setError(
          e instanceof Error ? e.message : ui("读取失败", "Could not load"),
        );
    } finally {
      if (sequence.current === current) setLoading(false);
    }
  };

  const stateLabel = (status: string, kind?: AgentOperation["kind"]) =>
    ({
      pending: ui("待您确认", "Awaiting your decision"),
      executing: ui("执行中", "Executing"),
      confirmed:
        kind === "share"
          ? ui("邀请已发出", "Invitation sent")
          : kind === "import"
            ? ui("已导入", "Imported")
            : ui("已发布", "Published"),
      rejected: ui("已拒绝", "Rejected"),
      expired: ui("已过期", "Expired"),
      failed: ui("未完成", "Failed"),
      interrupted: ui("结果待核对", "Needs verification"),
    })[status] ?? status;

  const operationContent = !runId ? (
    <Empty
      description={ui(
        "发起任务后可查看本轮操作",
        "Start a task to view its operations",
      )}
    />
  ) : operations.length ? (
    <Space orientation="vertical" style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title={ui(
          "确认前请核对对象与范围。科研人工批准仍在原流程单独完成。",
          "Review the target and scope. Scientific approvals remain separate.",
        )}
      />
      {operations.map((operation) => {
        const expired = Date.parse(operation.expiresAt) <= now;
        const canConfirm =
          operation.canConfirm && !expired && operation.status === "pending";
        const query = new URLSearchParams({ projectTagId: String(projectId) });
        const identity = Number(operation.result.objectId);
        const actualLink =
          operation.status !== "confirmed"
            ? null
            : operation.kind === "import" &&
                Number.isSafeInteger(operation.result.resourceId)
              ? `/resources/catalog?${query}`
              : operation.kind === "publish" &&
                  operation.result.kind === "result"
                ? `/results?${query}`
                : Number.isSafeInteger(identity) &&
                    identity > 0 &&
                    operation.result.kind === "composition"
                  ? `/map?${query}&compositionId=${identity}`
                  : Number.isSafeInteger(identity) &&
                      identity > 0 &&
                      operation.result.kind === "workspace"
                    ? `/map?${query}&sceneId=${identity}`
                    : null;
        return (
          <Card
            key={operation.id}
            size="small"
            title={operation.preview.title}
            extra={
              <Tag>
                {operation.status === "pending" &&
                !expired &&
                !operation.canConfirm
                  ? ui("当前不可执行", "Currently unavailable")
                  : stateLabel(
                      expired && operation.status === "pending"
                        ? "expired"
                        : operation.status,
                      operation.kind,
                    )}
              </Tag>
            }
          >
            <Typography.Paragraph>
              <strong>{ui("对象：", "Target: ")}</strong>
              {operation.preview.target}
            </Typography.Paragraph>
            <Typography.Paragraph>
              <strong>{ui("范围：", "Scope: ")}</strong>
              {operation.preview.scope}
            </Typography.Paragraph>
            <Typography.Paragraph>
              {operation.preview.effect}
            </Typography.Paragraph>
            {operation.preview.details.map((detail) => (
              <Typography.Paragraph key={detail} type="secondary">
                {detail}
              </Typography.Paragraph>
            ))}
            <Typography.Paragraph type="secondary">
              {ui("确认期限：", "Confirm before: ")}
              {new Date(operation.expiresAt).toLocaleString()}
            </Typography.Paragraph>
            {operation.detail && <Alert type="info" title={operation.detail} />}
            {operation.status === "confirmed" && (
              <Typography.Paragraph>
                {ui("真实结果编号：", "Result references: ")}
                {Object.entries(operation.result)
                  .filter(([key]) => key.endsWith("Id"))
                  .map(([key, value]) => `${key}: ${value}`)
                  .join("，")}
              </Typography.Paragraph>
            )}
            {actualLink && (
              <Button href={actualLink} target="_blank" rel="noopener">
                {ui("查看实际对象", "View the actual object")}
              </Button>
            )}
            {canConfirm && (
              <Space wrap style={{ marginTop: 12 }}>
                <Button
                  type="primary"
                  disabled={!!deciding}
                  loading={deciding === operation.id}
                  onClick={() => void decide(operation, "confirm")}
                >
                  {ui("确认执行此操作", "Confirm this operation")}
                </Button>
                <Button
                  disabled={!!deciding}
                  onClick={() => void decide(operation, "reject")}
                >
                  {ui("拒绝", "Reject")}
                </Button>
              </Space>
            )}
          </Card>
        );
      })}
    </Space>
  ) : (
    <Empty
      description={ui("本轮没有待确认操作", "No operations in this run")}
    />
  );

  return (
    <>
      <Button
        size={inline ? "small" : "middle"}
        type="text"
        icon={<AuditOutlined />}
        onClick={() => setOpen(true)}
      >
        {inline
          ? ui("查看待确认操作", "Review pending operations")
          : ui("平台操作", "Platform operations")}
      </Button>
      <Drawer
        open={open}
        onClose={() => {
          sequence.current += 1;
          write.current?.abort();
          setDeciding(undefined);
          setOpen(false);
        }}
        title={ui("平台操作", "Platform operations")}
        size="large"
        destroyOnHidden
      >
        <Space wrap style={{ marginBottom: 16 }}>
          {runIds.length > 0 && (
            <Select
              aria-label={ui("操作所属任务", "Operation run")}
              value={runId}
              disabled={!!deciding}
              onChange={(value) => {
                setSelectedRun(value);
                setOperations([]);
                setCalls(undefined);
              }}
              options={runIds.map((id) => ({
                value: id,
                label: ui(
                  `第 ${runIds.indexOf(id) + 1} 轮对话`,
                  `Conversation turn ${runIds.indexOf(id) + 1}`,
                ),
              }))}
            />
          )}
          <Button
            icon={<ReloadOutlined />}
            disabled={loading || !!deciding}
            onClick={() => setRefresh((value) => value + 1)}
          >
            {ui("刷新", "Refresh")}
          </Button>
        </Space>
        {error && (
          <Alert type="error" title={error} style={{ marginBottom: 16 }} />
        )}
        <Spin spinning={loading}>
          <Tabs
            activeKey={tab}
            onChange={(value) => {
              if (deciding) return;
              setTab(value);
              setError("");
            }}
            items={[
              {
                key: "operations",
                label: ui("待确认操作", "Operations"),
                children: operationContent,
              },
              {
                key: "calls",
                label: ui("调用回执", "Tool receipts"),
                children: (
                  <Space orientation="vertical" style={{ width: "100%" }}>
                    {!calls?.items.length && (
                      <Empty
                        description={ui("暂无工具调用回执", "No tool receipts")}
                      />
                    )}
                    {calls?.items.map((call) => (
                      <Card
                        key={call.id}
                        size="small"
                        title={call.tool}
                        extra={
                          <Tag
                            color={
                              call.status === "failed"
                                ? "error"
                                : call.status === "succeeded"
                                  ? "success"
                                  : "processing"
                            }
                          >
                            {call.status === "succeeded"
                              ? ui("调用成功", "Call succeeded")
                              : call.status === "failed"
                                ? ui("调用失败", "Call failed")
                                : ui("调用中", "Running")}
                          </Tag>
                        }
                      >
                        <Typography.Paragraph type="secondary">
                          {new Date(call.createdAt).toLocaleString()}
                        </Typography.Paragraph>
                        <Typography.Paragraph>
                          {ui(
                            "调用成功以业务实际状态为准，受理不表示任务已完成。",
                            "Use the actual business state to verify completion.",
                          )}
                        </Typography.Paragraph>
                        <pre
                          style={{
                            whiteSpace: "pre-wrap",
                            overflowWrap: "anywhere",
                          }}
                        >
                          {JSON.stringify(
                            Object.keys(call.error).length
                              ? call.error
                              : call.resultRefs,
                            null,
                            2,
                          )}
                        </pre>
                      </Card>
                    ))}
                    {calls?.nextOffset !== null &&
                      calls?.nextOffset !== undefined && (
                        <Button
                          onClick={() => void moreCalls()}
                          disabled={loading}
                        >
                          {ui("加载更多回执", "Load more receipts")}
                        </Button>
                      )}
                  </Space>
                ),
              },
              {
                key: "capabilities",
                label: ui("可用能力", "Capabilities"),
                children: (
                  <Space orientation="vertical" style={{ width: "100%" }}>
                    <Typography.Paragraph>
                      {ui(
                        "当前账号与项目可发现的能力。实际执行还会核对资料权限、版本和必要的用户决定。",
                        "Capabilities for this account and project. Execution rechecks access, revisions and required user decisions.",
                      )}
                    </Typography.Paragraph>
                    {capabilities?.items.map((item) => (
                      <Card key={item.name} size="small" title={item.name}>
                        <Typography.Paragraph>
                          {item.description}
                        </Typography.Paragraph>
                        <Typography.Paragraph type="secondary">
                          {item.completion}
                        </Typography.Paragraph>
                        <Collapse
                          items={[
                            {
                              key: item.name,
                              label: ui("查看接口规范", "View API contract"),
                              children: (
                                <>
                                  <Typography.Paragraph>
                                    {item.limitations}
                                  </Typography.Paragraph>
                                  <Typography.Paragraph>
                                    {item.idempotency}
                                  </Typography.Paragraph>
                                  <Typography.Paragraph>
                                    {item.retry}
                                  </Typography.Paragraph>
                                  <pre
                                    style={{
                                      whiteSpace: "pre-wrap",
                                      overflowWrap: "anywhere",
                                    }}
                                  >
                                    {JSON.stringify(item.inputSchema, null, 2)}
                                  </pre>
                                </>
                              ),
                            },
                          ]}
                        />
                      </Card>
                    ))}
                  </Space>
                ),
              },
            ]}
          />
        </Spin>
      </Drawer>
    </>
  );
}
