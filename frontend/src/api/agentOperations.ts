import { requestJson } from "./client";
import type {
  AgentOperation,
  AgentOperationDecision,
  AgentOperationList,
  AgentCapabilityCatalog,
  AgentToolCallList,
} from "./generated/types.gen";

const statuses = new Set([
  "pending",
  "executing",
  "confirmed",
  "rejected",
  "expired",
  "failed",
  "interrupted",
]);
const uuid = /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i;
const object = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === "object" && !Array.isArray(v);
const integer = (v: unknown): v is number =>
  Number.isSafeInteger(v) && Number(v) > 0;
function invalid(): never {
  throw new Error("平台操作响应无效，请刷新后重试");
}

export function assertOperation(
  value: unknown,
  projectId: number,
  runId?: number,
): asserts value is AgentOperation {
  if (
    !object(value) ||
    typeof value.id !== "string" ||
    !uuid.test(value.id) ||
    value.projectId !== projectId ||
    !integer(value.runId) ||
    (runId !== undefined && value.runId !== runId) ||
    !["import", "publish", "share"].includes(String(value.kind)) ||
    !statuses.has(String(value.status)) ||
    typeof value.digest !== "string" ||
    !/^[a-f\d]{64}$/.test(value.digest) ||
    !object(value.preview) ||
    value.preview.projectId !== projectId ||
    !object(value.result) ||
    typeof value.canConfirm !== "boolean" ||
    typeof value.detail !== "string" ||
    ![value.createdAt, value.expiresAt].every(
      (v) => typeof v === "string" && Number.isFinite(Date.parse(v)),
    ) ||
    !(
      value.decidedAt === null ||
      (typeof value.decidedAt === "string" &&
        Number.isFinite(Date.parse(value.decidedAt)))
    )
  )
    invalid();
  for (const key of ["title", "target", "scope", "effect"])
    if (typeof value.preview[key] !== "string") invalid();
  if (
    !Array.isArray(value.preview.details) ||
    value.preview.details.length > 20 ||
    value.preview.details.some((v) => typeof v !== "string")
  )
    invalid();
  if (value.canConfirm && value.status !== "pending") invalid();
}

export const agentOperationsApi = {
  list: (runId: number, projectId: number, signal?: AbortSignal) =>
    requestJson<AgentOperationList>(`/api/agent/runs/${runId}/operations/`, {
      projectTagId: String(projectId),
      signal,
      validate: (value) => {
        if (
          !object(value) ||
          value.runId !== runId ||
          value.projectId !== projectId ||
          !Array.isArray(value.items) ||
          value.items.length > 8
        )
          invalid();
        value.items.forEach((item) => assertOperation(item, projectId, runId));
      },
    }),
  decide: (
    operation: AgentOperation,
    decision: AgentOperationDecision["decision"],
    projectId: number,
    signal?: AbortSignal,
  ) =>
    requestJson<AgentOperation>(`/api/agent/operations/${operation.id}/`, {
      method: "POST",
      projectTagId: String(projectId),
      signal,
      body: {
        decision,
        digest: operation.digest,
      } satisfies AgentOperationDecision,
      validate: (value) => {
        assertOperation(value, projectId, operation.runId);
        if (value.id !== operation.id) invalid();
      },
    }),
  capabilities: (projectId: number, signal?: AbortSignal) =>
    requestJson<AgentCapabilityCatalog>("/api/agent/capabilities/", {
      projectTagId: String(projectId),
      signal,
      validate: (value) => {
        if (
          !object(value) ||
          value.projectId !== projectId ||
          value.schemaVersion !== 1 ||
          !Array.isArray(value.items) ||
          value.items.some(
            (item) =>
              !object(item) ||
              typeof item.name !== "string" ||
              typeof item.description !== "string" ||
              !object(item.inputSchema) ||
              typeof item.completion !== "string",
          )
        )
          invalid();
      },
    }),
  calls: (runId: number, projectId: number, offset = 0, signal?: AbortSignal) =>
    requestJson<AgentToolCallList>(
      `/api/agent/runs/${runId}/tool-calls/?offset=${offset}&limit=30`,
      {
        projectTagId: String(projectId),
        signal,
        validate: (value) => {
          if (
            !object(value) ||
            value.runId !== runId ||
            value.projectId !== projectId ||
            !Array.isArray(value.items) ||
            !Number.isSafeInteger(value.total) ||
            Number(value.total) < 0 ||
            !(
              value.nextOffset === null ||
              (Number.isSafeInteger(value.nextOffset) &&
                Number(value.nextOffset) > offset)
            ) ||
            value.items.some(
              (item) =>
                !object(item) ||
                typeof item.id !== "string" ||
                typeof item.tool !== "string" ||
                !["running", "succeeded", "failed"].includes(
                  String(item.status),
                ) ||
                !object(item.resultRefs) ||
                !object(item.error),
            )
          )
            invalid();
        },
      },
    ),
};
