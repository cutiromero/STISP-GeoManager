import {
  Alert,
  App,
  Button,
  Drawer,
  Popconfirm,
  Progress,
  Space,
  Steps,
  Tag,
} from "antd";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { businessFlowsApi } from "../api/businessFlows";
import { getActiveProject } from "../projects/session";
import type { BusinessFlowRun } from "../api/generated/types.gen";
import { flowStateLabels, nodeStateLabel } from "./businessFlowPresentation";

const active = new Set(["queued", "running", "waiting_compute"]);
const pollMs = 2400;
const validId = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;

export default function FixedFlowRunPanel({
  id,
  initial,
  onClose,
}: {
  id: string;
  initial?: BusinessFlowRun;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [controlling, setControlling] = useState(false);
  const [flow, setFlow] = useState(initial?.id === id ? initial : undefined);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: number;
    const read = async () => {
      try {
        if (!validId.test(id)) throw new Error("任务编号无效");
        const run = await businessFlowsApi.run(id, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        if (String(run.projectId) !== getActiveProject())
          throw new Error("任务不属于当前项目");
        setFlow(run);
        setError("");
        if (active.has(run.status))
          timer = window.setTimeout(() => void read(), pollMs);
      } catch (reason) {
        if (controller.signal.aborted) return;
        setError(
          reason instanceof Error ? reason.message : "暂时无法读取任务状态",
        );
      }
    };
    void read();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [id, attempt]);
  const changeStatus = async (action: "cancel" | "pause" | "resume") => {
    setControlling(true);
    try {
      setFlow(await businessFlowsApi[action](id));
      setAttempt((value) => value + 1);
    } catch (reason) {
      if (!(reason instanceof Error && reason.name === "AbortError"))
        message.error(
          reason instanceof Error ? reason.message : "操作暂未完成",
        );
    } finally {
      setControlling(false);
    }
  };
  const nodes = flow?.definitionSnapshot.nodes ?? [];
  const current = nodes.findIndex((node) => node.id === flow?.currentNode);
  const finished =
    flow?.nodes.filter((node) => node.status === "succeeded").length ?? 0;
  const currentState = flow?.nodes.find(
    (node) => node.nodeId === flow.currentNode,
  );
  const diagnostic = currentState?.contextRecovery?.diagnostic;
  return (
    <Drawer
      open
      title="业务流任务"
      onClose={onClose}
      styles={{ wrapper: { width: "min(640px, 100vw)" } }}
    >
      {error && (
        <Alert
          showIcon
          type="error"
          title={error}
          action={
            <Button onClick={() => setAttempt((value) => value + 1)}>
              重新读取
            </Button>
          }
        />
      )}
      {!flow ? (
        !error && <Alert showIcon type="info" title="正在读取实际任务状态" />
      ) : (
        <Space orientation="vertical" size="large" style={{ width: "100%" }}>
          <div>
            <h2>{flow.name}</h2>
            <Tag color={flow.status === "succeeded" ? "green" : "blue"}>
              {flowStateLabels[flow.status] ?? flow.status}
            </Tag>
          </div>
          <Progress
            aria-label="业务流进度"
            percent={
              nodes.length ? Math.round((100 * finished) / nodes.length) : 0
            }
            status={
              flow.status === "failed"
                ? "exception"
                : active.has(flow.status)
                  ? "active"
                  : undefined
            }
          />
          <Steps
            orientation="vertical"
            size="small"
            current={
              flow.status === "succeeded" ? nodes.length : Math.max(0, current)
            }
            items={nodes.map((node) => {
              const state = flow.nodes.find((row) => row.nodeId === node.id);
              return {
                title: node.title,
                description: state ? nodeStateLabel(state) : node.description,
              };
            })}
          />
          {diagnostic && (
            <Alert
              showIcon
              type="warning"
              title={diagnostic.analysis}
              description={diagnostic.facts.join("；")}
            />
          )}
          {(active.has(flow.status) ||
            flow.status === "paused" ||
            flow.status === "waiting_approval") && (
            <Space>
              {active.has(flow.status) && (
                <Button
                  loading={controlling}
                  onClick={() => void changeStatus("pause")}
                >
                  暂停任务
                </Button>
              )}
              {flow.status === "paused" && (
                <Button
                  loading={controlling}
                  onClick={() => void changeStatus("resume")}
                >
                  继续任务
                </Button>
              )}
              <Popconfirm
                title="停止本次任务？"
                description="停止后不会自动重新计算，已生成成果仍保留。"
                onConfirm={() => changeStatus("cancel")}
              >
                <Button danger loading={controlling}>
                  停止任务
                </Button>
              </Popconfirm>
            </Space>
          )}
          {flow.status === "succeeded" && (
            <Alert
              showIcon
              type="success"
              title={`已归档 ${flow.resultResourceIds?.length ?? 0} 项成果`}
              description="点击进入数据中心查看；主地图可登记为正式成果。"
            />
          )}
          {flow.status === "succeeded" && (
            <Button
              type="primary"
              onClick={() =>
                navigate(
                  `/resources/catalog?view=task-results&taskGroup=${flow.id}&projectTagId=${flow.projectId}`,
                )
              }
            >
              查看任务成果
            </Button>
          )}
          {flow.conversationId &&
            flow.definitionSnapshot.executionMode !== "fixed" && (
              <Link
                to={`/agent/workbench?conversationId=${flow.conversationId}&projectTagId=${flow.projectId}`}
              >
                查看完整处理记录
              </Link>
            )}
        </Space>
      )}
    </Drawer>
  );
}
