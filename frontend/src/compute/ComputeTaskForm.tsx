import {
  App,
  Alert,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Typography,
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  computeApi,
  type ComputeCandidate,
  type ComputeParameterSpec,
  type ComputeTask,
  type ComputeTaskCreate,
  type ComputeVersion,
} from "../api/compute";
import { createUuid } from "../utils/uuid";
import { useComputeText } from "./ui";

function ParameterControl({
  parameter,
  inputs,
  id,
  value,
  checked,
  onChange,
}: {
  parameter: ComputeParameterSpec;
  inputs: Record<string, ComputeCandidate | undefined>;
  id?: string;
  value?: unknown;
  checked?: boolean;
  onChange?: (value: unknown) => void;
}) {
  const ui = useComputeText();
  const data = parameter.input ? inputs[parameter.input] : undefined;
  if (parameter.type === "boolean")
    return <Switch id={id} checked={checked} onChange={onChange} />;
  if (
    parameter.type === "enum" ||
    parameter.type === "field" ||
    parameter.type === "band"
  ) {
    const values =
      parameter.type === "enum"
        ? (parameter.choices ?? [])
        : parameter.type === "field"
          ? (data?.fields ?? [])
          : Array.from({ length: data?.bands ?? 0 }, (_, index) => index + 1);
    return (
      <Select
        id={id}
        value={value as string | number | undefined}
        onChange={onChange}
        showSearch
        options={values.map((value) => ({ value, label: parameter.type === "enum" ? ui(String(value)) : String(value) }))}
        style={{ minWidth: 180 }}
      />
    );
  }
  if (parameter.type === "number" || parameter.type === "integer")
    return (
      <InputNumber
        id={id}
        value={typeof value === "number" ? value : null}
        onChange={onChange}
        min={parameter.min}
        max={parameter.max}
        precision={parameter.type === "integer" ? 0 : undefined}
        style={{ width: "100%" }}
      />
    );
  return (
    <Input
      id={id}
      value={typeof value === "string" ? value : ""}
      onChange={(event) => onChange?.(event.target.value)}
      maxLength={2000}
    />
  );
}

export default function ComputeTaskForm({
  version,
  trial = false,
  initial,
  resourceId,
  onClose,
  onSubmitted,
}: {
  version: ComputeVersion;
  trial?: boolean;
  initial?: ComputeTask;
  resourceId?: number;
  onClose: () => void;
  onSubmitted: (task: ComputeTask) => void;
}) {
  const ui = useComputeText();
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [candidates, setCandidates] = useState<ComputeCandidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const key = useRef(createUuid());
  const submitting = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (!resourceId || initial) return;
    let live = true;
    computeApi
      .inputs({ resourceId })
      .then((data) => {
        const resource = data.items[0];
        if (!live || !resource) return;
        const input = version.manifest.inputs.find(
          (i) => i.kind === resource.kind,
        );
        if (input) {
          setCandidates((old) =>
            Array.from(
              new Map([...old, resource].map((c) => [c.id, c])).values(),
            ),
          );
          form.setFieldValue(["inputs", input.key], resource.id);
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [resourceId, initial, version, form]);
  const values = Form.useWatch([], form) as
    | { inputs?: Record<string, number>; parameters?: Record<string, unknown> }
    | undefined;
  const selected = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(values?.inputs ?? {}).map(([name, id]) => [
          name,
          candidates.find((c) => c.id === id),
        ]),
      ),
    [values?.inputs, candidates],
  );
  useEffect(() => {
    let mounted = true;
    setLoading(true);
    computeApi
      .inputs({ q: keyword, page, pageSize: 30 })
      .then((data) => {
        if (mounted) {
          setCandidates((old) => {
            const retained = old.filter((c) =>
              Object.values(form.getFieldValue("inputs") ?? {}).includes(c.id),
            );
            return Array.from(
              new Map(
                [...retained, ...data.items].map((c) => [c.id, c]),
              ).values(),
            );
          });
          setTotal(data.total);
        }
      })
      .catch((e) => {
        if (mounted) setError(e.message);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [keyword, page, form]);
  const submit = async () => {
    if (submitting.current) return;
    submitting.current = true;
    try {
      const fields = await form.validateFields();
      setBusy(true);
      setError("");
      const body: ComputeTaskCreate = {
        ...fields,
        versionId: version.id,
        trial,
        parameters: fields.parameters ?? {},
        inputs: fields.inputs ?? {},
        idempotencyKey: key.current,
      };
      const checked = await computeApi.preflight(body);
      const task = await computeApi.submit({
        ...body,
        parameters: checked.parameters,
      });
      if (alive.current) {
        message.success(
          ui(
            "任务已提交，可关闭页面等待计算",
            "Task submitted; it keeps running after you leave",
          ),
        );
        onSubmitted(task);
      }
    } catch (e) {
      if (alive.current && e instanceof Error) setError(e.message);
    } finally {
      submitting.current = false;
      if (alive.current) setBusy(false);
    }
  };
  return (
    <Modal
      open
      width={720}
      title={`${trial ? ui("算法试运行", "Trial run") : ui("新建计算任务", "New compute task")} · ${ui(version.manifest.name)} ${version.version}`}
      onCancel={onClose}
      onOk={submit}
      confirmLoading={busy}
      okText={ui("检查并提交", "Validate and submit")}
      cancelText={ui("取消", "Cancel")}
      destroyOnHidden
    >
      <Alert
        type="info"
        showIcon
        title={ui(
          "只使用当前项目内有权访问的数据，无需先加载到地图。结果仍属于当前项目。",
          "Use authorized data in the current project. Map loading is not required; results stay in this project.",
        )}
        style={{ marginBottom: 20 }}
      />
      {error && (
        <Alert
          type="error"
          showIcon
          title={error}
          style={{ marginBottom: 16 }}
        />
      )}
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          name: initial?.name ?? ui(version.manifest.name),
          inputs: initial
            ? Object.fromEntries(
                initial.inputs.map((r) => [String(r.key), r.resourceId]),
              )
            : {},
          parameters:
            initial?.parameters ??
            Object.fromEntries(
              version.manifest.parameters
                .filter((p) => p.default !== undefined)
                .map((p) => [p.key, p.default]),
            ),
        }}
      >
        <Form.Item
          name="name"
          label={ui("任务名称", "Task name")}
          rules={[{ required: true }]}
        >
          <Input maxLength={160} />
        </Form.Item>
        <Input.Search
          placeholder={ui("搜索当前项目数据", "Search current project data")}
          onSearch={(text) => {
            setKeyword(text);
            setPage(1);
          }}
          allowClear
          style={{ marginBottom: 16 }}
        />
        {version.manifest.inputs.map((input) => (
          <Form.Item
            key={input.key}
            name={["inputs", input.key]}
            label={`${ui(input.label)} · ${input.kind}`}
            rules={[{ required: input.required }]}
          >
            <Select
              showSearch
              loading={loading}
              optionFilterProp="label"
              placeholder={ui("选择输入数据", "Select input data")}
              options={candidates
                .filter((c) => c.kind === input.kind)
                .map((c) => ({
                  value: c.id,
                  label: c.name,
                  disabled:
                    input.minBands !== undefined && c.bands < input.minBands,
                }))}
            />
          </Form.Item>
        ))}
        {total > 30 && (
          <Space style={{ marginBottom: 16 }}>
            <Typography.Text>
              {ui("数据候选页", "Data page")} {page}/{Math.ceil(total / 30)}
            </Typography.Text>
            <a onClick={() => setPage(Math.max(1, page - 1))}>
              {ui("上一页", "Previous")}
            </a>
            <a
              onClick={() => setPage(Math.min(Math.ceil(total / 30), page + 1))}
            >
              {ui("下一页", "Next")}
            </a>
          </Space>
        )}
        {version.manifest.parameters.map((parameter) => {
          const when = parameter.when;
          if (when && values?.parameters?.[String(when.key)] !== when.equals)
            return null;
          return (
            <Form.Item
              key={parameter.key}
              name={["parameters", parameter.key]}
              label={ui(parameter.label)}
              help={parameter.help ? ui(parameter.help) : undefined}
              rules={[{ required: parameter.required }]}
              valuePropName={parameter.type === "boolean" ? "checked" : "value"}
              preserve={false}
            >
              <ParameterControl parameter={parameter} inputs={selected} />
            </Form.Item>
          );
        })}
      </Form>
      <Typography.Paragraph type="secondary">
        {ui("输出：", "Outputs: ")}
        {version.manifest.outputs
          .map((o) => `${ui(o.label)} (${o.kind})`)
          .join("、")}
      </Typography.Paragraph>
    </Modal>
  );
}
