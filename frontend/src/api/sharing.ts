import { requestJson } from "./client";
import {
  parseShareCheck,
  parseShareInvitation,
  parseShareList,
  parseShareOpen,
} from "../sharing/shareResponses";
import type {
  ShareCheckResponse,
  ShareInvitation,
  ShareInvitationList,
  ShareKind,
  ShareOpenResponse,
} from "./generated/types.gen";

export type {
  ShareInvitation,
  ShareKind,
  ShareTarget,
} from "./generated/types.gen";

export const sharingApi = {
  check: (kind: ShareKind, objectId: number, username: string) =>
    requestJson<ShareCheckResponse>("/api/sharing/check/", {
      method: "POST",
      body: { kind, objectId, username },
    }).then(parseShareCheck),
  invite: (
    kind: ShareKind,
    objectId: number,
    username: string,
    idempotencyKey: string,
  ) =>
    requestJson<ShareInvitation>("/api/sharing/invitations/", {
      method: "POST",
      body: { kind, objectId, username, idempotencyKey },
    }).then(parseShareInvitation),
  list: (box: "received" | "sent", offset = 0, limit = 20) =>
    requestJson<ShareInvitationList>(
      `/api/sharing/invitations/?${new URLSearchParams({ box, offset: String(offset), limit: String(limit) })}`,
    ).then(parseShareList),
  respond: (
    id: number,
    decision: "accept" | "reject",
    idempotencyKey: string,
  ) =>
    requestJson<ShareInvitation>(`/api/sharing/invitations/${id}/respond/`, {
      method: "POST",
      body: { decision, idempotencyKey },
    }).then(parseShareInvitation),
  read: (id: number) =>
    requestJson<ShareInvitation>(`/api/sharing/invitations/${id}/read/`, {
      method: "POST",
      body: {},
    }).then(parseShareInvitation),
  open: (id: number) =>
    requestJson<ShareOpenResponse>(`/api/sharing/invitations/${id}/open/`).then(
      parseShareOpen,
    ),
};
