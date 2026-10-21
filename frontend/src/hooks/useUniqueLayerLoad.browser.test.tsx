import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { LoadedLayerGroup } from "../types";
import { createEmptyLayerGroup } from "../utils/layerFactory";
import { resourceLayerKey } from "../utils/uniqueLoadedLayers";
import { useUniqueLayerLoad } from "./useUniqueLayerLoad";
import { cloneDefaultVectorSymbolization } from "../symbolization";

function group(): LoadedLayerGroup {
  const value = createEmptyLayerGroup("测试数据");
  value.children = [
    {
      id: "existing-layer",
      name: "已有数据",
      layerType: "vector",
      sourceResource: { ...value.sourceResource, id: 17 },
      geojson: { type: "FeatureCollection", features: [] },
      geometryType: "Polygon",
      visible: false,
      summary: "",
      metadata: {},
      fields: [],
      symbolization: cloneDefaultVectorSymbolization(),
    },
  ];
  return value;
}

describe("useUniqueLayerLoad", () => {
  it("shares a pending query/render operation between rapid loading requests", async () => {
    let finish!: (value: boolean) => void;
    const create = vi.fn(
      () =>
        new Promise<boolean>((resolve) => {
          finish = resolve;
        }),
    );
    const onLoading = vi.fn();
    const { result } = renderHook(() =>
      useUniqueLayerLoad({
        scope: "project-3",
        groups: [],
        onExisting: vi.fn(),
        onLoading,
      }),
    );
    let first!: Promise<boolean>;
    let second!: Promise<boolean>;
    await act(async () => {
      first = result.current.load("resource:17", create);
      second = result.current.load("resource:17", create);
      await Promise.resolve();
    });
    expect(create).toHaveBeenCalledOnce();
    expect(onLoading).toHaveBeenCalledOnce();
    finish(true);
    await expect(first).resolves.toBe(true);
    await expect(second).resolves.toBe(true);
  });

  it("selects an existing layer without querying or rendering it again", async () => {
    const existing = group();
    const create = vi.fn();
    const onExisting = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      useUniqueLayerLoad({
        scope: "project-3",
        groups: [existing],
        onExisting,
        onLoading: vi.fn(),
      }),
    );
    await expect(
      result.current.load(resourceLayerKey(existing.children[0]), create),
    ).resolves.toBe(true);
    expect(create).not.toHaveBeenCalled();
    expect(onExisting).toHaveBeenCalledWith(existing, existing.children[0]);
  });

  it("releases failed operations for a retry and removed layers for reloading", async () => {
    const existing = group();
    const create = vi.fn().mockResolvedValueOnce(false).mockResolvedValue(true);
    const onExisting = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(
      ({ groups }) =>
        useUniqueLayerLoad({
          scope: "project-3",
          groups,
          onExisting,
          onLoading: vi.fn(),
        }),
      { initialProps: { groups: [existing] } },
    );
    const key = resourceLayerKey(existing.children[0]);
    await result.current.load(key, create);
    rerender({ groups: [] });
    await expect(result.current.load(key, create)).resolves.toBe(false);
    await expect(result.current.load(key, create)).resolves.toBe(true);
    expect(create).toHaveBeenCalledTimes(2);
  });

  it("does not share pending operations across projects", async () => {
    const create = vi.fn().mockResolvedValue(true);
    const { result, rerender } = renderHook(
      ({ scope }) =>
        useUniqueLayerLoad({
          scope,
          groups: [],
          onExisting: vi.fn(),
          onLoading: vi.fn(),
        }),
      { initialProps: { scope: "project-3" } },
    );
    const first = result.current.load("resource:17", create);
    rerender({ scope: "project-4" });
    const second = result.current.load("resource:17", create);
    await Promise.all([first, second]);
    expect(create).toHaveBeenCalledTimes(2);
  });
});
