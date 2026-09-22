import { beforeEach, describe, expect, it } from "vitest";
import type { LoadedLayerGroup } from "../types";
import {
  clearCachedLayerGroups,
  readCachedLayerGroups,
  rememberCachedLayerGroups,
} from "./layerWorkspaceStorage";

describe("layerWorkspaceStorage in-memory handoff", () => {
  beforeEach(async () => {
    await clearCachedLayerGroups();
  });

  it("restores every loaded layer immediately across page remounts", async () => {
    const groups = [
      { id: "first", children: [{ id: "layer-a" }] },
      { id: "second", children: [{ id: "layer-b" }] },
    ] as LoadedLayerGroup[];

    rememberCachedLayerGroups("user-7", groups);

    await expect(readCachedLayerGroups("user-7")).resolves.toEqual(groups);
  });

  it("keeps large runtime state available even when persistence is deferred", async () => {
    const largePayload = "x".repeat(8 * 1024 * 1024 + 1);
    const groups = [
      {
        id: "large",
        summary: largePayload,
        children: [{ id: "large-layer" }],
      },
    ] as LoadedLayerGroup[];

    rememberCachedLayerGroups("user-8", groups);

    const restored = await readCachedLayerGroups("user-8");
    expect(restored).toHaveLength(1);
    expect(restored[0].summary).toHaveLength(largePayload.length);
  });

  it("evicts the least recently used workspace after the entry budget", async () => {
    const group = (id: string) => [{ id, children: [] }] as LoadedLayerGroup[];
    rememberCachedLayerGroups("user-1", group("one"));
    rememberCachedLayerGroups("user-2", group("two"));
    rememberCachedLayerGroups("user-3", group("three"));

    await expect(readCachedLayerGroups("user-1")).resolves.toEqual(
      group("one"),
    );
    rememberCachedLayerGroups("user-4", group("four"));

    await expect(readCachedLayerGroups("user-2")).resolves.toEqual([]);
    await expect(readCachedLayerGroups("user-1")).resolves.toEqual(
      group("one"),
    );
  });
});
