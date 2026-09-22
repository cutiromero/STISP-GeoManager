import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  cloneDefaultGroupSymbolization,
  cloneDefaultRasterSymbolization,
  cloneDefaultVectorSymbolization,
} from "../symbolization";
import type {
  LoadedLayerGroup,
  LoadedRasterLayer,
  LoadedVectorLayer,
  ResourceListItem,
} from "../types";
import {
  readCachedLayerGroups,
  rememberCachedLayerGroups,
  writeCachedLayerGroups,
} from "../utils/layerWorkspaceStorage";
import { useLayerGroups } from "./useLayerGroups";

vi.mock("../utils/layerWorkspaceStorage", () => ({
  readCachedLayerGroups: vi.fn(),
  rememberCachedLayerGroups: vi.fn(),
  writeCachedLayerGroups: vi.fn(),
}));

const readCachedLayerGroupsMock = vi.mocked(readCachedLayerGroups);
const rememberCachedLayerGroupsMock = vi.mocked(rememberCachedLayerGroups);
const writeCachedLayerGroupsMock = vi.mocked(writeCachedLayerGroups);

describe("useLayerGroups", () => {
  beforeEach(() => {
    readCachedLayerGroupsMock.mockReset();
    rememberCachedLayerGroupsMock.mockReset();
    writeCachedLayerGroupsMock.mockReset();
    readCachedLayerGroupsMock.mockResolvedValue([]);
    writeCachedLayerGroupsMock.mockResolvedValue();
  });

  it("restores cached groups on startup", async () => {
    const cachedGroups = [makeGroup("cached")];
    readCachedLayerGroupsMock.mockResolvedValueOnce(cachedGroups);

    const { result } = renderHook(() => useLayerGroups());

    await waitFor(() => {
      expect(result.current.groups).toEqual(cachedGroups);
    });
  });

  it("persists group changes after startup cache hydration", async () => {
    const { result } = renderHook(() => useLayerGroups());

    await waitFor(() => {
      expect(readCachedLayerGroupsMock).toHaveBeenCalledWith("default");
    });
    expect(writeCachedLayerGroupsMock).not.toHaveBeenCalled();
    act(() => {
      result.current.addGroup(makeGroup("persisted"));
    });

    await waitFor(() => {
      expect(writeCachedLayerGroupsMock).toHaveBeenLastCalledWith("default", [
        expect.objectContaining({ id: "persisted" }),
      ]);
    });
  });

  it("uses the provided cache key for browser-local layer state", async () => {
    renderHook(() => useLayerGroups("user-7"));

    await waitFor(() => {
      expect(readCachedLayerGroupsMock).toHaveBeenCalledWith("user-7");
    });
    expect(writeCachedLayerGroupsMock).not.toHaveBeenCalled();
  });

  it("prepends new groups and updates group-level state", () => {
    const { result } = renderHook(() => useLayerGroups());

    act(() => {
      result.current.addGroup(makeGroup("first"));
      result.current.addGroup(makeGroup("second"));
    });
    act(() => {
      result.current.setGroupVisibility("first", false);
      result.current.setGroupName("first", "重命名图层组");
    });

    expect(result.current.groups.map((group) => group.id)).toEqual([
      "second",
      "first",
    ]);
    expect(result.current.groups[1].visible).toBe(false);
    expect(result.current.groups[1].name).toBe("重命名图层组");
  });

  it("updates only raster layers through updateRasterLayer", () => {
    const { result } = renderHook(() => useLayerGroups());
    const group = makeGroup("group", [
      makeVectorLayer("vector-layer"),
      makeRasterLayer("raster-layer"),
    ]);

    act(() => {
      result.current.addGroup(group);
    });
    act(() => {
      result.current.updateRasterLayer("group", "vector-layer", (layer) => ({
        ...layer,
        summary: "不应更新",
      }));
      result.current.updateRasterLayer("group", "raster-layer", (layer) => ({
        ...layer,
        renderStatus: "ready",
      }));
    });

    const [vectorLayer, rasterLayer] = result.current.groups[0].children;
    expect(vectorLayer.summary).toBe("vector-layer 摘要");
    expect(rasterLayer.layerType).toBe("raster");
    expect(rasterLayer.renderStatus).toBe("ready");
  });

  it("updates visibility only for the targeted vector or raster layer", () => {
    const { result } = renderHook(() => useLayerGroups());
    const group = makeGroup("group", [
      makeVectorLayer("vector-layer"),
      makeRasterLayer("raster-layer"),
    ]);

    act(() => {
      result.current.addGroup(group);
    });
    act(() => {
      result.current.setLayerVisibility("group", "vector-layer", false);
    });

    expect(result.current.groups[0].children[0].visible).toBe(false);
    expect(result.current.groups[0].children[1].visible).toBe(true);

    act(() => {
      result.current.setLayerVisibility("group", "raster-layer", false);
    });

    expect(result.current.groups[0].children[0].visible).toBe(false);
    expect(result.current.groups[0].children[1].visible).toBe(false);
  });

  it("removes empty groups when the last layer is removed", () => {
    const { result } = renderHook(() => useLayerGroups());

    act(() => {
      result.current.addGroup(
        makeGroup("group", [makeVectorLayer("only-layer")]),
      );
    });
    act(() => {
      result.current.removeLayer("group", "only-layer");
    });

    expect(result.current.groups).toEqual([]);
  });

  it("keeps manually created groups when their last layer is removed", () => {
    const { result } = renderHook(() => useLayerGroups());

    act(() => {
      result.current.addGroup({
        ...makeGroup("manual", [makeVectorLayer("only-layer")]),
        isManual: true,
      });
    });
    act(() => {
      result.current.removeLayer("manual", "only-layer");
    });

    expect(result.current.groups).toHaveLength(1);
    expect(result.current.groups[0].isManual).toBe(true);
    expect(result.current.groups[0].children).toEqual([]);
  });

  it("reorders groups around a target group", () => {
    const { result } = renderHook(() => useLayerGroups());

    act(() => {
      result.current.setGroups([
        makeGroup("a"),
        makeGroup("b"),
        makeGroup("c"),
      ]);
    });
    act(() => {
      result.current.reorderGroups("a", "c", "after");
    });

    expect(result.current.groups.map((group) => group.id)).toEqual([
      "b",
      "c",
      "a",
    ]);
  });

  it("moves layers within the same group", () => {
    const { result } = renderHook(() => useLayerGroups());

    act(() => {
      result.current.setGroups([
        makeGroup("group", [
          makeVectorLayer("layer-a"),
          makeVectorLayer("layer-b"),
          makeVectorLayer("layer-c"),
        ]),
      ]);
    });
    act(() => {
      result.current.moveLayer("group", "layer-a", "group", "layer-c", "after");
    });

    expect(result.current.groups[0].children.map((layer) => layer.id)).toEqual([
      "layer-b",
      "layer-c",
      "layer-a",
    ]);
  });

  it("moves layers across groups and removes emptied source groups", () => {
    const { result } = renderHook(() => useLayerGroups());

    act(() => {
      result.current.setGroups([
        makeGroup("source", [makeVectorLayer("moving")]),
        {
          ...makeGroup("target", [makeVectorLayer("target-layer")]),
          isManual: true,
        },
      ]);
    });
    act(() => {
      result.current.moveLayer(
        "source",
        "moving",
        "target",
        "target-layer",
        "before",
      );
    });

    expect(result.current.groups.map((group) => group.id)).toEqual(["target"]);
    expect(result.current.groups[0].children.map((layer) => layer.id)).toEqual([
      "moving",
      "target-layer",
    ]);
  });

  it("moves layers into manually created empty groups", () => {
    const { result } = renderHook(() => useLayerGroups());

    act(() => {
      result.current.setGroups([
        makeGroup("source", [makeVectorLayer("moving")]),
        { ...makeGroup("manual", []), isManual: true },
      ]);
    });
    act(() => {
      result.current.moveLayer("source", "moving", "manual", null, "inside");
    });

    expect(result.current.groups.map((group) => group.id)).toEqual(["manual"]);
    expect(result.current.groups[0].children.map((layer) => layer.id)).toEqual([
      "moving",
    ]);
  });
});

function makeGroup(
  id: string,
  children: LoadedLayerGroup["children"] = [makeVectorLayer(`${id}-layer`)],
): LoadedLayerGroup {
  return {
    id,
    name: `${id} 组`,
    sourceResource: sourceResource(),
    visible: true,
    summary: `${id} 摘要`,
    createdAt: "2026-06-06T00:00:00.000Z",
    metadata: {},
    symbolization: cloneDefaultGroupSymbolization(),
    children,
  };
}

function makeVectorLayer(id: string): LoadedVectorLayer {
  return {
    id,
    name: id,
    layerType: "vector",
    sourceResource: sourceResource(),
    geojson: { type: "FeatureCollection", features: [] },
    geometryType: "Point",
    visible: true,
    summary: `${id} 摘要`,
    metadata: {},
    symbolization: cloneDefaultVectorSymbolization(),
    fields: [],
  };
}

function makeRasterLayer(id: string): LoadedRasterLayer {
  return {
    id,
    name: id,
    layerType: "raster",
    sourceResource: sourceResource() as LoadedRasterLayer["sourceResource"],
    geometryType: "Raster",
    visible: true,
    summary: `${id} 摘要`,
    metadata: {},
    symbolization: cloneDefaultRasterSymbolization(),
    fields: [],
  };
}

function sourceResource(): ResourceListItem {
  return {
    id: 1,
    name: "测试资源",
    dataType: "vector",
  } as ResourceListItem;
}
