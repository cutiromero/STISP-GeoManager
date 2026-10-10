import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import {
  mapUrlResourceIds,
  mapUrlResourceBounds,
  useMapUrlResources,
} from "./MapPage";
import type { LoadedLayer, ResourceListItem } from "../types";

const resources: ResourceListItem[] = [1, 2, 3].map((id) => ({
  id,
  name: `成果图层 ${id}`,
  code: `result-${id}`,
  dataType: id === 1 ? "raster" : "vector",
  category: null,
  source: "真实计算",
  provider: "科研组",
  dataDate: null,
  spatialExtent: "80,40,90,45",
  coordinateSystem: "EPSG:4326",
  fileFormat: "GeoPackage",
  description: "",
  qualityNote: "",
  sizeBytes: 100,
  itemCount: 2,
  status: "active",
  isQueryable: id !== 1,
  isRenderable: id === 1,
  updatedAt: "2026-10-10",
}));

function options(params = "resources=1,2&projectTagId=2") {
  return {
    params: new URLSearchParams(params),
    currentProject: "2",
    projects: [{ id: 1 }, { id: 2 }],
    chooseProject: vi.fn(),
    ready: true,
    loadingResources: false,
    resources,
    english: false,
    showExisting: vi.fn().mockResolvedValue(false),
    load: vi.fn().mockResolvedValue(true),
    onStart: vi.fn(),
  };
}

it("accepts multiple resource links and the old single-resource format without duplicates or invalid IDs", () => {
  expect(
    mapUrlResourceIds(
      new URLSearchParams("resources=1,2,1,-1,abc,0,9007199254740999"),
    ),
  ).toEqual([1, 2]);
  expect(mapUrlResourceIds(new URLSearchParams("resourceId=3"))).toEqual([3]);
  expect(mapUrlResourceIds(new URLSearchParams("computeOutputId=30"))).toEqual(
    [],
  );
});

it("loads multiple raster and vector resources once and makes existing layers visible", async () => {
  const setup = options();
  setup.showExisting.mockImplementation(async (id) => id === 2);
  const view = renderHook((value) => useMapUrlResources(value), {
    initialProps: setup,
  });
  await waitFor(() => expect(setup.showExisting).toHaveBeenCalledTimes(2));
  expect(setup.load).toHaveBeenCalledOnce();
  expect(setup.load).toHaveBeenCalledWith(resources[0]);
  view.rerender({ ...setup, resources: [...resources] });
  await act(async () => {
    await Promise.resolve();
  });
  expect(setup.load).toHaveBeenCalledOnce();
  expect(view.result.current.error).toBe("");
});

it("switches only to an authorized project through the existing confirmation flow before loading", async () => {
  const setup = { ...options(), currentProject: "1" };
  const view = renderHook((value) => useMapUrlResources(value), {
    initialProps: setup,
  });
  await waitFor(() => expect(setup.chooseProject).toHaveBeenCalledWith("2"));
  expect(setup.load).not.toHaveBeenCalled();
  expect(view.result.current.error).toContain("切换到成果所属项目");
  view.rerender({ ...setup, currentProject: "2" });
  await waitFor(() => expect(setup.load).toHaveBeenCalledTimes(2));
});

it("does not load or switch for an inaccessible project", async () => {
  const setup = options("resources=1,2&projectTagId=7");
  const view = renderHook(() => useMapUrlResources(setup));
  await waitFor(() =>
    expect(view.result.current.error).toContain("当前账号不能访问"),
  );
  expect(setup.chooseProject).not.toHaveBeenCalled();
  expect(setup.load).not.toHaveBeenCalled();
});

it("retries failed layers without resubmitting the layers already loaded successfully", async () => {
  const setup = options();
  setup.load
    .mockResolvedValueOnce(true)
    .mockResolvedValueOnce(false)
    .mockResolvedValue(true);
  const view = renderHook(() => useMapUrlResources(setup));
  await waitFor(() =>
    expect(view.result.current.error).toContain("成果图层 2"),
  );
  expect(setup.load).toHaveBeenCalledTimes(2);
  act(() => view.result.current.retry());
  await waitFor(() => expect(setup.load).toHaveBeenCalledTimes(3));
  expect(setup.load.mock.calls[2]?.[0]).toEqual(resources[1]);
  await waitFor(() => expect(view.result.current.error).toBe(""));
});

it("waits for resources and map readiness before treating an input as unavailable", async () => {
  const setup = options();
  const view = renderHook((value) => useMapUrlResources(value), {
    initialProps: { ...setup, ready: false, loadingResources: true },
  });
  expect(setup.load).not.toHaveBeenCalled();
  view.rerender({ ...setup, ready: true, loadingResources: false });
  await waitFor(() => expect(setup.load).toHaveBeenCalledTimes(2));
  expect(view.result.current.error).toBe("");
});

it("finishes an in-flight resource then starts the latest URL without overlapping loads", async () => {
  const setup = options();
  let complete!: (value: boolean) => void;
  setup.load.mockReturnValueOnce(
    new Promise<boolean>((resolve) => {
      complete = resolve;
    }),
  );
  const view = renderHook((value) => useMapUrlResources(value), {
    initialProps: setup,
  });
  await waitFor(() => expect(setup.load).toHaveBeenCalledOnce());
  view.rerender({
    ...setup,
    params: new URLSearchParams("resources=3&projectTagId=2"),
  });
  expect(setup.load).toHaveBeenCalledOnce();
  await act(async () => complete(true));
  await waitFor(() => expect(setup.load).toHaveBeenCalledTimes(2));
  expect(setup.load.mock.calls[1]?.[0]).toEqual(resources[2]);
});

it("merges the whole raster and vector extents after multiple successful loads and keeps single-layer positioning", async () => {
  const setup = options("resources=1,2,3&projectTagId=2");
  setup.load
    .mockResolvedValueOnce(true)
    .mockResolvedValueOnce(true)
    .mockResolvedValueOnce(false);
  const view = renderHook(() => useMapUrlResources(setup));
  await waitFor(() =>
    expect(view.result.current.loadedResourceIds).toEqual([1, 2]),
  );
  const layers = [
    {
      layerType: "raster",
      sourceResource: resources[0],
      imageCoordinates: [
        [80, 45],
        [90, 45],
        [90, 40],
        [80, 40],
      ],
    },
    {
      layerType: "vector",
      sourceResource: resources[1],
      geojson: {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: {},
            geometry: {
              type: "Polygon",
              coordinates: [
                [
                  [85, 42],
                  [95, 42],
                  [95, 48],
                  [85, 48],
                  [85, 42],
                ],
              ],
            },
          },
        ],
      },
    },
    {
      layerType: "raster",
      sourceResource: resources[2],
      imageCoordinates: [
        [0, 5],
        [5, 5],
        [5, 0],
        [0, 0],
      ],
    },
  ] as LoadedLayer[];
  expect(
    mapUrlResourceBounds(
      layers,
      view.result.current.loadedResourceIds,
    )?.toArray(),
  ).toEqual([
    [80, 40],
    [95, 48],
  ]);
  expect(mapUrlResourceBounds(layers, [1])).toBeNull();
  expect(mapUrlResourceBounds(layers.slice(0, 1), [1, 2])).toBeNull();
});
