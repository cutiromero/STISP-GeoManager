import { EyeOutlined } from "@ant-design/icons";
import { Button, Spin } from "antd";
import { lazy, Suspense, useEffect, useState } from "react";
import type { BusinessFlowNodeState } from "../api/generated/types.gen";
import { nodeComputeTaskIds } from "./businessFlowOutputs";
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
  const taskIds = nodeComputeTaskIds(node);
  const taskKey = taskIds.join(",");
  const [opened, setOpened] = useState<{ taskKey: string; revision: string }>();
  useEffect(() => {
    setOpened(undefined);
  }, [node.nodeId, taskKey]);
  if (
    !taskIds.length ||
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
            previous?.taskKey === taskKey
              ? undefined
              : { taskKey, revision: String(revision) },
          )
        }
      >
        {opened?.taskKey === taskKey
          ? ui("收起计算结果", "Hide computation results")
          : node.status === "waiting_compute"
            ? ui("查看计算进度与结果", "View progress and results")
            : ui("查看节点计算结果", "View computation results")}
      </Button>
      {opened?.taskKey === taskKey && (
        <div className="business-flow-node-result">
          <Suspense fallback={<Spin size="small" />}>
            <RunComputeTasks
              taskIds={taskIds}
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
