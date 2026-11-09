import { EyeOutlined } from "@ant-design/icons";
import { Button, Spin } from "antd";
import { lazy, Suspense, useEffect, useState } from "react";
import type { BusinessFlowNodeState } from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";
const RunComputeTasks = lazy(() => import("../agent/RunComputeTasks"));
const ready = new Set([
  "waiting_compute",
  "executed",
  "reviewing",
  "waiting_human",
  "waiting_approval",
  "succeeded",
  "completed",
]);
export default function BusinessFlowNodeOutputs({
  node,
  title,
  revision,
}: {
  node: BusinessFlowNodeState;
  title: string;
  revision: number;
}) {
  const ui = useComputeText();
  const taskId =
    typeof node.outputs.taskId === "string" &&
    /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(
      node.outputs.taskId,
    )
      ? node.outputs.taskId
      : undefined;
  const [opened, setOpened] = useState<{ taskId: string; revision: string }>();
  useEffect(() => {
    setOpened(undefined);
  }, [node.nodeId, taskId]);
  if (
    !taskId ||
    !(ready.has(node.status) || node.executor.status === "succeeded")
  )
    return null;
  return (
    <section className="business-flow-node-outputs">
      <Button
        size="small"
        icon={<EyeOutlined />}
        aria-label={`${title}：查看节点计算结果`}
        onClick={() =>
          setOpened((previous) =>
            previous?.taskId === taskId
              ? undefined
              : { taskId, revision: String(revision) },
          )
        }
      >
        {opened?.taskId === taskId
          ? ui("收起计算结果", "Hide computation results")
          : node.status === "waiting_compute"
            ? ui("查看计算进度与结果", "View progress and results")
            : ui("查看节点计算结果", "View computation results")}
      </Button>
      {opened?.taskId === taskId && (
        <div className="business-flow-node-result">
          <Suspense fallback={<Spin size="small" />}>
            <RunComputeTasks
              taskIds={[opened.taskId]}
              refreshKey={opened.revision}
              autoImport={false}
              terminal
            />
          </Suspense>
        </div>
      )}
    </section>
  );
}
