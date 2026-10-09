import {
  Alert,
  Button,
  Collapse,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import { useEffect, useState } from "react";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type {
  AgentWorkflow,
  ComputeAlgorithm,
  ComputeCandidate,
  ComputeParameterSpec,
} from "../api/generated/types.gen";
import { createUuid } from "../utils/uuid";
import { useComputeText } from "../compute/ui";

const active = ["queued", "running", "waiting_compute", "waiting_approval"];
const labels: Record<string, string> = {
  queued: "等待处理",
  running: "准备计划",
  waiting_compute: "执行与入库",
  waiting_approval: "等待确认",
  succeeded: "已完成",
  failed: "未完成",
  cancelled: "已停止",
  interrupted: "已中断",
};

function ParameterField({
  spec,
  value,
  candidate,
  onChange,
}: {
  spec: ComputeParameterSpec;
  value: unknown;
  candidate?: ComputeCandidate;
  onChange: (value: unknown) => void;
}) {
  if (spec.type === "boolean")
    return <Switch checked={value === true} onChange={onChange} />;
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
}: {
  model: string;
  resourceIds: number[];
  embedded?: boolean;
  onStatusChange?: (status: AgentWorkflow["status"] | undefined) => void;
}) {
  const ui = useComputeText();
  const [goal, setGoal] = useState("");
  const [algorithms, setAlgorithms] = useState<ComputeAlgorithm[]>([]);
  const [candidates, setCandidates] = useState<ComputeCandidate[]>([]);
  const [versionId, setVersionId] = useState<number>();
  const [inputs, setInputs] = useState<Record<string, number>>({});
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const [workflow, setWorkflow] = useState<AgentWorkflow>();
  const [history, setHistory] = useState<AgentWorkflow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const version = algorithms
    .flatMap((algorithm) => algorithm.versions)
    .find((v) => v.id === versionId);
  const report = (e: unknown) =>
    setError(e instanceof Error ? e.message : "请求失败");
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
        setWorkflow(w.items[0]);
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
    setBusy(true);
    setError("");
    try {
      const result = await agentApi.createWorkflow({
        goal,
        model,
        resourceIds: [...new Set([...resourceIds, ...Object.values(inputs)])],
        workflowType: "research_processing",
        algorithmVersionId: versionId,
        inputs,
        parameters,
        executeOperators: false,
        importResults: true,
        idempotencyKey: createUuid(),
      });
      setWorkflow(result);
      setHistory((old) => [result, ...old]);
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  };
  const action = async (confirm: boolean) => {
    if (!workflow) return;
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
      setBusy(false);
    }
  };
  useEffect(() => {
    onStatusChange?.(workflow?.status);
  }, [workflow?.status, onStatusChange]);
  const fields = (value: unknown) =>
    value && typeof value === "object" && !Array.isArray(value)
      ? Object.entries(value)
      : [];
  const content = (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Typography.Text type="secondary">
        {ui(
          "描述目标，核对数据与算法后确认执行。平台持续跟踪计算、知识检查和结果入库，离开页面后仍可恢复查看。",
          "Describe a goal, review the data and algorithm, then confirm. The platform tracks calculation, knowledge checks and import even after you leave.",
        )}
      </Typography.Text>
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
              version.manifest.parameters.find((p) => p.key === spec.when?.key)
                ?.default) === spec.when.equals,
        )
        .map((spec) => (
          <Space key={spec.key} wrap>
            <Typography.Text>{spec.label}</Typography.Text>
            <ParameterField
              spec={spec}
              value={parameters[spec.key] ?? spec.default}
              candidate={
                spec.input
                  ? candidates.find((c) => c.id === inputs[spec.input ?? ""])
                  : undefined
              }
              onChange={(value) =>
                setParameters((old) => ({ ...old, [spec.key]: value }))
              }
            />
          </Space>
        ))}
      <Button
        type="primary"
        loading={busy}
        disabled={
          !goal.trim() ||
          !model ||
          Boolean(workflow && active.includes(workflow.status))
        }
        onClick={() => void preview()}
      >
        {ui("生成执行计划", "Preview plan")}
      </Button>
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
            void agentApi.workflow(id).then(setWorkflow).catch(report);
          }}
        />
      )}
      {workflow && (
        <div className="agent-workflow-status">
          <Space wrap>
            <Tag
              color={
                workflow.status === "succeeded"
                  ? "green"
                  : workflow.status === "failed"
                    ? "red"
                    : "blue"
              }
            >
              {ui(labels[workflow.status] ?? workflow.status)}
            </Tag>
            <span>{workflow.detail}</span>
          </Space>
          {workflow.planHash && (
            <dl className="agent-plan-summary">
              <dt>{ui("算法", "Algorithm")}</dt>
              <dd>{String(workflow.plan.algorithm ?? "")}</dd>
              <dt>{ui("输入数据", "Input data")}</dt>
              <dd>
                {fields(workflow.plan.inputNames).map(([key, value]) => (
                  <div key={key}>{String(value)}</div>
                ))}
              </dd>
              <dt>{ui("执行参数", "Parameters")}</dt>
              <dd>
                {fields(workflow.plan.parameters).map(([key, value]) => (
                  <div key={key}>
                    {key}：{String(value)}
                  </div>
                ))}
              </dd>
              <dt>{ui("知识依据", "Knowledge references")}</dt>
              <dd>
                {workflow.evidence.length
                  ? workflow.evidence.map((entry) => (
                      <div key={String(entry.id)}>
                        {String(entry.title)} · {ui("版本", "Revision")}{" "}
                        {String(entry.revision)}
                      </div>
                    ))
                  : ui(
                      "未匹配到相关知识规则，将保留算法原始结果",
                      "No matching rules; the original calculation will be preserved",
                    )}
              </dd>
            </dl>
          )}
          {workflow.status === "waiting_approval" && (
            <Button
              type="primary"
              loading={busy}
              onClick={() => void action(true)}
            >
              {ui("确认执行并自动入库", "Confirm and import automatically")}
            </Button>
          )}
          {active.includes(workflow.status) && (
            <Button loading={busy} onClick={() => void action(false)}>
              {ui("停止此工作流", "Stop workflow")}
            </Button>
          )}
          {workflow.steps.map((item) => (
            <p key={item.id}>
              {item.sequence}. {item.message}
            </p>
          ))}
          {!!workflow.resultResourceIds.length && (
            <Alert
              type="success"
              title={`${ui("结果已入库，资源编号", "Results imported, resource IDs")}: ${workflow.resultResourceIds.join("、")}`}
            />
          )}
        </div>
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
