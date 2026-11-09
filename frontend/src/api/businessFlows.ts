import { requestJson } from "./client";
import { ResponseFormatError } from "./responseDiagnostics";
import type {
  BusinessFlowCreate,
  BusinessFlowDecision,
  BusinessFlowDetail,
  BusinessFlowList,
  BusinessFlowRun,
  BusinessFlowRunList,
  BusinessFlowStart,
  BusinessFlowUpdate,
  BusinessFlowVersionPublish,
} from "./generated/types.gen";

const invalid = (field: string): never => {
  throw new ResponseFormatError(
    `businessFlow.${field}`,
    "业务流返回内容不完整，请重试，当前任务不会重新启动。",
  );
};
const record = (value: unknown, field: string): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return invalid(field);
  return value as Record<string, unknown>;
};
const texts = (value: unknown) =>
  Array.isArray(value) && value.every((item) => typeof item === "string");
function assertSpec(value: unknown) {
  const spec = record(value, "definition");
  if (
    spec.schemaVersion !== 1 ||
    !["geology_generic", "research_flow"].includes(String(spec.adapter)) ||
    !Array.isArray(spec.nodes) ||
    spec.nodes.length === 0 ||
    spec.nodes.length > 32 ||
    !Array.isArray(spec.inputRequirements) ||
    !texts(spec.outputRequirements)
  )
    invalid("definition");
  for (const raw of spec.nodes as unknown[]) {
    const node = record(raw, "node"),
      review = record(node.review, "review");
    if (
      typeof node.id !== "string" ||
      typeof node.title !== "string" ||
      typeof node.description !== "string" ||
      typeof node.instruction !== "string" ||
      !["agent", "operator", "human", "result"].includes(String(node.kind)) ||
      !texts(node.dependsOn) ||
      !texts(node.dataRoles) ||
      typeof review.ai !== "boolean" ||
      typeof review.human !== "boolean" ||
      !Number.isSafeInteger(review.maxRevisions)
    )
      invalid("node");
    if (node.inputBindings !== undefined) {
      const bindings = record(node.inputBindings, "inputBindings");
      for (const value of Object.values(bindings)) {
        const item = record(value, "inputBinding");
        if (
          !(
            typeof item.role === "string" ||
            (typeof item.nodeId === "string" &&
              typeof item.outputKey === "string")
          )
        )
          invalid("inputBinding");
      }
    }
  }
  for (const raw of spec.inputRequirements as unknown[]) {
    const input = record(raw, "input");
    if (
      typeof input.key !== "string" ||
      typeof input.label !== "string" ||
      typeof input.description !== "string" ||
      typeof input.required !== "boolean" ||
      !texts(input.dataTypes) ||
      !texts(input.requiredFields)
    )
      invalid("input");
  }
}
function assertDetail(value: unknown) {
  const detail = record(value, "detail"),
    flow = record(detail.flow, "flow");
  if (
    !Number.isSafeInteger(flow.id) ||
    typeof flow.name !== "string" ||
    typeof flow.description !== "string" ||
    !Array.isArray(detail.versions) ||
    typeof detail.canManage !== "boolean"
  )
    invalid("detail");
  if (detail.version != null)
    assertSpec(record(detail.version, "version").definition);
  for (const version of detail.versions as unknown[])
    assertSpec(record(version, "version").definition);
}
function assertList(value: unknown) {
  const list = record(value, "list");
  if (
    !Array.isArray(list.items) ||
    list.items.length > 50 ||
    typeof list.canManage !== "boolean" ||
    (list.nextOffset !== undefined &&
      (!Number.isSafeInteger(list.nextOffset) || Number(list.nextOffset) <= 0))
  )
    invalid("list");
  for (const raw of list.items as unknown[]) {
    const item = record(raw, "item");
    if (
      !Number.isSafeInteger(item.id) ||
      typeof item.code !== "string" ||
      typeof item.name !== "string" ||
      typeof item.description !== "string" ||
      typeof item.isActive !== "boolean"
    )
      invalid("item");
  }
}
export function assertBusinessFlowRun(value: unknown) {
  const run = record(value, "run");
  if (
    typeof run.id !== "string" ||
    typeof run.status !== "string" ||
    !Array.isArray(run.nodes) ||
    !Array.isArray(run.events) ||
    !Number.isSafeInteger(run.revision)
  )
    invalid("run");
  assertSpec(run.definitionSnapshot);
  if (
    (run.nodes as unknown[]).length > 32 ||
    (run.events as unknown[]).length > 120 ||
    typeof run.name !== "string" ||
    typeof run.goal !== "string" ||
    typeof run.currentNode !== "string" ||
    !Number.isSafeInteger(run.projectId)
  )
    invalid("run");
  for (const raw of run.events as unknown[]) {
    const event = record(raw, "event");
    if (
      !Number.isSafeInteger(event.id) ||
      typeof event.nodeId !== "string" ||
      typeof event.kind !== "string" ||
      typeof event.status !== "string" ||
      typeof event.message !== "string" ||
      typeof event.createdAt !== "string" ||
      !["executor", "reviewer", "human", "system"].includes(String(event.actor))
    )
      invalid("event");
  }
  for (const raw of run.nodes as unknown[]) {
    const node = record(raw, "nodeState"),
      human = record(node.human, "human");
    if (
      typeof node.nodeId !== "string" ||
      typeof node.status !== "string" ||
      !Number.isSafeInteger(node.attempt) ||
      typeof human.required !== "boolean" ||
      typeof human.status !== "string" ||
      typeof human.reason !== "string"
    )
      invalid("nodeState");
    record(node.outputs, "outputs");
    for (const actor of ["executor", "reviewer"]) {
      const value = record(node[actor], actor);
      if (typeof value.status !== "string") invalid(actor);
      for (const key of [
        "model",
        "answer",
        "summary",
        "reason",
        "feedback",
        "thinking",
        "decision",
      ]) {
        if (value[key] !== undefined && typeof value[key] !== "string")
          invalid(actor + "." + key);
      }
    }
  }
}
export const businessFlowsApi = {
  list: (
    options: {
      signal?: AbortSignal;
      q?: string;
      offset?: number;
      limit?: number;
    } = {},
  ) => {
    const { signal, q = "", offset = 0, limit = 50 } = options;
    const query = new URLSearchParams({
      q,
      offset: String(offset),
      limit: String(limit),
    });
    return requestJson<BusinessFlowList>(`/api/business-flows/?${query}`, {
      signal,
      validate: (value) => {
        assertList(value);
        const next = (value as BusinessFlowList).nextOffset;
        if (
          next !== undefined &&
          (next <= offset ||
            (value as BusinessFlowList).items.length !== limit ||
            next !== offset + limit)
        )
          invalid("list.nextOffset");
      },
    });
  },
  detail: (id: number, options: { signal?: AbortSignal } = {}) =>
    requestJson<BusinessFlowDetail>(`/api/business-flows/${id}/`, {
      ...options,
      validate: (value) => {
        assertDetail(value);
        if ((value as BusinessFlowDetail).flow.id !== id) invalid("flow.id");
      },
    }),
  create: (body: BusinessFlowCreate) =>
    requestJson<BusinessFlowDetail>("/api/business-flows/", {
      method: "POST",
      body,
      validate: assertDetail,
    }),
  update: (id: number, body: BusinessFlowUpdate) =>
    requestJson<BusinessFlowDetail>(`/api/business-flows/${id}/`, {
      method: "PATCH",
      body,
      validate: assertDetail,
    }),
  publish: (id: number, body: BusinessFlowVersionPublish) =>
    requestJson<BusinessFlowDetail>(`/api/business-flows/${id}/versions/`, {
      method: "POST",
      body,
      validate: assertDetail,
    }),
  start: (id: number, body: BusinessFlowStart) =>
    requestJson<BusinessFlowRun>(`/api/business-flows/${id}/start/`, {
      method: "POST",
      body,
      validate: assertBusinessFlowRun,
    }),
  runs: (options: { signal?: AbortSignal } = {}) =>
    requestJson<BusinessFlowRunList>("/api/business-flows/runs/", {
      ...options,
      validate: (value) => {
        if (!Array.isArray(record(value, "runs").items)) invalid("runs");
      },
    }),
  run: (id: string, options: { signal?: AbortSignal } = {}) =>
    requestJson<BusinessFlowRun>(
      `/api/business-flows/runs/${encodeURIComponent(id)}/`,
      { ...options, validate: assertBusinessFlowRun },
    ),
  decide: (id: string, body: BusinessFlowDecision) =>
    requestJson<BusinessFlowRun>(
      `/api/business-flows/runs/${encodeURIComponent(id)}/decide/`,
      { method: "POST", body, validate: assertBusinessFlowRun },
    ),
  cancel: (id: string) =>
    requestJson<BusinessFlowRun>(
      `/api/business-flows/runs/${encodeURIComponent(id)}/cancel/`,
      { method: "POST", validate: assertBusinessFlowRun },
    ),
  pause: (id: string) =>
    requestJson<BusinessFlowRun>(
      `/api/business-flows/runs/${encodeURIComponent(id)}/pause/`,
      { method: "POST", validate: assertBusinessFlowRun },
    ),
  resume: (id: string) =>
    requestJson<BusinessFlowRun>(
      `/api/business-flows/runs/${encodeURIComponent(id)}/resume/`,
      { method: "POST", validate: assertBusinessFlowRun },
    ),
};
