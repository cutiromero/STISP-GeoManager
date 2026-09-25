import type { User } from "../types";

export function canReadHelp(id: string, user: User | null): boolean {
  const p = user?.permissions;
  switch (id) {
    case "admin-management":
      return !!p?.canAccessAdmin;
    case "permission-audit":
      return !!p?.canManageAuth;
    case "backup-security":
      return !!p?.canManageDataBackup;
    case "data-inventory":
      return !!p?.canChangeDataResources;
    case "data-import":
    case "data-standards":
      return !!p?.canUploadData;
    case "project-topic":
      return !!p?.canCreateWorkspaces;
    case "spatial-query":
    case "attribute-layer":
      return !!p?.canQueryData;
    default:
      return true;
  }
}

export function downloadHelp(text: string, english: boolean) {
  const url = URL.createObjectURL(
    new Blob([text], { type: "text/markdown;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = english ? "my-platform-guide.md" : "我的平台使用指南.md";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
