export const workspaceInventoryChangedEvent =
  "huyang:workspace-inventory-changed";

type WorkspaceInventoryKind = "workspace" | "composition" | "result";

interface WorkspaceInventoryChangeDetail {
  kind: WorkspaceInventoryKind;
  at: number;
}

export function notifyWorkspaceInventoryChanged(kind: WorkspaceInventoryKind) {
  const detail: WorkspaceInventoryChangeDetail = { kind, at: Date.now() };
  window.dispatchEvent(
    new CustomEvent<WorkspaceInventoryChangeDetail>(
      workspaceInventoryChangedEvent,
      { detail },
    ),
  );
  try {
    window.localStorage.setItem(
      workspaceInventoryChangedEvent,
      JSON.stringify(detail),
    );
  } catch {
    // Local dispatch is enough when storage is unavailable.
  }
}

export function isWorkspaceInventoryChange(value: unknown) {
  return (
    typeof value === "object" &&
    value !== null &&
    "kind" in value &&
    ((value as WorkspaceInventoryChangeDetail).kind === "workspace" ||
      (value as WorkspaceInventoryChangeDetail).kind === "composition" ||
      (value as WorkspaceInventoryChangeDetail).kind === "result")
  );
}
