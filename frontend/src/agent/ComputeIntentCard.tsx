import { PlayCircleOutlined, ExperimentOutlined } from "@ant-design/icons";
import { Alert, Button, Checkbox, Form } from "antd";
import { useEffect, useRef, useState } from "react";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type { AgentComputeIntent, AgentRun } from "../api/generated/types.gen";
import ComputeAlgorithmFields, {
  resetLinkedComputeParameters,
} from "../compute/ComputeAlgorithmFields";
import { useComputeText } from "../compute/ui";

type Values = {
  inputs: Record<string, number>;
  parameters: Record<string, unknown>;
};

export default function ComputeIntentCard({
  runId,
  intent,
  onChanged,
}: {
  runId: number;
  intent: AgentComputeIntent;
  onChanged: (run: AgentRun) => void;
}) {
  const ui = useComputeText();
  const [form] = Form.useForm<Values>();
  const values = Form.useWatch([], form) as Values | undefined;
  const [candidates, setCandidates] = useState(intent.inputCandidates);
  const [keyword, setKeyword] = useState("");
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [autoImport, setAutoImport] = useState(intent.autoImport);
  const alive = useRef(true);
  const actionPending = useRef(false);
  const status = intent.status;
  const editable = ["collecting", "ready", "blocked"].includes(status);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    form.setFieldsValue({
      inputs: intent.inputs,
      parameters: intent.parameters,
    });
    setCandidates(intent.inputCandidates);
    setAutoImport(intent.autoImport);
    setError("");
  }, [intent.planRevision, form]);
  useEffect(() => {
    if (!editable || !keyword.trim()) return;
    let live = true;
    const timer = setTimeout(() => {
      setSearching(true);
      void computeApi
        .inputs({ q: keyword.trim(), pageSize: 30 })
        .then((result) => {
          if (live)
            setCandidates((previous) =>
              Array.from(
                new Map(
                  [...previous, ...result.items].map((item) => [item.id, item]),
                ).values(),
              ),
            );
        })
        .catch((reason) => {
          if (live)
            setError(reason instanceof Error ? reason.message : "查找数据失败");
        })
        .finally(() => {
          if (live) setSearching(false);
        });
    }, 250);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [keyword, editable]);
  const act = async (action: "submit" | "cancel") => {
    if (actionPending.current) return;
    actionPending.current = true;
    try {
      const fields =
        action === "submit"
          ? await form.validateFields()
          : form.getFieldsValue();
      setBusy(true);
      setError("");
      const next = await agentApi.updateComputeIntent(runId, {
        action,
        planRevision: intent.planRevision,
        inputs: fields.inputs ?? {},
        parameters: fields.parameters ?? {},
        autoImport,
      });
      if (alive.current) onChanged(next);
    } catch (reason) {
      if (alive.current && reason instanceof Error) {
        setError(reason.message);
        if ("status" in reason && Number(reason.status) === 409) {
          try {
            const latest = await agentApi.computeIntent(runId);
            if (alive.current) onChanged(latest);
          } catch (refreshError) {
            if (alive.current && refreshError instanceof Error)
              setError(refreshError.message);
          }
        }
      }
    } finally {
      actionPending.current = false;
      if (alive.current) setBusy(false);
    }
  };
  if (status === "submitted") return null;
  if (status === "cancelled" || status === "superseded")
    return (
      <p className="agent-compute-muted">
        {status === "cancelled"
          ? ui("这次计算已取消。", "This computation was cancelled.")
          : ui(
              "计算配置已更新，请使用下方最新配置。",
              "Use the updated configuration below.",
            )}
      </p>
    );
  const algorithm = intent.algorithm;
  return (
    <section
      className="agent-compute-intent"
      aria-label={ui("计算配置", "Compute setup")}
    >
      <div className="agent-compute-intent-heading">
        <span className="agent-compute-symbol">
          <ExperimentOutlined aria-hidden="true" />
        </span>
        <div>
          <strong>
            {algorithm
              ? ui(algorithm.manifest.name)
              : ui("准备计算", "Prepare computation")}
          </strong>
          <span>{intent.message}</span>
        </div>
      </div>
      {error && <Alert title={error} type="error" showIcon />}
      {algorithm && (
        <Form
          name={`compute-intent-${runId}`}
          form={form}
          layout="vertical"
          initialValues={{
            inputs: intent.inputs,
            parameters: intent.parameters,
          }}
          disabled={busy}
          className="agent-compute-form"
          onValuesChange={(changed) =>
            resetLinkedComputeParameters(form, algorithm.manifest, changed)
          }
        >
          <ComputeAlgorithmFields
            manifest={algorithm.manifest}
            candidates={candidates}
            values={
              values ?? { inputs: intent.inputs, parameters: intent.parameters }
            }
            loading={searching}
            onSearch={setKeyword}
          />
          <div className="agent-compute-intent-actions">
            <Button
              type="primary"
              icon={<PlayCircleOutlined aria-hidden="true" />}
              loading={busy}
              onClick={() => void act("submit")}
            >
              {ui("开始计算", "Start computation")}
            </Button>
            <Button
              type="text"
              disabled={busy}
              onClick={() => void act("cancel")}
            >
              {ui("取消", "Cancel")}
            </Button>
            <span>
              <Checkbox
                checked={autoImport}
                onChange={(event) => setAutoImport(event.target.checked)}
              >
                {ui("完成后自动入库", "Import automatically when complete")}
              </Checkbox>
            </span>
          </div>
        </Form>
      )}
      {!algorithm && (
        <Button type="text" loading={busy} onClick={() => void act("cancel")}>
          {ui("取消此次计算", "Cancel this computation")}
        </Button>
      )}
      {intent.warnings.length > 0 && (
        <div className="agent-compute-notes">
          {intent.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      )}
    </section>
  );
}
