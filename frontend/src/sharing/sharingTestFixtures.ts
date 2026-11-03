import type {
  ComputeOutput,
  ShareCheckResponse,
  ShareInvitation,
  ShareInvitationList,
  ShareTarget,
} from "../api/generated/types.gen";

export function shareTarget(overrides: Partial<ShareTarget> = {}): ShareTarget {
  return {
    kind: "workspace",
    objectId: 17,
    name: "地质成果工程",
    projectTagId: 1,
    projectName: "逻辑推理",
    openUrl: "/map?sceneId=17",
    ...overrides,
  };
}

export function shareInvitation(
  overrides: Partial<ShareInvitation> = {},
): ShareInvitation {
  return {
    id: 23,
    status: "pending",
    sender: { username: "owner", displayName: "项目用户" },
    recipient: { username: "researcher", displayName: "科研用户" },
    target: shareTarget(),
    createdAt: "2026-11-03T09:00:00+08:00",
    respondedAt: null,
    unread: true,
    detail: "请确认是否接受本次分享。",
    canRespond: true,
    ...overrides,
  };
}

export function shareList(items: ShareInvitation[] = []): ShareInvitationList {
  return {
    items,
    total: items.length,
    unreadCount: items.filter((item) => item.unread).length,
    offset: 0,
    limit: 12,
  };
}

export function shareCheck(username = "researcher"): ShareCheckResponse {
  return {
    eligible: true,
    detail: "接收方可以查看该项目和分享对象。",
    recipient: { username, displayName: "科研用户" },
    target: shareTarget(),
  };
}

export function sharedOutput(
  overrides: Partial<ComputeOutput> = {},
): ComputeOutput {
  return {
    id: 71,
    key: "report",
    label: "检查报告",
    kind: "report",
    fileName: "检查报告.md",
    sizeBytes: 2048,
    checksum: "abc",
    metadata: { format: "markdown" },
    expired: false,
    importStatus: "none",
    resourceId: null,
    importError: "",
    downloadUrl: "/api/compute/outputs/71/download/",
    previewUrl: "/api/compute/outputs/71/preview/",
    ...overrides,
  };
}
