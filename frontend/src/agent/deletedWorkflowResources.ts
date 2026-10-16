import type { AgentWorkflow } from "../api/generated/types.gen";

/** Read-only display of deletion receipts; these entries are never usable inputs. */
export function deletedWorkflowResources(workflow: AgentWorkflow) {
  const receipts = workflow.plan.deletedResources;
  if (!Array.isArray(receipts)) return [];
  return receipts.flatMap((value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return [];
    const receipt = value as Record<string, unknown>;
    if (
      receipt.status !== "deleted" ||
      typeof receipt.formerResourceId !== "number" ||
      !Number.isInteger(receipt.formerResourceId)
    )
      return [];
    return [
      {
        id: receipt.formerResourceId,
        name:
          typeof receipt.name === "string" ? receipt.name : "已删除的目录数据",
        source: typeof receipt.source === "string" ? receipt.source : "",
        deletedAt:
          typeof receipt.deletedAt === "string" ? receipt.deletedAt : "",
      },
    ];
  });
}
