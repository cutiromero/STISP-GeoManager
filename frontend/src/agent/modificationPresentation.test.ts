import { expect, it } from "vitest";
import type { AgentModificationSuggestion } from "../api/generated/types.gen";
import {
  heldModificationGroups,
  modificationAction,
  presentationGroups,
  selectableModification,
} from "./modificationPresentation";

const suggestion = (
  overrides: Partial<AgentModificationSuggestion> = {},
): AgentModificationSuggestion =>
  ({
    id: "one",
    element: "lithology",
    ruleId: "L-01",
    groupId: "target-C",
    action: "reclassify",
    suggestedState: "reclassify C",
    status: "suggested",
    reason: "合成夹具",
    ...overrides,
  }) as AgentModificationSuggestion;

it("merges presentation groups across target codes and snapshots without changing approval identities", () => {
  const items = Array.from({ length: 80 }, (_, index) =>
    suggestion({
      id: `issue-${index}`,
      groupId: `snapshot-${index}`,
      suggestedState: `reclassify ${index % 2 ? "C" : "O"}`,
    }),
  );
  const held = suggestion({ id: "protected", status: "exception" });
  const groups = presentationGroups(
    [...items, held].filter(selectableModification),
  );
  expect(groups.size).toBe(1);
  expect([...groups.values()][0]?.map((item) => item.id)).toEqual(
    items.map((item) => item.id),
  );
  const selected = [...groups.values()][0]!.filter(
    (item) => item.id !== "issue-1",
  );
  expect(selected).toHaveLength(79);
  expect(selected.some((item) => item.id === "protected")).toBe(false);
});

it("merges held groups only by element and rule, deduplicates stage summaries, and honors the element filter", () => {
  const stages = [
    {
      results: [
        {
          groups: [
            {
              group_id: "first",
              element: "lithology",
              rule_id: "L-01",
              count: 4,
            },
            {
              group_id: "second",
              element: "lithology",
              rule_id: "L-01",
              count: 6,
            },
            {
              group_id: "other",
              element: "structure",
              rule_id: "S-01",
              count: 3,
            },
          ],
        },
      ],
      groupDecisions: [
        { group_id: "first", disposition: "review", reason: "证据缺口" },
        { group_id: "second", disposition: "review", reason: "地质例外" },
        { group_id: "other", disposition: "review", reason: "核查" },
      ],
    },
  ];
  const items = [
    suggestion({
      status: "review",
      groupId: "other",
      element: "structure",
      ruleId: "S-01",
    }),
  ];
  const groups = heldModificationGroups(items, stages, "all");
  expect(
    groups.map(({ element, ruleId, count }) => [element, ruleId, count]),
  ).toEqual([
    ["structure", "S-01", 3],
    ["lithology", "L-01", 10],
  ]);
  expect(heldModificationGroups(items, stages, "lithology")).toHaveLength(1);
  for (const action of ["keep", "retain", "review"])
    expect(selectableModification(suggestion({ action }))).toBe(false);
});

it.each([
  ["exclude", "exclude", "剔除（从修正后成果删除）"],
  ["delete", "delete", "剔除（从修正后成果删除）"],
  ["downweight", "downweight", "降权"],
  ["reclassify", "reclassify C", "重分类为 C"],
  ["set_code", "set_code O", "改代号为 O"],
])("uses explicit action wording for %s", (action, suggestedState, label) => {
  expect(modificationAction({ action, suggestedState })).toBe(label);
});
