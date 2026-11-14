import { lazy, Suspense } from "react";
import { Spin } from "antd";
import type { BusinessFlowRun } from "../api/generated/types.gen";
import { businessFlowComputeTaskIds } from "./businessFlowOutputs";
const RunComputeTasks = lazy(() => import("../agent/RunComputeTasks"));
const WorkflowReportFile = lazy(() => import("../agent/WorkflowReportFile"));

export default function BusinessFlowResults({
  flow,
}: {
  flow: BusinessFlowRun;
}) {
  const taskIds = businessFlowComputeTaskIds(flow);
  const outputIds = flow.resultOutputIds ?? [];
  const catalogueKinds = new Set([
    "raster",
    "vector",
    "table",
    "image",
    "document",
    "gene",
  ]);
  const declaredKinds = [
    ...new Set(
      flow.definitionSnapshot.nodes
        .flatMap(
          (node) =>
            node.contract?.requiredOutputs.map(
              (output) => output.semanticType,
            ) ?? [],
        )
        .filter((kind) => catalogueKinds.has(kind)),
    ),
  ];
  const report = (
    <WorkflowReportFile workflowId={flow.id} projectId={flow.projectId} />
  );
  return (
    <Suspense fallback={<Spin />}>
      {taskIds.length ? (
        <RunComputeTasks
          taskIds={taskIds}
          terminal
          autoImport={false}
          display="files"
          refreshKey={`${flow.id}:${outputIds.join(",")}`}
          visibleOutputIds={outputIds}
          visibleOutputKinds={declaredKinds.length ? declaredKinds : undefined}
          report={report}
        />
      ) : (
        report
      )}
    </Suspense>
  );
}
