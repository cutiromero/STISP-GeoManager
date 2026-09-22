import {
  App,
  Alert,
  Button,
  Card,
  Empty,
  Input,
  Pagination,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import {
  CalculatorOutlined,
  ExperimentOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
} from "@ant-design/icons";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import WorkspaceHeader from "../components/WorkspaceHeader";
import { useAppContext } from "../contexts/AppContext";
import { useProjectContext } from "../projects/ProjectContext";
import {
  computeApi,
  type ComputeAlgorithm,
  type ComputeRuntimeStatus,
  type ComputeTask,
  type ComputeVersion,
} from "../api/compute";
import AlgorithmManager from "./AlgorithmManager";
import ComputeTaskForm from "./ComputeTaskForm";
import ComputeTaskDetail, { OutputTable } from "./ComputeTaskDetail";
import { taskStatusLabels, statusText, useComputeText } from "./ui";
import "./compute.css";

export default function ComputePage({ admin = false }: { admin?: boolean }) {
  const project = useProjectContext();
  const { user } = useAppContext();
  return (
    <ComputeWorkspace
      key={`${project?.current ?? "1"}:${user?.id ?? "anonymous"}`}
      admin={admin}
    />
  );
}

function ComputeWorkspace({ admin }: { admin: boolean }) {
  const ui = useComputeText();
  const { user } = useAppContext();
  const project = useProjectContext();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [params] = useSearchParams();
  const [tab, setTab] = useState(admin ? "manage" : "algorithms");
  const [runtime, setRuntime] = useState<ComputeRuntimeStatus | null>(null);
  const [algorithms, setAlgorithms] = useState<ComputeAlgorithm[]>([]);
  const [tasks, setTasks] = useState<ComputeTask[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [category, setCategory] = useState<string>();
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState<string>();
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [taskPage, setTaskPage] = useState(1);
  const [taskTotal, setTaskTotal] = useState(0);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [creating, setCreating] = useState<{
    version: ComputeVersion;
    trial: boolean;
    initial?: ComputeTask;
  } | null>(null);
  const [selectedTask, setSelectedTask] = useState<string | null>(
    params.get("task"),
  );
  const [selectedVersions, setSelectedVersions] = useState<
    Record<number, number | undefined>
  >({});
  useEffect(() => {
    let live = true;
    computeApi
      .algorithms({ page, q: keyword, category })
      .then((data) => {
        if (live) {
          setAlgorithms(data.items);
          setTotal(data.total);
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
  }, [page, keyword, category, revision]);
  useEffect(() => {
    if (!user) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const data = await computeApi.runtime();
        if (live) setRuntime(data);
        if (
          data.permissions.view_own_task ||
          (admin && data.permissions.manage_tasks)
        ) {
          const list = await computeApi.tasks({
            page: taskPage,
            status,
            manage: admin && data.permissions.manage_tasks ? 1 : undefined,
          });
          if (live) {
            setTasks(list.items);
            setTaskTotal(list.total);
          }
        }
      } catch (e) {
        if (live && e instanceof Error) setError(e.message);
      } finally {
        if (live) timer = setTimeout(refresh, 5000);
      }
    };
    void refresh();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [user, taskPage, status, revision, admin]);
  const onSubmitted = (task: ComputeTask) => {
    setCreating(null);
    setSelectedTask(task.id);
    setTab("tasks");
    setRevision((r) => r + 1);
  };
  const permissions = runtime?.permissions ?? {};
  const algorithmsView = (
    <>
      <div className="compute-toolbar">
        <Input.Search
          allowClear
          placeholder={ui("搜索算法名称", "Search algorithms")}
          onSearch={(value) => {
            setKeyword(value);
            setPage(1);
          }}
          style={{ maxWidth: 360 }}
        />
        <Select
          allowClear
          placeholder={ui("全部分类", "All categories")}
          value={category}
          onChange={(value) => {
            setCategory(value);
            setPage(1);
          }}
          options={categories.map((c) => ({ value: c, label: c }))}
          style={{ minWidth: 180 }}
        />
      </div>
      <div className="compute-algorithm-grid">
        {algorithms.map((algorithm) => (
          <Card
            key={algorithm.id}
            className="compute-algorithm-card"
            title={
              <Space>
                <ExperimentOutlined />
                <span>{algorithm.name}</span>
              </Space>
            }
            extra={
              <Tag>
                {algorithm.projectTagId === 1
                  ? ui("公开算法", "Public algorithm")
                  : ui("项目算法", "Project algorithm")}
              </Tag>
            }
          >
            <Typography.Paragraph>{algorithm.description}</Typography.Paragraph>
            <Space wrap>
              <Tag>{algorithm.category || ui("未分类", "Uncategorized")}</Tag>
              {algorithm.versions[0]?.manifest.inputs.map((input) => (
                <Tag key={input.key}>{input.kind}</Tag>
              ))}
            </Space>
            <div className="compute-card-footer">
              <Typography.Text type="secondary">
                {algorithm.author}
              </Typography.Text>
              <Select
                placeholder={ui(
                  "选择版本开始计算",
                  "Choose a version to compute",
                )}
                value={selectedVersions[algorithm.id]}
                disabled={!runtime?.available || !permissions.submit_task}
                onChange={(id) => {
                  setSelectedVersions((old) => ({ ...old, [algorithm.id]: id }));
                }}
                options={algorithm.versions.map((v) => ({
                  value: v.id,
                  label: v.version,
                }))}
                style={{ minWidth: 150 }}
              />
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                disabled={
                  !selectedVersions[algorithm.id] ||
                  !runtime?.available ||
                  !permissions.submit_task
                }
                onClick={() => {
                  const version = algorithm.versions.find(
                    (v) => v.id === selectedVersions[algorithm.id],
                  );
                  if (version) setCreating({ version, trial: false });
                }}
              >
                {ui("执行", "Run")}
              </Button>
            </div>
          </Card>
        ))}
      </div>
      {!algorithms.length && (
        <Empty
          description={ui(
            "当前项目暂无已发布算法；管理员可添加算法包，试运行后发布。",
            "No published algorithms are available. Administrators can add packages and publish after a trial.",
          )}
        />
      )}
      <Pagination
        current={page}
        total={total}
        pageSize={20}
        onChange={setPage}
        style={{ marginTop: 24 }}
      />
    </>
  );
  const tasksView = (
    <>
      <div className="compute-toolbar">
        <Select
          allowClear
          placeholder={ui("全部状态", "All statuses")}
          value={status}
          style={{ minWidth: 180 }}
          onChange={(value) => {
            setStatus(value);
            setTaskPage(1);
          }}
          options={Object.entries(taskStatusLabels).map(([value, label]) => ({
            value,
            label: ui(...label),
          }))}
        />
        <Typography.Text type="secondary">
          {admin
            ? ui(
                "显示当前项目内有权管理的任务",
                "Authorized tasks in the current project",
              )
            : ui(
                "仅显示当前项目内本人提交的任务",
                "Only your tasks in the current project",
              )}
        </Typography.Text>
      </div>
      <Table
        rowKey="id"
        dataSource={tasks}
        scroll={{ x: 760 }}
        pagination={{
          current: taskPage,
          total: taskTotal,
          pageSize: 20,
          onChange: setTaskPage,
        }}
        onRow={(task) => ({ onDoubleClick: () => setSelectedTask(task.id) })}
        columns={[
          {
            title: ui("任务", "Task"),
            key: "name",
            render: (_, task) => (
              <Button
                type="link"
                onClick={() => {
                  setSelectedTask(task.id);
                  void computeApi.action(task.id, "read").catch(() => {});
                }}
              >
                {task.name}
                {task.unread && " •"}
              </Button>
            ),
          },
          { title: ui("算法", "Algorithm"), dataIndex: "algorithmName" },
          {
            title: ui("状态", "Status"),
            key: "status",
            render: (_, task) => (
              <Tag
                color={
                  task.status === "succeeded"
                    ? "success"
                    : task.status === "failed"
                      ? "error"
                      : "processing"
                }
              >
                {statusText(ui, task.status)}
              </Tag>
            ),
          },
          { title: ui("阶段", "Stage"), dataIndex: "stage" },
          {
            title: ui("提交时间", "Created"),
            key: "created",
            render: (_, task) => new Date(task.createdAt).toLocaleString(),
          },
        ]}
      />
    </>
  );
  const resultView = (
    <>
      <Alert
        type="info"
        title={ui(
          "结果默认保留7天；入库后的数据长期保留。入库失败可以单独重试。",
          "Temporary results are retained for 7 days by default. Imported data remains available; imports can be retried independently.",
        )}
        style={{ marginBottom: 20 }}
      />
      <OutputTable
        outputs={tasks.flatMap((task) => task.outputs)}
        permissions={permissions}
        onChanged={() => setRevision((r) => r + 1)}
      />
      <Pagination
        current={taskPage}
        total={taskTotal}
        pageSize={20}
        onChange={setTaskPage}
        style={{ marginTop: 24 }}
      />
    </>
  );
  const help = (
    <Space orientation="vertical" size={16}>
      <Typography.Title level={4}>
        {ui(
          "选择算法，让数据继续产生结果",
          "Choose an algorithm and compute with your data",
        )}
      </Typography.Title>
      <Typography.Paragraph>
        {ui(
          "1. 切换到要操作的项目。选择已发布算法和固定版本，平台会按清单生成数据选择器与参数表单。",
          "1. Select your project, then choose a published algorithm version. The platform builds its input and parameter form.",
        )}
      </Typography.Paragraph>
      <Typography.Paragraph>
        {ui(
          "2. 选择当前项目内有权访问的栅格、矢量或表格，填写参数后提交。关闭浏览器不影响已提交任务。",
          "2. Select authorized raster, vector or table inputs and submit parameters. Closing the browser does not stop submitted tasks.",
        )}
      </Typography.Paragraph>
      <Typography.Paragraph>
        {ui(
          "3. 在“我的任务”查看阶段、取消或重试。在结果列表预览属性与元数据，下载实际计算文件，或存入数据资源后继续分析和制图。",
          "3. Track, cancel or retry tasks. Preview attributes and metadata, download scientific files, or import results for further analysis and mapping.",
        )}
      </Typography.Paragraph>
      <Typography.Paragraph>
        {ui(
          "管理员通过后台登记算法并上传 ZIP。包内需有 operator.yaml、main.py、README.md；使用模板中的 run(context) 接口。每个新版本先试运行，核对结果后发布。代码和参数声明一经上传不能改写，修改需上传新版本。",
          "Administrators register algorithms and upload ZIP packages containing operator.yaml, main.py and README.md. Use the run(context) template interface. Trial and review each immutable version before publishing.",
        )}
      </Typography.Paragraph>
      <Typography.Paragraph type="secondary">
        {ui(
          "任务一次只属于一个项目。公开算法可处理私有数据，但不会把数据或结果公开给算法作者。空间查询仍仅针对已加载的矢量图层。",
          "Each task belongs to one project. Public algorithms can process private inputs without sharing data or results with their authors. Spatial queries remain restricted to loaded vector layers.",
        )}
      </Typography.Paragraph>
    </Space>
  );
  const tabs = [
    ...(admin
      ? [
          {
            key: "manage",
            label: ui("算法管理", "Algorithm management"),
            children: (
              <AlgorithmManager
                runtime={runtime}
                refreshKey={revision}
                onTrial={(version) => setCreating({ version, trial: true })}
              />
            ),
          },
        ]
      : [
          {
            key: "algorithms",
            label: ui("算法资源", "Algorithms"),
            children: algorithmsView,
          },
        ]),
    {
      key: "tasks",
      label: admin
        ? ui("任务管理", "Task management")
        : ui("我的任务", "My tasks"),
      children: user ? (
        tasksView
      ) : (
        <Empty description={ui("登录后查看任务", "Sign in to view tasks")} />
      ),
    },
    {
      key: "results",
      label: ui("计算结果", "Results"),
      children: user ? resultView : <Empty />,
    },
    ...(admin
      ? [
          {
            key: "runtime",
            label: ui("运行环境", "Runtime"),
            children: (
              <Space orientation="vertical">
                <Alert
                  type={runtime?.available ? "success" : "warning"}
                  title={runtime?.detail ?? ui("正在检查", "Checking")}
                />
                <Typography.Paragraph>
                  {ui(
                    "运行环境由部署配置固定；算法包在本机 Python 子进程中执行，不能通过平台接口访问数据库。",
                    "The runtime is fixed by deployment configuration. Algorithm packages run in a local Python child process and cannot access the platform database through its APIs.",
                  )}
                </Typography.Paragraph>
                <pre className="compute-manifest">
                  {JSON.stringify(
                    { runtimes: runtime?.runtimes, limits: runtime?.limits },
                    null,
                    2,
                  )}
                </pre>
              </Space>
            ),
          },
        ]
      : []),
    { key: "help", label: ui("使用说明", "Help"), children: help },
  ];
  const content = (
    <div className="compute-content">
      {!admin && (
        <div className="compute-intro">
          <div>
            <Typography.Text className="compute-eyebrow">
              {ui("时空计算 · 算法与数据", "GEOSPATIAL COMPUTING")}
            </Typography.Text>
            <Typography.Title level={2}>
              <CalculatorOutlined /> {ui("计算中心", "Compute center")}
            </Typography.Title>
            <Typography.Paragraph>
              {ui(
                "选择算法，提交任务，让结果回到数据工作流。",
                "Choose an algorithm, submit a task and bring results back into your data workflow.",
              )}
            </Typography.Paragraph>
          </div>
          <Tag color="geekblue">
            {project?.projects.find((p) => String(p.id) === project.current)
              ?.name ?? ui("公开", "Public")}
          </Tag>
        </div>
      )}
      {user && runtime && !runtime.available && (
        <Alert
          type="warning"
          showIcon
          title={ui(
            "计算执行环境待就绪",
            "Compute execution environment is not ready",
          )}
          description={runtime.detail}
          style={{ marginBottom: 20 }}
        />
      )}
      {error && (
        <Alert
          type="error"
          title={error}
          closable
          onClose={() => setError("")}
          style={{ marginBottom: 16 }}
        />
      )}
      <Tabs
        activeKey={tab}
        onChange={(key) => {
          setTab(key);
          if (key === "manage") setRevision((r) => r + 1);
        }}
        items={tabs}
        tabBarExtraContent={
          <Space>
            {!admin && permissions.manage_algorithms && (
              <Button onClick={() => navigate("/admin/compute")}>
                {ui("管理算法", "Manage algorithms")}
              </Button>
            )}
            <Button
              icon={<ReloadOutlined />}
              onClick={() => setRevision((r) => r + 1)}
            >
              {ui("刷新", "Refresh")}
            </Button>
          </Space>
        }
      />
      {creating && (
        <ComputeTaskForm
          version={creating.version}
          trial={creating.trial}
          initial={creating.initial}
          resourceId={Number(params.get("resourceId")) || undefined}
          onClose={() => setCreating(null)}
          onSubmitted={onSubmitted}
        />
      )}
      {selectedTask && (
        <ComputeTaskDetail
          id={selectedTask}
          permissions={permissions}
          onClose={() => {
            setSelectedTask(null);
            setRevision((r) => r + 1);
          }}
          onCopy={(task) => {
            if (!runtime?.available) {
              message.warning(
                ui("请先完成运行环境部署", "Complete runtime setup first"),
              );
              return;
            }
            setSelectedTask(null);
            setCreating({
              version: task.version,
              trial: task.trial,
              initial: task,
            });
          }}
        />
      )}
    </div>
  );
  return admin ? (
    content
  ) : (
    <div className="compute-shell">
      <WorkspaceHeader
        activeTab="compute"
        canBrowseData={!!user?.permissions.canBrowseData}
      />
      {content}
    </div>
  );
}
