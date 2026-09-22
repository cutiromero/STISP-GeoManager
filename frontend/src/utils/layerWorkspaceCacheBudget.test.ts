import { describe, expect, it } from "vitest";
import type { LoadedLayerGroup } from "../types";
import { createLayerWorkspaceFingerprint } from "./layerWorkspaceCacheBudget";

describe("createLayerWorkspaceFingerprint", () => {
  it("returns a compact stable fingerprint for persistable workspaces", () => {
    const groups = [
      { id: "first", name: "胡杨", children: [] },
    ] as LoadedLayerGroup[];

    const first = createLayerWorkspaceFingerprint(groups, 1024);
    const second = createLayerWorkspaceFingerprint(groups, 1024);

    expect(first).toEqual(second);
    expect(first?.fingerprint.length).toBeLessThan(40);
    expect(first?.byteLength).toBeGreaterThan(0);
  });

  it("rejects an obviously oversized workspace before persistence", () => {
    const groups = [
      { id: "large", summary: "x".repeat(2048), children: [] },
    ] as LoadedLayerGroup[];

    expect(createLayerWorkspaceFingerprint(groups, 1024)).toBeNull();
  });

  it("counts non-ASCII strings using their UTF-8 byte size", () => {
    const groups = [
      { id: "中文", name: "胡杨", children: [] },
    ] as LoadedLayerGroup[];

    const result = createLayerWorkspaceFingerprint(groups, 1024);

    expect(result?.byteLength).toBe(
      new TextEncoder().encode(JSON.stringify(groups)).byteLength,
    );
  });
});
