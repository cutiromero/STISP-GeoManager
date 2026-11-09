import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import type { Map as MapboxMap } from "mapbox-gl";
import { createEmptyLayerGroup } from "../utils/layerFactory";
import { cloneDefaultVectorSymbolization } from "../symbolization";
import type {
  LoadedLayerGroup,
  LoadedVectorLayer,
  ResourceQueryResult,
} from "../types";
import { useViewportVectorLayers } from "./useViewportVectorLayers";
import { api } from "../api/client";
const realResourceProfile = api.resourceProfile;
const mocks = {
  queryResource: vi.spyOn(api, "queryResource"),
  resourceProfile: vi.spyOn(api, "resourceProfile"),
};
afterEach(() => {
  cleanup();
  mocks.queryResource.mockReset();
  mocks.resourceProfile.mockReset();
  vi.unstubAllGlobals();
});

function fixture() {
  const group = createEmptyLayerGroup("大点图层");
  const layer: LoadedVectorLayer = {
    id: "points",
    name: "points",
    layerType: "vector",
    visible: true,
    geometryType: "Point",
    summary: "",
    metadata: {},
    fields: [],
    sourceResource: {
      ...group.sourceResource,
      id: 7,
      itemCount: 39953,
      sizeBytes: 10000000,
    },
    symbolization: cloneDefaultVectorSymbolization(),
    geojson: { type: "FeatureCollection", features: [] },
  };
  group.children = [layer];
  return group;
}
function result(x: number | null): ResourceQueryResult {
  return {
    resourceId: 7,
    resourceName: "points",
    totalCount: x === null ? 0 : 1,
    returnedCount: x === null ? 0 : 1,
    limit: 1500,
    limitExceeded: false,
    bounds: [],
    elapsedMs: 1,
    fields: [],
    warnings: [],
    geojson: {
      type: "FeatureCollection",
      features:
        x === null
          ? []
          : [
              {
                type: "Feature",
                id: x,
                properties: {},
                geometry: { type: "Point", coordinates: [x, 40] },
              },
            ],
    },
  };
}
class Camera {
  box = [85, 40, 90, 45];
  events = new Map<string, Set<() => void>>();
  on(e: string, f: () => void) {
    if (!this.events.has(e)) this.events.set(e, new Set());
    this.events.get(e)!.add(f);
  }
  off(e: string, f: () => void) {
    this.events.get(e)?.delete(f);
  }
  getBounds() {
    const [w, s, e, n] = this.box;
    return {
      getWest: () => w,
      getSouth: () => s,
      getEast: () => e,
      getNorth: () => n,
    };
  }
  isMoving() {
    return false;
  }
  emit(e: string) {
    this.events.get(e)?.forEach((f) => f());
  }
  move(box: number[]) {
    this.emit("movestart");
    this.box = box;
    this.emit("moveend");
  }
}
function harness(
  camera: Camera,
  initial = fixture(),
  resolveTilePreviews = false,
) {
  const onError = vi.fn();
  const hook = renderHook(
    ({ scope }) => {
      const [groups, setGroups] = useState<LoadedLayerGroup[]>([initial]);
      useViewportVectorLayers({
        resolveTilePreviews,
        map: camera as unknown as MapboxMap,
        scope,
        enabled: true,
        groups,
        limit: 10000,
        onError,
        updateLayer: (gid, lid, update) =>
          setGroups((g) =>
            g.map((group) =>
              group.id === gid
                ? {
                    ...group,
                    children: group.children.map((l) =>
                      l.id === lid ? update(l) : l,
                    ),
                  }
                : group,
            ),
          ),
      });
      return groups;
    },
    { initialProps: { scope: "user:1:project:2" } },
  );
  return { ...hook, onError };
}
describe("view-bound vector loading", () => {
  it("upgrades an existing layer once and moves without querying large GeoJSON", async () => {
    const camera = new Camera();
    const preview = {
      revision: "0".repeat(24),
      tileUrl: "/api/tile/{z}/{x}/{y}.pbf",
      sourceLayer: "features" as const,
      minZoom: 0 as const,
      maxZoom: 10 as const,
      bounds: [80, 10, 110, 50],
      clustered: true,
      featureCount: 39953,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ vectorTiles: preview }), {
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );
    // Exercise real descriptor verification instead of returning an untagged stub.
    mocks.resourceProfile.mockImplementation((...args) =>
      realResourceProfile(...args),
    );
    const h = harness(camera, fixture(), true);
    await waitFor(() =>
      expect(
        (h.result.current[0]!.children[0] as LoadedVectorLayer).vectorTiles
          ?.revision,
      ).toBe(preview.revision),
    );
    expect(mocks.queryResource).not.toHaveBeenCalled();
    const initialKey = h.result.current[0]!.children[0]!.metadata.视野查询键;
    act(() => camera.move([92, 17, 105, 30]));
    await waitFor(() =>
      expect(h.result.current[0]!.children[0]!.metadata.视野查询键).not.toBe(
        initialKey,
      ),
    );
    expect(mocks.resourceProfile).toHaveBeenCalledTimes(1);
    expect(mocks.queryResource).not.toHaveBeenCalled();
    h.unmount();
  });

  it("ignores a prepared profile that arrives after the project scope changes", async () => {
    let resolveProfile: (profile: never) => void = () => {};
    mocks.resourceProfile.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveProfile = resolve;
        }),
    );
    const h = harness(new Camera(), fixture(), true);
    await waitFor(() => expect(mocks.resourceProfile).toHaveBeenCalledTimes(1));
    h.unmount();
    await act(async () =>
      resolveProfile({ vectorTiles: { revision: "late" } } as never),
    );
    expect(mocks.queryResource).not.toHaveBeenCalled();
    expect(h.onError).not.toHaveBeenCalled();
  });
  it("prioritizes two pipelines and caps concurrent viewport requests at two", async () => {
    const camera = new Camera();
    const group = fixture();
    const points = group.children[0] as LoadedVectorLayer;
    group.children = [
      points,
      ...[8, 9].map((id) => ({
        ...points,
        id: `line-${id}`,
        geometryType: "MultiLineString",
        sourceResource: { ...points.sourceResource, id },
      })),
    ];
    const pending: ((value: ResourceQueryResult) => void)[] = [];
    mocks.queryResource.mockImplementation(
      () => new Promise((resolve) => pending.push(resolve)),
    );
    const h = harness(camera, group);
    await waitFor(() => expect(mocks.queryResource).toHaveBeenCalledTimes(2));
    expect(
      mocks.queryResource.mock.calls.slice(0, 2).map((call) => call[0].id),
    ).toEqual([8, 9]);
    await act(async () => pending[0]!(result(86)));
    await waitFor(() => expect(mocks.queryResource).toHaveBeenCalledTimes(3));
    expect(mocks.queryResource.mock.calls[2]![0].id).toBe(7);
    h.unmount();
    expect(
      mocks.queryResource.mock.calls.every((call) => call[2]?.aborted),
    ).toBe(true);
    await act(async () => {
      pending[1]!(result(87));
      pending[2]!(result(88));
    });
    expect(h.onError).not.toHaveBeenCalled();
  });
  it("debounces moving, replaces empty views, and reuses a recent region", async () => {
    const camera = new Camera();
    mocks.queryResource
      .mockResolvedValueOnce(result(86))
      .mockResolvedValueOnce(result(null));
    const h = harness(camera);
    await waitFor(() => {
      expect(h.onError.mock.calls).toEqual([]);
      expect(camera.events.size).toBe(2);
      expect(mocks.queryResource).toHaveBeenCalledTimes(1);
    });
    await waitFor(() =>
      expect(
        (h.result.current[0]!.children[0] as LoadedVectorLayer).geojson
          .features,
      ).toHaveLength(1),
    );
    act(() => {
      camera.move([95, 20, 100, 25]);
      camera.move([100, 20, 105, 25]);
    });
    await waitFor(() => expect(mocks.queryResource).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        (h.result.current[0]!.children[0] as LoadedVectorLayer).geojson
          .features,
      ).toHaveLength(0),
    );
    act(() => camera.move([85, 40, 90, 45]));
    await new Promise((r) => setTimeout(r, 450));
    expect(mocks.queryResource).toHaveBeenCalledTimes(2);
    expect(
      (h.result.current[0]!.children[0] as LoadedVectorLayer).geojson.features,
    ).toHaveLength(1);
    expect(h.onError).not.toHaveBeenCalled();
  });
  it("aborts and discards stale responses after moving to a new view", async () => {
    let finish!: (r: ResourceQueryResult) => void;
    const camera = new Camera();
    mocks.queryResource
      .mockImplementationOnce(
        () =>
          new Promise<ResourceQueryResult>((r) => {
            finish = r;
          }),
      )
      .mockResolvedValueOnce(result(100));
    const h = harness(camera);
    await waitFor(() => {
      expect(h.onError.mock.calls).toEqual([]);
      expect(camera.events.size).toBe(2);
      expect(mocks.queryResource).toHaveBeenCalledTimes(1);
    });
    const signal = mocks.queryResource.mock.calls[0]![2] as AbortSignal;
    act(() => camera.move([95, 20, 105, 30]));
    expect(signal.aborted).toBe(true);
    await waitFor(() =>
      expect(
        (h.result.current[0]!.children[0] as LoadedVectorLayer).geojson
          .features[0]?.id,
      ).toBe(100),
    );
    await act(async () => finish(result(86)));
    expect(
      (h.result.current[0]!.children[0] as LoadedVectorLayer).geojson
        .features[0]?.id,
    ).toBe(100);
  });
  it("cancels prior project requests and never refreshes explicit query results", async () => {
    let finish!: (r: ResourceQueryResult) => void;
    const camera = new Camera();
    mocks.queryResource
      .mockImplementationOnce(
        () =>
          new Promise<ResourceQueryResult>((r) => {
            finish = r;
          }),
      )
      .mockResolvedValueOnce(result(100));
    const h = harness(camera);
    await waitFor(() => {
      expect(h.onError.mock.calls).toEqual([]);
      expect(camera.events.size).toBe(2);
      expect(mocks.queryResource).toHaveBeenCalledTimes(1);
    });
    h.rerender({ scope: "user:1:project:3" });
    await waitFor(() => expect(mocks.queryResource).toHaveBeenCalledTimes(2));
    await act(async () => finish(result(86)));
    expect(
      (h.result.current[0]!.children[0] as LoadedVectorLayer).geojson
        .features[0]?.id,
    ).toBe(100);
    h.unmount();
    const explicit = fixture();
    (explicit.children[0] as LoadedVectorLayer).query = {
      attributeFilters: [
        { id: "a", field: "year", operator: "eq", value: "2000" },
      ],
      spatialFilter: null,
    };
    mocks.queryResource.mockClear();
    harness(new Camera(), explicit);
    await new Promise((r) => setTimeout(r, 450));
    expect(mocks.queryResource).not.toHaveBeenCalled();
  });
});
