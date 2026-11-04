import { describe, expect, it } from "vitest";
import { liveComputeTask } from "../agent/computeFlow.testFixtures";
import { ResponseFormatError } from "./responseDiagnostics";
import {
  assertAgentComputeTasks,
  assertAgentResources,
  assertWorkflow,
  assertWorkflowSummaryList,
} from "./workflowResponse";

const workflow = () => ({
  id: "saved",
  projectId: 3,
  workflowType: "geology_map_review",
  goal: "检查地图",
  status: "succeeded",
  detail: "",
  currentStep: "finish",
  createdAt: "2026-11-04",
  updatedAt: "2026-11-04",
  planHash: "frozen",
  plan: {},
  parameters: {},
  resourceIds: [1],
  resultIds: [],
  resultResourceIds: [],
  evidence: [],
  steps: [
    {
      id: 1,
      sequence: 1,
      kind: "review_feedback",
      status: "succeeded",
      message: "已批准",
      computeTaskId: "",
      action: { decision: "approve" },
      inputRefs: {},
      outputRefs: {},
      metrics: {},
      decision: null,
    },
  ],
});

describe("durable workflow response boundaries", () => {
  it("accepts a persisted workflow without changing the plan, evidence or approval", () => {
    const saved = workflow();
    const before = structuredClone(saved);
    expect(() => assertWorkflow(saved)).not.toThrow();
    expect(saved).toEqual(before);
  });

  it.each(["plan", "parameters"])("rejects missing object %s", (key) => {
    for (const bad of [undefined, null, []])
      expect(() => assertWorkflow({ ...workflow(), [key]: bad })).toThrow(
        ResponseFormatError,
      );
  });

  it.each([
    "steps",
    "evidence",
    "resourceIds",
    "resultIds",
    "resultResourceIds",
  ])("rejects invalid workflow %s", (key) => {
    for (const bad of [undefined, null, {}, [null]])
      expect(() => assertWorkflow({ ...workflow(), [key]: bad })).toThrow(
        ResponseFormatError,
      );
  });

  it("rejects an invalid model decision but accepts null for human review", () => {
    const saved = workflow();
    const invalidDecisions = ["approve", {}, { findings: null }];
    for (const decision of invalidDecisions) {
      const steps = [{ ...saved.steps[0], decision }];
      expect(() => assertWorkflow({ ...saved, steps })).toThrow(
        ResponseFormatError,
      );
    }
    expect(() => assertWorkflow(saved)).not.toThrow();
  });

  it("checks pagination and workflow summary items", () => {
    const page = {
      items: [workflow()],
      total: 1,
      offset: 0,
      limit: 30,
      hasMore: false,
    };
    expect(() => assertWorkflowSummaryList(page)).not.toThrow();
    expect(() => assertWorkflowSummaryList({ ...page, items: [null] })).toThrow(
      ResponseFormatError,
    );
    expect(() =>
      assertWorkflowSummaryList({ ...page, hasMore: undefined }),
    ).toThrow(ResponseFormatError);
  });

  it("rejects broken background compute snapshots without replacing successful ones", () => {
    const task = liveComputeTask("succeeded");
    const snapshot = {
      items: [
        { task, autoImport: false, trackingStatus: "succeeded", detail: "" },
      ],
    };
    expect(() => assertAgentComputeTasks(snapshot)).not.toThrow();
    expect(() =>
      assertAgentComputeTasks({
        items: [{ ...snapshot.items[0], task: { ...task, outputs: null } }],
      }),
    ).toThrow(ResponseFormatError);
    expect(() => assertAgentComputeTasks({ items: [null] })).toThrow(
      ResponseFormatError,
    );
    expect(() => assertAgentComputeTasks({})).toThrow(ResponseFormatError);
  });

  it("rejects broken resource entries while preserving real empty resources", () => {
    expect(() => assertAgentResources({ items: [] })).not.toThrow();
    expect(() =>
      assertAgentResources({
        items: [{ id: 1, name: "地图", dataType: "vector", description: "" }],
      }),
    ).not.toThrow();
    expect(() => assertAgentResources({ items: [null] })).toThrow(
      ResponseFormatError,
    );
    expect(() => assertAgentResources({ items: null })).toThrow(
      ResponseFormatError,
    );
  });
});
