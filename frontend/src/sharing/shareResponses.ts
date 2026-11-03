import type {
  ComputePreview,
  ShareCheckResponse,
  ShareInvitation,
  ShareInvitationList,
  ShareOpenResponse,
  SharePerson,
  ShareTarget,
} from "../api/generated/types.gen";

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function integer(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}
function person(value: unknown): value is SharePerson {
  return (
    object(value) &&
    typeof value.username === "string" &&
    typeof value.displayName === "string"
  );
}
function target(value: unknown): value is ShareTarget {
  return (
    object(value) &&
    ["workspace", "composition", "compute_output"].includes(
      String(value.kind),
    ) &&
    integer(value.objectId) &&
    value.objectId > 0 &&
    integer(value.projectTagId) &&
    value.projectTagId > 0 &&
    [value.name, value.projectName, value.openUrl].every(
      (item) => typeof item === "string",
    )
  );
}
function invitation(value: unknown): value is ShareInvitation {
  return (
    object(value) &&
    integer(value.id) &&
    value.id > 0 &&
    ["pending", "accepted", "rejected", "unavailable"].includes(
      String(value.status),
    ) &&
    person(value.sender) &&
    person(value.recipient) &&
    target(value.target) &&
    typeof value.createdAt === "string" &&
    (value.respondedAt === null || typeof value.respondedAt === "string") &&
    typeof value.unread === "boolean" &&
    typeof value.detail === "string" &&
    typeof value.canRespond === "boolean"
  );
}
function invalid(): never {
  throw new Error("分享服务返回内容不完整，请稍后重试");
}

export function parseShareList(value: unknown): ShareInvitationList {
  if (
    !object(value) ||
    !Array.isArray(value.items) ||
    !value.items.every(invitation) ||
    ![value.total, value.unreadCount, value.limit, value.offset].every(integer)
  )
    invalid();
  return value as ShareInvitationList;
}
export function parseShareInvitation(value: unknown): ShareInvitation {
  if (!invitation(value)) invalid();
  return value;
}
export function parseShareCheck(value: unknown): ShareCheckResponse {
  if (
    !object(value) ||
    typeof value.eligible !== "boolean" ||
    typeof value.detail !== "string" ||
    (value.eligible && (!target(value.target) || !person(value.recipient)))
  )
    invalid();
  return value as ShareCheckResponse;
}
export function parseShareOpen(value: unknown): ShareOpenResponse {
  if (!object(value) || !target(value.target)) invalid();
  if (value.output !== undefined) {
    const output = value.output;
    if (
      !object(output) ||
      !integer(output.id) ||
      !object(output.metadata) ||
      typeof output.expired !== "boolean" ||
      ![output.label, output.kind, output.fileName, output.downloadUrl].every(
        (item) => typeof item === "string",
      ) ||
      typeof output.sizeBytes !== "number"
    )
      invalid();
  }
  return value as ShareOpenResponse;
}

export function parseSharedPreview(value: unknown): ComputePreview {
  if (
    !object(value) ||
    typeof value.kind !== "string" ||
    !object(value.metadata) ||
    !Array.isArray(value.columns) ||
    !value.columns.every((column) => typeof column === "string") ||
    !Array.isArray(value.rows) ||
    !value.rows.every(Array.isArray)
  )
    invalid();
  return value as ComputePreview;
}
