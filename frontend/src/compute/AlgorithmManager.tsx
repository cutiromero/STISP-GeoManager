import {
  App,
  Alert,
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { DeleteOutlined } from "@ant-design/icons";
import { useEffect, useRef, useState } from "react";
import {
  computeApi,
  downloadComputeFile,
  type ComputeAlgorithm,
  type ComputeAlgorithmWrite,
  type ComputeRuntimeStatus,
  type ComputeVersion,
} from "../api/compute";
import { useComputeText } from "./ui";

export default function AlgorithmManager({
  runtime,
  onTrial,
  refreshKey = 0,
}: {
  runtime: ComputeRuntimeStatus | null;
  onTrial: (version: ComputeVersion) => void;
  refreshKey?: number;
}) {
  const ui = useComputeText();
  const { message, modal } = App.useApp();
  const [items, setItems] = useState<ComputeAlgorithm[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [keyword, setKeyword] = useState("");
  const [detail, setDetail] = useState<ComputeAlgorithm | null>(null);
  const [editing, setEditing] = useState<ComputeAlgorithm | null | undefined>(
    undefined,
  );
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm<ComputeAlgorithmWrite>();
  const [categories, setCategories] = useState<string[]>([]);
  const [category, setCategory] = useState("");
  const [categoryOpen, setCategoryOpen] = useState(false);
  const alive = useRef(true);
  const packageInput = useRef<HTMLInputElement>(null);
  const runtimeAvailable = runtime?.available ?? false;
  const runtimeDetail =
    runtime?.detail ?? ui("正在检查计算执行环境", "Checking compute runtime");
  const runtimePermissions = runtime?.permissions ?? {};
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    let live = true;
    computeApi
      .algorithms({ manage: 1, page, q: keyword })
      .then((data) => {
        if (live) {
          setItems(data.items);
          setTotal(data.total);
          setDetail((old) =>
            old ? (data.items.find((a) => a.id === old.id) ?? old) : null,
          );
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    computeApi
      .categories()
      .then((data) => {
        if (live) setCategories([...new Set(data.items.map((c) => c.name))]);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [page, keyword, revision, refreshKey]);
  const perform = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      if (alive.current) {
        setRevision((v) => v + 1);
        message.success(ui("操作完成", "Saved"));
      }
    } catch (e) {
      if (alive.current && e instanceof Error) setError(e.message);
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  const edit = (value: ComputeAlgorithm | null) => {
    setEditing(value);
    form.resetFields();
    form.setFieldsValue(value ?? { enabled: true });
  };
  const remove = (algorithm: ComputeAlgorithm) => {
    modal.confirm({
      title: ui("删除算法登记", "Delete algorithm registration"),
      content: ui(
        `确认删除“${ui(algorithm.name)}”？没有任务记录的版本和算法包会一并删除。已有任务记录的算法需要归档停用。`,
        `Delete “${ui(algorithm.name)}”? Versions and packages without task history will be removed. Algorithms with task history must be archived instead.`,
      ),
      okText: ui("删除", "Delete"),
      okButtonProps: { danger: true },
      cancelText: ui("取消", "Cancel"),
      onOk: () =>
        perform(async () => {
          await computeApi.deleteAlgorithm(algorithm.id);
          if (alive.current && detail?.id === algorithm.id) setDetail(null);
        }),
    });
  };
  if (!runtimePermissions.manage_algorithms)
    return (
      <Empty
        description={ui(
          "没有算法维护权限",
          "Algorithm management permission is required",
        )}
      />
    );
  return (
    <Space orientation="vertical" size={20} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title={ui(
          "登记 → 上传版本 → 试运行并核对结果 → 发布",
          "Register → Upload a version → Trial and review → Publish",
        )}
        description={ui(
          "算法归属当前项目。“公开”项目的已发布算法可在其他项目调用，输入和结果保留在任务所属项目。",
          "Algorithms belong to the current project. Published public algorithms can be used elsewhere; inputs and results stay in the task project.",
        )}
      />
      {error && (
        <Alert
          type="error"
          title={error}
          closable
          onClose={() => setError("")}
        />
      )}
      <Space wrap>
        <Button type="primary" onClick={() => edit(null)}>
          {ui("登记算法", "Register algorithm")}
        </Button>
        <Button onClick={() => setCategoryOpen(true)}>
          {ui("新增分类", "New category")}
        </Button>
        <Input.Search
          placeholder={ui("搜索算法", "Search algorithms")}
          allowClear
          onSearch={(value) => {
            setKeyword(value);
            setPage(1);
          }}
        />
        <Button onClick={() => setRevision((r) => r + 1)}>
          {ui("刷新", "Refresh")}
        </Button>
      </Space>
      <Table
        rowKey="id"
        dataSource={items}
        scroll={{ x: 720 }}
        pagination={{ current: page, total, pageSize: 20, onChange: setPage }}
        columns={[
          {
            title: ui("算法", "Algorithm"),
            key: "name",
            render: (_, algorithm) => (
              <Space orientation="vertical" size={0}>
                <Typography.Text strong>{ui(algorithm.name)}</Typography.Text>
                <Typography.Text type="secondary">
                  {algorithm.identifier}
                </Typography.Text>
              </Space>
            ),
          },
          { title: ui("分类", "Category"), dataIndex: "category", render: (value: string) => ui(value) },
          {
            title: ui("状态", "Status"),
            key: "enabled",
            render: (_, algorithm) => (
              <Tag color={algorithm.enabled ? "success" : "default"}>
                {algorithm.enabled
                  ? ui("启用", "Enabled")
                  : ui("停用", "Disabled")}
              </Tag>
            ),
          },
          {
            title: ui("版本", "Versions"),
            key: "versions",
            render: (_, algorithm) => algorithm.versions.length,
          },
          {
            title: ui("操作", "Actions"),
            key: "actions",
            render: (_, algorithm) => (
              <Space>
                <Button onClick={() => setDetail(algorithm)}>
                  {ui("管理版本", "Versions")}
                </Button>
                <Button onClick={() => edit(algorithm)}>
                  {ui("编辑", "Edit")}
                </Button>
                <Button
                  danger
                  disabled={busy}
                  icon={<DeleteOutlined />}
                  onClick={() => remove(algorithm)}
                >
                  {ui("删除", "Delete")}
                </Button>
              </Space>
            ),
          },
        ]}
      />
      <Typography.Title level={5}>
        {ui("算法包模板", "Package templates")}
      </Typography.Title>
      <Space wrap>
        {[
          [1, "栅格线性变换", "Raster transform"],
          [4, "NDVI示例", "NDVI example"],
          [5, "NDWI水体指数", "NDWI water index"],
          [2, "矢量缓冲区", "Vector buffer"],
          [6, "矢量面积与周长", "Polygon area and perimeter"],
          [3, "表格分组汇总", "Table summary"],
        ].map(([id, zh, en]) => (
          <Button
            key={id}
            onClick={() =>
              perform(() =>
                downloadComputeFile(
                  `/api/compute/templates/${id}/`,
                  `operator-template-${id}.zip`,
                ),
              )
            }
          >
            {ui(String(zh), String(en))}
          </Button>
        ))}
      </Space>
      <Modal
        open={editing !== undefined}
        title={
          editing
            ? ui("编辑算法", "Edit algorithm")
            : ui("登记算法", "Register algorithm")
        }
        onCancel={() => setEditing(undefined)}
        confirmLoading={busy}
        onOk={() =>
          perform(async () => {
            const body = await form.validateFields();
            await computeApi.saveAlgorithm(editing?.id ?? null, body);
            if (alive.current) setEditing(undefined);
          })
        }
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label={ui("算法名称", "Name")}
            rules={[{ required: true }]}
          >
            <Input maxLength={160} />
          </Form.Item>
          <Form.Item
            name="identifier"
            label={ui(
              "稳定标识（与包内identifier一致）",
              "Identifier (matches the package)",
            )}
            rules={[{ required: true }, { pattern: /^[a-z][a-z0-9_-]{0,79}$/ }]}
          >
            <Input disabled={!!editing?.versions.length} maxLength={80} />
          </Form.Item>
          <Form.Item name="category" label={ui("分类", "Category")}>
            <Select
              allowClear
              options={categories.map((c) => ({ value: c, label: ui(c) }))}
            />
          </Form.Item>
          <Form.Item name="author" label={ui("作者或来源", "Author or source")}>
            <Input maxLength={160} />
          </Form.Item>
          <Form.Item
            name="description"
            label={ui("用途和限制", "Purpose and limitations")}
          >
            <Input.TextArea rows={3} maxLength={4000} />
          </Form.Item>
          <Form.Item
            name="enabled"
            label={ui("启用算法", "Enabled")}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        open={categoryOpen}
        title={ui("新增算法分类", "New algorithm category")}
        onCancel={() => setCategoryOpen(false)}
        confirmLoading={busy}
        onOk={() =>
          perform(async () => {
            await computeApi.createCategory(category);
            if (alive.current) {
              setCategoryOpen(false);
              setCategory("");
            }
          })
        }
      >
        <Input
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          maxLength={80}
        />
      </Modal>
      <Drawer
        open={!!detail}
        width={840}
        title={detail?.name}
        onClose={() => setDetail(null)}
      >
        {detail && (
          <Space orientation="vertical" size={20} style={{ width: "100%" }}>
            <Typography.Paragraph>{detail.description}</Typography.Paragraph>
            {!runtimeAvailable && (
              <Alert
                type="warning"
                showIcon
                title={ui(
                  "计算执行环境待就绪",
                  "Compute execution environment is not ready",
                )}
                description={runtimeDetail}
              />
            )}
            {error && <Alert type="error" title={error} />}
            <Space orientation="vertical" size={8}>
              <Typography.Text strong>
                {ui(
                  "上传新版本 ZIP（最多50 MiB）",
                  "Upload version ZIP (up to 50 MiB)",
                )}
              </Typography.Text>
              <Button
                loading={busy}
                onClick={() => packageInput.current?.click()}
              >
                {ui("选择并上传算法包", "Choose and upload package")}
              </Button>
              <input
                ref={packageInput}
                type="file"
                accept=".zip"
                aria-label={ui(
                  "选择算法包 ZIP",
                  "Choose algorithm package ZIP",
                )}
                disabled={busy}
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) {
                    if (file.size > 50 * 1024 ** 2) {
                      setError(ui("文件超过50 MiB", "File exceeds 50 MiB"));
                      return;
                    }
                    void perform(() => computeApi.upload(detail.id, file));
                  }
                }}
              />
            </Space>
            {detail.versions.map((version) => (
              <div key={version.id} className="compute-version-card">
                <Space wrap>
                  <Typography.Title level={5} style={{ margin: 0 }}>
                    {version.version}
                  </Typography.Title>
                  <Tag>
                    {version.status === "draft"
                      ? ui("草稿", "Draft")
                      : version.status === "published"
                        ? ui("已发布", "Published")
                        : ui("已归档", "Archived")}
                  </Tag>
                  <Tag color={version.validated ? "success" : "warning"}>
                    {version.validated
                      ? ui("试运行通过", "Trial passed")
                      : ui("尚未通过试运行", "Trial required")}
                  </Tag>
                </Space>
                <Typography.Paragraph type="secondary">
                  {ui(version.manifest.description)}
                </Typography.Paragraph>
                <Space wrap>
                  <Tooltip
                    title={
                      !runtimeAvailable
                        ? runtimeDetail
                        : !detail.enabled
                          ? ui("请先启用算法", "Enable the algorithm first")
                          : !runtimePermissions.submit_task
                            ? ui(
                                "没有提交计算任务权限",
                                "You do not have permission to submit tasks",
                              )
                            : undefined
                    }
                  >
                    <span>
                      <Button
                        disabled={
                          !runtimeAvailable ||
                          !detail.enabled ||
                          !runtimePermissions.submit_task ||
                          version.status === "archived"
                        }
                        onClick={() => onTrial(version)}
                      >
                        {ui("试运行", "Trial run")}
                      </Button>
                    </span>
                  </Tooltip>
                  {version.status === "draft" &&
                    runtimePermissions.publish_algorithm && (
                      <Button
                        type="primary"
                        disabled={!version.validated}
                        onClick={() =>
                          perform(() =>
                            computeApi.versionAction(version.id, "publish"),
                          )
                        }
                      >
                        {ui("发布", "Publish")}
                      </Button>
                    )}
                  {version.status !== "archived" && (
                    <Button
                      onClick={() =>
                        perform(() =>
                          computeApi.versionAction(version.id, "archive"),
                        )
                      }
                    >
                      {ui("归档停用", "Archive")}
                    </Button>
                  )}
                  {runtimePermissions.download_algorithm && (
                    <Button
                      onClick={() =>
                        perform(() =>
                          downloadComputeFile(
                            `/api/compute/versions/${version.id}/package/`,
                            `${detail.identifier}-${version.version}.zip`,
                          ),
                        )
                      }
                    >
                      {ui("下载源码包", "Download package")}
                    </Button>
                  )}
                </Space>
                <details style={{ marginTop: 16 }}>
                  <summary>
                    {ui(
                      "输入、参数和输出规范",
                      "Input, parameter and output specification",
                    )}
                  </summary>
                  <pre className="compute-manifest">
                    {JSON.stringify(version.manifest, null, 2)}
                  </pre>
                </details>
                <Typography.Paragraph
                  type="secondary"
                  style={{ marginTop: 10, wordBreak: "break-all" }}
                >
                  SHA256: {version.checksum}
                </Typography.Paragraph>
              </div>
            ))}
          </Space>
        )}
      </Drawer>
    </Space>
  );
}
