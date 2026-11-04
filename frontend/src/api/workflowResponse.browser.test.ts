import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { liveComputeTask } from "../agent/computeFlow.testFixtures";
import { agentApi } from "./agent";
import { computeApi } from "./compute";
import {
  RESPONSE_DIAGNOSTICS_KEY,
  ResponseFormatError,
} from "./responseDiagnostics";

const saved = () => ({
  id: "saved",
  projectId: 3,
  workflowType: "geology_map_review",
  goal: "Private goal",
  status: "succeeded",
  detail: "",
  currentStep: "finish",
  createdAt: "2026-11-04",
  updatedAt: "2026-11-04",
  planHash: "frozen",
  plan: {},
  parameters: {},
  resourceIds: [],
  resultIds: [],
  resultResourceIds: [],
  evidence: [],
  steps: [],
});

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function records() {
  return JSON.parse(sessionStorage.getItem(RESPONSE_DIAGNOSTICS_KEY) ?? "[]");
}

describe("algorithm and background task API guards", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    sessionStorage.removeItem(RESPONSE_DIAGNOSTICS_KEY);
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    sessionStorage.removeItem(RESPONSE_DIAGNOSTICS_KEY);
  });

  it("captures missing algorithm versions together with the real response metadata", async () => {
    const response = json({
      items: [
        { id: 1, name: "Private algorithm", identifier: "demo", enabled: true },
      ],
      total: 1,
    });
    Object.defineProperties(response, {
      url: {
        value: "https://example.test/api/compute/algorithms/?token=secret",
      },
      redirected: { value: true },
    });
    fetchMock.mockResolvedValue(response);
    await expect(computeApi.algorithms()).rejects.toBeInstanceOf(
      ResponseFormatError,
    );
    const record = records()[0];
    expect(record.issue).toBe("algorithms.items[0].versions: expected array");
    expect(record).toMatchObject({
      status: 200,
      redirected: true,
      contentType: "application/json",
      finalUrlAvailable: true,
    });
    expect(record.structure.fields.items.samples[0].fields).not.toHaveProperty(
      "versions",
    );
    expect(new URL(record.finalUrl).searchParams.get("token")).toBe(
      "[redacted]",
    );
    expect(JSON.stringify(record)).not.toContain("Private algorithm");
  });

  it("accepts completed tasks and rejects malformed nested output updates", async () => {
    const task = liveComputeTask("succeeded");
    fetchMock.mockResolvedValueOnce(json(task));
    expect(await computeApi.task(task.id)).toEqual(task);
    fetchMock.mockResolvedValueOnce(
      json({
        items: [
          {
            task: { ...task, outputs: null },
            autoImport: false,
            trackingStatus: "done",
            detail: "",
          },
        ],
      }),
    );
    await expect(agentApi.computeTasks(5)).rejects.toBeInstanceOf(
      ResponseFormatError,
    );
    expect(records()[0].issue).toBe(
      "computeTasks.items[0].task.outputs: expected array",
    );
  });

  it("verifies workflow identity and nested state before any update reaches rendering", async () => {
    fetchMock.mockResolvedValueOnce(json(saved()));
    expect(await agentApi.workflow("saved")).toEqual(saved());
    fetchMock.mockResolvedValueOnce(json({ ...saved(), id: "other" }));
    await expect(agentApi.workflow("saved")).rejects.toBeInstanceOf(
      ResponseFormatError,
    );
    expect(records()[0].issue).toBe("workflow.id: request mismatch");
    fetchMock.mockResolvedValueOnce(json({ ...saved(), plan: null }));
    await expect(agentApi.workflow("saved")).rejects.toBeInstanceOf(
      ResponseFormatError,
    );
    expect(records()[1].structure.fields.plan.type).toBe("null");
  });

  it("checks resources and history summaries rather than casting missing arrays", async () => {
    fetchMock.mockResolvedValueOnce(json({ items: null }));
    await expect(agentApi.resources()).rejects.toBeInstanceOf(
      ResponseFormatError,
    );
    fetchMock.mockResolvedValueOnce(
      json({ total: 0, offset: 0, limit: 30, hasMore: false }),
    );
    await expect(
      agentApi.workflowHistory({ workflowType: "geology_map_review" }),
    ).rejects.toBeInstanceOf(ResponseFormatError);
    expect(records()).toHaveLength(2);
  });

  it("keeps authorization failures separate from malformed success responses", async () => {
    fetchMock.mockResolvedValue(json({ detail: "已撤权" }, 403));
    await expect(agentApi.workflow("saved")).rejects.toMatchObject({
      status: 403,
    });
    expect(records()[0].issue).toBe("http:403");
  });
});
