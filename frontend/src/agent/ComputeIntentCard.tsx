import { PlayCircleOutlined, ExperimentOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type {
  AgentComputeIntent,
  AgentRun,
  ComputeCandidate,
  ComputeParameterSpec,
} from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";

type Values = {
  inputs: Record<string, number>;
  parameters: Record<string, unknown>;
};

function ParameterInput({
  parameter,
  candidate,
  value,
  checked,
  onChange,
  id,
}: {
  parameter: ComputeParameterSpec;
  candidate?: ComputeCandidate;
  value?: unknown;
  checked?: boolean;
  onChange?: (value: unknown) => void;
  id?: string;
}) {
  const ui = useComputeText();
  if (parameter.type === "boolean")
    return <Switch id={id} checked={checked} onChange={onChange} />;
  if (["band", "field", "enum"].includes(parameter.type)) {
    const options: { value: string | number; label: string }[] =
      parameter.type === "band"
        ? Array.from({ length: candidate?.bands ?? 0 }, (_, index) => ({
            value: index + 1,
            label: ui(`第 ${index + 1} 波段`, `Band ${index + 1}`),
          }))
        : (parameter.type === "field"
            ? (candidate?.fields ?? [])
            : (parameter.choices ?? [])
          ).map((entry) => ({ value: entry, label: ui(entry) }));
    return (
      <Select
        id={id}
        value={value as string | number | undefined}
        onChange={onChange}
        options={options}
        disabled={parameter.type !== "enum" && !candidate}
        placeholder={ui("请选择", "Select")}
        aria-label={ui(parameter.label)}
      />
    );
  }
  if (parameter.type === "integer" || parameter.type === "number")
    return (
      <InputNumber
        id={id}
        value={typeof value === "number" ? value : null}
        onChange={onChange}
        min={parameter.min}
        max={parameter.max}
        precision={parameter.type === "integer" ? 0 : undefined}
      />
    );
  return (
    <Input
      id={id}
      value={typeof value === "string" ? value : ""}
      maxLength={2000}
      onChange={(event) => onChange?.(event.target.value)}
    />
  );
}

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
  const selected = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(values?.inputs ?? intent.inputs).map(([key, id]) => [
          key,
          candidates.find((candidate) => candidate.id === id),
        ]),
      ),
    [values?.inputs, intent.inputs, candidates],
  );
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
          disabled={busy}
          className="agent-compute-form"
          onValuesChange={(changed) => {
            for (const inputKey of Object.keys(changed.inputs ?? {})) {
              for (const parameter of algorithm.manifest.parameters)
                if (
                  parameter.input === inputKey &&
                  ["band", "field"].includes(parameter.type)
                )
                  form.setFieldValue(["parameters", parameter.key], undefined);
            }
          }}
        >
          {algorithm.manifest.inputs.map((input) => (
            <Form.Item
              key={input.key}
              name={["inputs", input.key]}
              label={ui(input.label)}
              rules={[
                {
                  required: input.required,
                  message: ui("请选择输入数据", "Select input data"),
                },
              ]}
            >
              <Select
                showSearch
                onSearch={setKeyword}
                loading={searching}
                optionFilterProp="label"
                placeholder={ui("选择要处理的数据", "Choose data to process")}
                aria-label={ui(input.label)}
                options={candidates
                  .filter((candidate) => candidate.kind === input.kind)
                  .map((candidate) => ({
                    value: candidate.id,
                    label: `${candidate.name}${candidate.bands ? ui(` · ${candidate.bands} 波段`, ` · ${candidate.bands} bands`) : ""}`,
                    disabled:
                      input.minBands !== undefined &&
                      candidate.bands < input.minBands,
                  }))}
              />
            </Form.Item>
          ))}
          <div className="agent-compute-parameters">
            {algorithm.manifest.parameters.map((parameter) => {
              if (
                parameter.when &&
                values?.parameters?.[String(parameter.when.key)] !==
                  parameter.when.equals
              )
                return null;
              return (
                <Form.Item
                  key={parameter.key}
                  name={["parameters", parameter.key]}
                  label={ui(parameter.label)}
                  valuePropName={
                    parameter.type === "boolean" ? "checked" : "value"
                  }
                  preserve={false}
                  rules={[
                    {
                      required: parameter.required,
                      message: ui("请补充此参数", "Complete this parameter"),
                    },
                  ]}
                >
                  <ParameterInput
                    parameter={parameter}
                    candidate={
                      parameter.input ? selected[parameter.input] : undefined
                    }
                  />
                </Form.Item>
              );
            })}
          </div>
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
