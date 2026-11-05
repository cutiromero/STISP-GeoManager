import { expect, it, vi } from "vitest";
import { approvalSelection } from "./approvalSelection";
import { reviewWorkflow } from "../map/geologyReview.testFixtures";
import { agentApi } from "../api/agent";

it("encodes thousands of ordinary suggestions without implicitly including held candidates", async () => {
  const workflow = reviewWorkflow();
  const ids = Array.from({ length: 6268 }, (_, index) => `suggestion-${index}`);
  workflow.plan.reviewIndex = {
    total: 6270,
    suggestedIds: ids,
    candidateIds: ["review", "exception"],
    groups: [],
  };
  const all = await approvalSelection(workflow, ids);
  expect(all).toEqual({
    suggestionSelection: {
      base: "suggested",
      excludedIds: [],
      includedIds: [],
    },
  });
  expect(JSON.stringify(all).length).toBeLessThan(128);
  const partial = await approvalSelection(workflow, [
    ...ids.slice(1),
    "exception",
  ]);
  expect(partial).toEqual({
    suggestionSelection: {
      base: "suggested",
      excludedIds: [ids[0]],
      includedIds: ["exception"],
    },
  });
});

it("reads the frozen index for a lightweight card and surfaces stale-plan failures", async () => {
  const workflow = reviewWorkflow();
  workflow.view = "card";
  const ids = Array.from({ length: 6268 }, (_, index) => `suggestion-${index}`);
  const scope = { ...workflow, planHash: "changed" };
  const read = vi.spyOn(agentApi, "workflow").mockResolvedValue(scope);
  await expect(approvalSelection(workflow, ids)).rejects.toThrow(
    "审批方案已更新",
  );
  read.mockRestore();
});
