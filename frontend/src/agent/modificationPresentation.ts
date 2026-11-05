import type { AgentModificationSuggestion } from "../api/generated/types.gen";
import { record } from "../map/geologyReviewData";

export const modificationActions: Record<string, string> = {
  fix_symbol: "改代号",
  set_symbol: "改代号",
  set_code: "改代号",
  reclassify: "重分类",
  merge: "融合图斑",
  remove: "剔除（从修正后成果删除）",
  exclude: "剔除（从修正后成果删除）",
  delete: "剔除（从修正后成果删除）",
  downweight: "降权",
  retain: "保留",
  keep: "保留",
  review: "待裁定",
};

export function modificationAction(item: {
  action?: string;
  suggestedState: string;
}) {
  const action = item.action ?? "";
  const label = modificationActions[action] ?? item.suggestedState;
  const target = item.suggestedState.startsWith(`${action} `)
    ? item.suggestedState.slice(action.length + 1).trim()
    : "";
  return target &&
    ["reclassify", "set_code", "fix_symbol", "set_symbol"].includes(action)
    ? `${label}为 ${target}`
    : label;
}

export function selectableModification(item: AgentModificationSuggestion) {
  return (
    !["exception", "review", "retained", "pending"].includes(
      item.status ?? "",
    ) && !["keep", "retain", "review"].includes(item.action ?? "")
  );
}

export function presentationGroups(suggestions: AgentModificationSuggestion[]) {
  const groups = new Map<string, AgentModificationSuggestion[]>();
  for (const item of suggestions) {
    const key = JSON.stringify([item.element, item.ruleId, item.action]);
    const members = groups.get(key) ?? [];
    members.push(item);
    groups.set(key, members);
  }
  return groups;
}

export function heldModificationGroups(
  suggestions: AgentModificationSuggestion[],
  stages: Record<string, unknown>[],
  filter: string,
) {
  const groups = new Map<
    string,
    {
      element: string;
      ruleId: string;
      count: number;
      reasons: Set<string>;
    }
  >();
  const add = (
    element: string,
    ruleId: string,
    count: number,
    reason: string,
  ) => {
    if (filter !== "all" && element !== filter) return;
    const key = JSON.stringify([element, ruleId]);
    const group = groups.get(key) ?? {
      element,
      ruleId,
      count: 0,
      reasons: new Set<string>(),
    };
    group.count += count;
    if (reason) group.reasons.add(reason);
    groups.set(key, group);
  };
  const represented = new Map<string, number>();
  for (const item of suggestions.filter(
    (item) => !selectableModification(item),
  )) {
    add(item.element ?? "", item.ruleId, 1, item.reason);
    if (item.groupId)
      represented.set(item.groupId, (represented.get(item.groupId) ?? 0) + 1);
  }
  const summaries = new Map(
    stages
      .flatMap((stage) =>
        (Array.isArray(stage.results) ? stage.results : []).flatMap(
          (result) => {
            const groups = record(result).groups;
            return Array.isArray(groups) ? groups.map(record) : [];
          },
        ),
      )
      .map((group) => [String(group.group_id), group]),
  );
  const summarized = new Set<string>();
  for (const stage of stages) {
    for (const value of Array.isArray(stage.groupDecisions)
      ? stage.groupDecisions
      : []) {
      const decision = record(value);
      const identity = String(decision.group_id);
      if (decision.disposition !== "review" || summarized.has(identity))
        continue;
      const group = summaries.get(identity);
      if (!group) continue;
      summarized.add(identity);
      add(
        String(group.element),
        String(group.rule_id),
        Math.max(
          0,
          Number(group.count ?? 0) - (represented.get(identity) ?? 0),
        ),
        String(decision.reason ?? ""),
      );
    }
  }
  return [...groups.values()];
}
