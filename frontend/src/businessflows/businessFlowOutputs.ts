import type {
  BusinessFlowNodeState,
  BusinessFlowRun,
} from "../api/generated/types.gen";
const taskIdPattern =
  /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export function nodeComputeTaskIds(node: BusinessFlowNodeState) {
  const values = [
    ...(Array.isArray(node.outputs.taskIds) ? node.outputs.taskIds : []),
    node.outputs.taskId,
  ];
  return [
    ...new Set(
      values.filter(
        (value): value is string =>
          typeof value === "string" && taskIdPattern.test(value),
      ),
    ),
  ];
}
export function businessFlowComputeTaskIds(flow: BusinessFlowRun) {
  return [...new Set(flow.nodes.flatMap(nodeComputeTaskIds))];
}
