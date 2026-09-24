import { describe, expect, it } from "vitest";
import type { AgentBudgetOptions } from "../api/generated/types.gen";
import { budgetPreview } from "./TaskBudgetControl";

const options: AgentBudgetOptions = {
  enabled: true,
  tier: "superadmin",
  defaultProfile: "normal",
  maxPromptCharacters: 1048576,
  limits: {
    contextWindowTokens: 262144,
    maxOutputTokens: 261632,
    maxRunSeconds: 7200,
  },
  profiles: [
    {
      budgetProfile: "normal",
      tier: "superadmin",
      contextWindowTokens: 262144,
      maxOutputTokens: 32768,
      maxRunSeconds: 1800,
      reasoningEffort: "medium",
      requestedMaxOutputTokens: null,
    },
    {
      budgetProfile: "materials",
      tier: "superadmin",
      contextWindowTokens: 262144,
      maxOutputTokens: 16384,
      maxRunSeconds: 1800,
      reasoningEffort: "low",
      requestedMaxOutputTokens: null,
    },
    {
      budgetProfile: "reasoning",
      tier: "superadmin",
      contextWindowTokens: 262144,
      maxOutputTokens: 65536,
      maxRunSeconds: 3600,
      reasoningEffort: "xhigh",
      requestedMaxOutputTokens: null,
    },
  ],
};

describe("task budget preview", () => {
  it("leaves more room for long materials and more generation for reasoning", () => {
    expect(budgetPreview(options, "materials", 262144).input).toBe(245504);
    expect(budgetPreview(options, "reasoning", 262144).input).toBe(196352);
    expect(budgetPreview(options, "normal", 262144).output).toBe(32768);
  });
  it("caps small models and keeps the safety margin", () => {
    expect(budgetPreview(options, "reasoning", 32768)).toMatchObject({
      window: 32768,
      output: 16384,
      input: 16128,
      ceiling: 32256,
    });
  });
  it("shows a manual budget without pretending it is already consumed", () => {
    expect(budgetPreview(options, "normal", 262144, 131072)).toMatchObject({
      output: 131072,
      input: 130816,
    });
  });
});
