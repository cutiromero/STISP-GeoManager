import type {
  AgentWorkflow,
  AgentWorkflowConfirmation,
} from "../api/generated/types.gen";
import { record } from "../map/geologyReviewData";
import { agentApi } from "../api/agent";

export type AlterationActions = NonNullable<
  AgentWorkflowConfirmation["alterationActions"]
>;

export async function approvalSelection(
  workflow: AgentWorkflow,
  ids?: string[],
): Promise<
  Pick<
    AgentWorkflowConfirmation,
    "selectedSuggestionIds" | "suggestionSelection"
  >
> {
  if (!ids) return {};
  if (
    ids.length >= 200 &&
    !Array.isArray(record(workflow.plan.reviewIndex).suggestedIds)
  ) {
    const scope = await agentApi.workflow(workflow.id, {
      view: "inspection",
      limit: 0,
    });
    if (scope.planHash !== workflow.planHash)
      throw new Error("审批方案已更新，请刷新建议后重新确认");
    workflow = scope;
  }
  const index = record(workflow.plan.reviewIndex);
  if (ids.length < 200 || !Array.isArray(index.suggestedIds))
    return { selectedSuggestionIds: ids };
  const suggested = new Set(index.suggestedIds.map(String));
  const selected = new Set(ids);
  const compact = {
    base: "suggested" as const,
    excludedIds: [...suggested].filter((id) => !selected.has(id)),
    includedIds: ids.filter((id) => !suggested.has(id)),
  };
  return compact.excludedIds.length + compact.includedIds.length < ids.length
    ? { suggestionSelection: compact }
    : { selectedSuggestionIds: ids };
}
