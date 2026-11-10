import { CodeOutlined, LoadingOutlined } from "@ant-design/icons";
import { Alert, Button, Input, Modal } from "antd";
import { useEffect, useRef, useState } from "react";
import type {
  BusinessFlowRun,
  BusinessFlowInputScriptDetail,
} from "../api/generated/types.gen";
import { businessFlowsApi } from "../api/businessFlows";
import { ApiError } from "../api/client";
import { requestScope } from "../projects/session";
import { createUuid } from "../utils/uuid";
import { useComputeText } from "../compute/ui";
import "./business-flow-input-preparation.css";

const states: Record<string, string> = {
  needs_script: "待智能体编写",
  generating_script: "正在编写脚本",
  reviewing_script: "独立审核脚本",
  convert: "准备转换",
  waiting_compute: "受限计算中",
  waiting_import: "准备工作副本",
  ready: "已就绪",
  needs_clarification: "需要补充说明",
  failed: "未完成",
};

export default function BusinessFlowInputPreparation({
  flow,
  onChanged,
  onAccessBlocked,
}: {
  flow: BusinessFlowRun;
  onChanged: (flow: BusinessFlowRun) => void;
  onAccessBlocked: () => void;
}) {
  const ui = useComputeText();
  const latest = useRef(flow);
  latest.current = flow;
  const mounted = useRef(true);
  const read = useRef<AbortController | undefined>(undefined);
  const [selected, setSelected] = useState<string>();
  const [script, setScript] = useState<BusinessFlowInputScriptDetail>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string>();
  const key = useRef<{ fingerprint: string; value: string } | undefined>(
    undefined,
  );
  useEffect(() => {
    mounted.current = true;
    setSelected(undefined);
    setScript(undefined);
    setError("");
    setFeedback({});
    return () => {
      mounted.current = false;
      read.current?.abort();
    };
  }, [flow.id]);
  const rows =
    flow.inputPreparation?.items.filter((row) => row.status !== "direct") ?? [];
  if (!rows.length) return null;
  const denied = (value: unknown) => {
    if (value instanceof ApiError && [401, 403, 404].includes(value.status)) {
      setScript(undefined);
      setSelected(undefined);
      onAccessBlocked();
    }
    setError(
      value instanceof Error
        ? value.message
        : ui("资料衔接暂不可用", "Input preparation unavailable"),
    );
  };
  const open = async (role: string) => {
    read.current?.abort();
    const controller = new AbortController();
    read.current = controller;
    const scope = requestScope();
    const id = flow.id;
    setSelected(role);
    setScript(undefined);
    setLoading(true);
    setError("");
    try {
      const value = await businessFlowsApi.inputScript(id, role, {
        signal: controller.signal,
      });
      scope();
      if (
        !controller.signal.aborted &&
        mounted.current &&
        latest.current.id === id
      )
        setScript(value);
    } catch (value) {
      if (!controller.signal.aborted && mounted.current) denied(value);
    } finally {
      if (!controller.signal.aborted && mounted.current) setLoading(false);
    }
  };
  const clarify = async (role: string) => {
    if (busy || !feedback[role]?.trim()) return;
    const current = latest.current,
      scope = requestScope();
    const fingerprint = JSON.stringify([
      current.id,
      current.revision,
      role,
      feedback[role],
    ]);
    if (key.current?.fingerprint !== fingerprint)
      key.current = { fingerprint, value: createUuid() };
    setBusy(role);
    setError("");
    try {
      const next = await businessFlowsApi.clarifyInput(current.id, {
        role,
        feedback: feedback[role]!.trim(),
        revision: current.revision,
        idempotencyKey: key.current!.value,
      });
      scope();
      if (
        mounted.current &&
        latest.current.id === current.id &&
        next.revision >= latest.current.revision
      )
        onChanged(next);
    } catch (value) {
      if (mounted.current) denied(value);
    } finally {
      if (mounted.current) setBusy(undefined);
    }
  };
  return (
    <>
      <details
        className="flow-data-preparation"
        open={!flow.inputPreparation?.ready}
      >
        <summary>
          {ui("资料衔接", "Input preparation")}{" "}
          <span>
            {flow.inputPreparation?.ready
              ? ui("已完成", "Ready")
              : ui("由智能体处理", "Agent processing")}
          </span>
        </summary>
        {error && <Alert type="warning" title={error} />}
        {rows.map((row) => (
          <div className="flow-data-preparation-row" key={row.role}>
            <div className="flow-data-preparation-title">
              <strong>{row.sourceName}</strong>
              <small>{states[row.status] ?? row.status}</small>
            </div>
            {row.script?.summary && <p>{row.script.summary}</p>}
            {row.script?.lastError && (
              <details className="flow-preparation-diagnostic">
                <summary>{ui("查看本次诊断", "View diagnostics")}</summary>
                <p>{row.script.lastError}</p>
              </details>
            )}
            {row.script?.available && (
              <Button
                size="small"
                type="text"
                aria-label={ui("查看适配脚本", "View preparation script")}
                icon={<CodeOutlined aria-hidden="true" />}
                onClick={() => void open(row.role)}
              >
                {ui("查看适配脚本", "View preparation script")}
              </Button>
            )}
            {row.status === "needs_clarification" && (
              <div className="flow-preparation-question">
                <strong>{row.script?.question}</strong>
                <Input.TextArea
                  aria-label={ui("补充资料说明", "Clarify source meaning")}
                  value={feedback[row.role] ?? ""}
                  maxLength={4000}
                  autoSize={{ minRows: 2, maxRows: 5 }}
                  disabled={Boolean(busy)}
                  onChange={(event) =>
                    setFeedback((value) => ({
                      ...value,
                      [row.role]: event.target.value,
                    }))
                  }
                />
                <Button
                  type="primary"
                  loading={busy === row.role}
                  disabled={
                    !feedback[row.role]?.trim() ||
                    Boolean(busy) ||
                    flow.status === "paused"
                  }
                  onClick={() => void clarify(row.role)}
                >
                  {ui("提交说明并继续", "Submit clarification")}
                </Button>
              </div>
            )}
          </div>
        ))}
      </details>
      <Modal
        title={ui("本次资料适配脚本", "Input preparation script")}
        open={Boolean(selected)}
        onCancel={() => {
          read.current?.abort();
          setSelected(undefined);
          setScript(undefined);
        }}
        footer={null}
        width={860}
        destroyOnHidden
      >
        {loading && (
          <p>
            <LoadingOutlined />{" "}
            {ui("正在读取实际脚本…", "Loading the actual script…")}
          </p>
        )}
        {script && (
          <>
            <p>{script.summary}</p>
            <small>
              {ui(
                `第${script.attempt}次脚本 · ${script.sha256.slice(0, 12)}`,
                `Attempt ${script.attempt} · ${script.sha256.slice(0, 12)}`,
              )}
            </small>
            <pre className="flow-preparation-code">{script.code}</pre>
            {script.diagnostics.map((message, index) => (
              <Alert key={index} type="info" title={message} />
            ))}
          </>
        )}
        {!loading && error && <Alert type="warning" title={error} />}
      </Modal>
    </>
  );
}
