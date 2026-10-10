import {
  App,
  Alert,
  Button,
  Form,
  Input,
  Modal,
  Space,
  Typography,
} from "antd";
import { useEffect, useRef, useState } from "react";
import {
  computeApi,
  type ComputeCandidate,
  type ComputeTask,
  type ComputeTaskCreate,
  type ComputeVersion,
} from "../api/compute";
import { createUuid } from "../utils/uuid";
import ComputeAlgorithmFields, {
  resetLinkedComputeParameters,
  type ComputeFieldValues,
} from "./ComputeAlgorithmFields";
import { useComputeText } from "./ui";

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
  const values = Form.useWatch([], form) as ComputeFieldValues | undefined;
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
      styles={{
        body: {
          maxHeight: "min(70vh, 760px)",
          overflowY: "auto",
          overscrollBehavior: "contain",
          paddingRight: 4,
        },
      }}
    >
      <Alert
        type="info"
        showIcon
        title={ui(
          "使用当前项目的数据，计算结果也保存在当前项目。",
          "Use this project's data; results are saved to the same project.",
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
        disabled={busy}
        onValuesChange={(changed) =>
          resetLinkedComputeParameters(form, version.manifest, changed)
        }
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
        <ComputeAlgorithmFields
          manifest={version.manifest}
          candidates={candidates}
          values={values}
          loading={loading}
          searchControls={
            <>
              {version.manifest.inputs.length > 0 && (
                <Form.Item label={ui("查找输入数据", "Find input data")}>
                  <Input.Search
                    aria-label={ui("查找输入数据", "Find input data")}
                    placeholder={ui(
                      "输入数据名称，按 Enter 搜索",
                      "Enter a data name and press Enter",
                    )}
                    onSearch={(text) => {
                      setKeyword(text);
                      setPage(1);
                    }}
                    allowClear
                  />
                </Form.Item>
              )}
              {total > 30 && (
                <Space style={{ marginBottom: 16 }} wrap>
                  <Typography.Text type="secondary">
                    {ui("数据候选页", "Data page")} {page}/
                    {Math.ceil(total / 30)}
                  </Typography.Text>
                  <Button
                    size="small"
                    type="text"
                    disabled={page === 1}
                    onClick={() => setPage(Math.max(1, page - 1))}
                  >
                    {ui("上一页", "Previous")}
                  </Button>
                  <Button
                    size="small"
                    type="text"
                    disabled={page === Math.ceil(total / 30)}
                    onClick={() =>
                      setPage(Math.min(Math.ceil(total / 30), page + 1))
                    }
                  >
                    {ui("下一页", "Next")}
                  </Button>
                </Space>
              )}
            </>
          }
        />
      </Form>
    </Modal>
  );
}
