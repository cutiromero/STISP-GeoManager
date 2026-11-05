import { Alert, Button, Modal, Popconfirm, Space, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { agentApi } from "../api/agent";
import { useProjectContext } from "../projects/ProjectContext";
import type {
  AgentActiveWorkflow,
  AgentWorkflow,
} from "../api/generated/types.gen";

const statusLabels: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  waiting_compute: "等待计算",
  waiting_approval: "等待确认",
  paused: "已暂停",
};
const sceneLabels: Record<string, string> = {
  geology_generic: "通用地质推理",
  research_processing: "通用科研计算",
  geology_multi_element_reasoning: "多要素综合推理",
  geology_map_review: "地质图复查",
  geology_correction: "地质纠错",
  geology_age_correction: "地质年代纠错",
  ecology_investigation: "生态调查",
};

export default function ActiveWorkflowNotice({
  projectId,
  currentId,
  refreshKey,
}: {
  projectId: string;
  currentId?: string;
  refreshKey: string;
}) {
  const projects = useProjectContext()?.projects ?? [];
  const [item, setItem] = useState<AgentActiveWorkflow | null>(null);
  const [parked, setParked] = useState<AgentActiveWorkflow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<AgentWorkflow>();
  const [attempt, setAttempt] = useState(0);
  const currentProject = useRef(projectId);
  currentProject.current = projectId;
  useEffect(() => {
    const controller = new AbortController();
    setItem(null);
    setParked([]);
    setError("");
    setDetail(undefined);
    setBusy(false);
    const load = () =>
      void agentApi
        .activeWorkflow({ signal: controller.signal })
        .then((result) => {
          if (!controller.signal.aborted) {
            setItem(result.item);
            setParked(Array.isArray(result.parked) ? result.parked : []);
            setError("");
          }
        })
        .catch((reason) => {
          if (!controller.signal.aborted)
            setError(
              reason instanceof Error ? reason.message : "活动任务读取失败",
            );
        });
    load();
    const timer = window.setInterval(load, 10000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [projectId, currentId, refreshKey, attempt]);
  const operate = async (selected: AgentActiveWorkflow, cancel: boolean) => {
    const requestedProject = projectId;
    setBusy(true);
    setError("");
    try {
      const result = cancel
        ? await agentApi.cancelWorkflow(
            selected.id,
            undefined,
            String(selected.projectId),
          )
        : await agentApi.workflow(selected.id, {
            projectTagId: String(selected.projectId),
          });
      if (currentProject.current !== requestedProject) return;
      if (cancel) setAttempt((old) => old + 1);
      else setDetail(result);
    } catch (reason) {
      if (currentProject.current === requestedProject)
        setError(reason instanceof Error ? reason.message : "操作失败");
    } finally {
      if (currentProject.current === requestedProject) setBusy(false);
    }
  };
  return (
    <>
      {error && (
        <Alert
          type="error"
          title={error}
          action={
            <Button
              size="small"
              autoInsertSpace={false}
              onClick={() => setAttempt((old) => old + 1)}
            >
              重试
            </Button>
          }
        />
      )}
      {[...(item ? [item] : []), ...parked]
        .filter((selected) => selected.id !== currentId)
        .map((selected) => (
          <Alert
            key={selected.id}
            type={selected === item ? "warning" : "info"}
            showIcon
            title={`${selected === item ? "正在计算或排队" : "已停放，不阻挡新任务"}：${selected.goal.split(/[。！？\n]/)[0]}`}
            description={
              <Space orientation="vertical">
                <span>
                  场景：
                  {sceneLabels[selected.workflowType] ?? selected.workflowType}
                  ；状态：{statusLabels[selected.status]}；更新时间：
                  {new Date(selected.updatedAt).toLocaleString()}；项目：
                  {projects.find(
                    (project) =>
                      String(project.id) === String(selected.projectId),
                  )?.name ?? "所属项目（名称暂不可用）"}
                  ；对话：
                  {selected.conversationId == null
                    ? "独立任务（未关联对话）"
                    : selected.conversationTitle || "未命名对话"}
                </span>
                <Space>
                  <Button
                    size="small"
                    autoInsertSpace={false}
                    loading={busy}
                    onClick={() => void operate(selected, false)}
                  >
                    查看
                  </Button>
                  <Popconfirm
                    title="确定取消该任务？"
                    description="已完成的计算结果会保留，运行中的任务将在安全边界停止。"
                    okText="确认取消"
                    cancelText="保留任务"
                    onConfirm={() => operate(selected, true)}
                  >
                    <Button size="small" danger disabled={busy}>
                      取消该任务
                    </Button>
                  </Popconfirm>
                </Space>
              </Space>
            }
          />
        ))}
      <Modal
        title="活动工作流"
        open={Boolean(detail)}
        footer={null}
        onCancel={() => setDetail(undefined)}
      >
        {detail && (
          <Space orientation="vertical">
            <Typography.Paragraph>{detail.goal}</Typography.Paragraph>
            <span>
              场景：{sceneLabels[detail.workflowType] ?? detail.workflowType}
            </span>
            <span>状态：{statusLabels[detail.status] ?? detail.status}</span>
            <span>更新时间：{new Date(detail.updatedAt).toLocaleString()}</span>
            <Typography.Paragraph>{detail.detail}</Typography.Paragraph>
            {detail.steps.map((step) => (
              <Typography.Paragraph key={step.id}>
                {step.kind}：{step.message}
              </Typography.Paragraph>
            ))}
          </Space>
        )}
      </Modal>
    </>
  );
}
