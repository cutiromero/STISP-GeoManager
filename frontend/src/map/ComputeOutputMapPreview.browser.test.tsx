import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App as AntApp } from "antd";
import type { Map as MapboxMap } from "mapbox-gl";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { computeApi } from "../api/compute";
import type { ComputeMapPreview } from "../api/generated/types.gen";
import {
  projectTransformRequest,
  resetProjectSession,
} from "../projects/session";
import ComputeOutputMapPreview from "./ComputeOutputMapPreview";

const preview: ComputeMapPreview = {
  name: "研究区影像 · NDVI",
  kind: "raster",
  metadata: { width: 259, height: 260 },
  temporary: true,
  imageUrl: "/api/compute/outputs/30/map-preview/image/?projectTagId=1",
  imageCoordinates: [
    [88.36, 40.15],
    [88.37, 40.15],
    [88.37, 40.14],
    [88.36, 40.14],
  ],
};
function mapMock() {
  const sources = new Map<string, unknown>();
  const layers = new Map<string, unknown>();
  const events = new Map<string, () => void>();
  const value = {
    isStyleLoaded: vi.fn(() => true),
    getSource: vi.fn((name: string) => sources.get(name)),
    getLayer: vi.fn((name: string) => layers.get(name)),
    addSource: vi.fn((name: string, data: unknown) => sources.set(name, data)),
    addLayer: vi.fn((layer: { id: string }) => layers.set(layer.id, layer)),
    removeSource: vi.fn((name: string) => sources.delete(name)),
    removeLayer: vi.fn((name: string) => layers.delete(name)),
    setPaintProperty: vi.fn(),
    fitBounds: vi.fn(),
    on: vi.fn((name: string, callback: () => void) =>
      events.set(name, callback),
    ),
    off: vi.fn((name: string) => events.delete(name)),
  };
  return {
    value: value as unknown as MapboxMap,
    api: value,
    sources,
    layers,
    events,
  };
}
function Location() {
  const location = useLocation();
  return <output aria-label="预览位置">{location.pathname}</output>;
}
function show(map: MapboxMap, projectTagId = "1") {
  const onClose = vi.fn();
  const rendered = render(
    <AntApp>
      <MemoryRouter>
        <ComputeOutputMapPreview
          outputId={30}
          projectTagId={projectTagId}
          map={map}
          onClose={onClose}
        />
        <Location />
      </MemoryRouter>
    </AntApp>,
  );
  return { ...rendered, onClose };
}
beforeEach(() => {
  vi.restoreAllMocks();
  resetProjectSession();
  vi.spyOn(computeApi, "mapPreview").mockResolvedValue(preview);
  vi.spyOn(window, "fetch").mockResolvedValue(
    new Response(new Blob(["rendered PNG"]), {
      headers: { "Content-Type": "image/png" },
    }),
  );
});

it("renders the server image as a temporary map layer without creating a data resource", async () => {
  const map = mapMock();
  const importOutput = vi.spyOn(computeApi, "importOutput");
  const createObjectUrl = vi.spyOn(URL, "createObjectURL");
  const revokeObjectUrl = vi.spyOn(URL, "revokeObjectURL");
  const { onClose, unmount } = show(map.value);
  await screen.findByText(preview.name);
  await waitFor(() => expect(map.api.addSource).toHaveBeenCalledOnce());
  expect(window.fetch).toHaveBeenCalledWith(
    preview.imageUrl,
    expect.objectContaining({
      credentials: "include",
      headers: { "X-Project-Id": "1" },
    }),
  );
  expect(map.api.addSource).toHaveBeenCalledWith(
    "compute-output-preview-source",
    expect.objectContaining({
      type: "image",
      url: preview.imageUrl,
      coordinates: preview.imageCoordinates,
    }),
  );
  expect(map.api.fitBounds).toHaveBeenCalledWith(
    [
      [88.36, 40.14],
      [88.37, 40.15],
    ],
    expect.objectContaining({ maxZoom: 19 }),
  );
  expect(importOutput).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "关闭结果预览" }));
  expect(onClose).toHaveBeenCalledOnce();
  unmount();
  expect(map.api.removeLayer).toHaveBeenCalledWith(
    "compute-output-preview-layer",
  );
  expect(map.api.removeSource).toHaveBeenCalledWith(
    "compute-output-preview-source",
  );
  expect(createObjectUrl).not.toHaveBeenCalled();
  expect(revokeObjectUrl).not.toHaveBeenCalled();
});

it("uses a same-origin PNG API source with project context and Mapbox credentials", async () => {
  vi.spyOn(computeApi, "mapPreview").mockResolvedValue({
    ...preview,
    imageUrl: "/api/compute/outputs/30/map-preview/image/",
  });
  const map = mapMock();
  show(map.value);
  await waitFor(() => expect(map.api.addSource).toHaveBeenCalledOnce());
  const url = preview.imageUrl;
  expect(map.api.addSource).toHaveBeenCalledWith(
    "compute-output-preview-source",
    expect.objectContaining({ url }),
  );
  expect(projectTransformRequest(url)).toEqual({
    url: new URL(url, window.location.origin).href,
    credentials: "include",
  });
});

it("rejects an external preview image before requesting or adding it to the map", async () => {
  vi.spyOn(computeApi, "mapPreview").mockResolvedValue({
    ...preview,
    imageUrl: "https://untrusted.example/api/compute/outputs/30/image/",
  });
  const map = mapMock();
  show(map.value);
  await screen.findByText("结果预览地址无效");
  expect(window.fetch).not.toHaveBeenCalled();
  expect(map.api.addSource).not.toHaveBeenCalled();
});

it("restores the preview after a basemap style change and keeps the camera unchanged", async () => {
  const map = mapMock();
  show(map.value);
  await screen.findByText(preview.name);
  await waitFor(() => expect(map.api.addSource).toHaveBeenCalledOnce());
  map.sources.clear();
  map.layers.clear();
  act(() => {
    map.events.get("style.load")?.();
  });
  expect(map.api.addSource).toHaveBeenCalledTimes(2);
  expect(map.api.fitBounds).toHaveBeenCalledOnce();
});

it("adds a PNG received after style.load when the remaining basemap tiles become idle", async () => {
  const map = mapMock();
  map.api.isStyleLoaded.mockReturnValue(false);
  const { unmount } = show(map.value);
  await screen.findByText(preview.name);
  expect(map.api.addSource).not.toHaveBeenCalled();
  map.api.isStyleLoaded.mockReturnValue(true);
  act(() => map.events.get("idle")?.());
  expect(map.api.addSource).toHaveBeenCalledOnce();
  expect(map.api.fitBounds).toHaveBeenCalledOnce();
  const paintCalls = map.api.setPaintProperty.mock.calls.length;
  act(() => map.events.get("idle")?.());
  expect(map.api.setPaintProperty).toHaveBeenCalledTimes(paintCalls);
  expect(map.api.fitBounds).toHaveBeenCalledOnce();
  unmount();
  expect(map.events.size).toBe(0);
});

it("adds a PNG received before style.load and does not repeat it on idle", async () => {
  const map = mapMock();
  map.api.isStyleLoaded.mockReturnValue(false);
  show(map.value);
  await screen.findByText(preview.name);
  expect(map.api.addSource).not.toHaveBeenCalled();
  map.api.isStyleLoaded.mockReturnValue(true);
  act(() => map.events.get("style.load")?.());
  act(() => map.events.get("idle")?.());
  expect(map.api.addSource).toHaveBeenCalledOnce();
  expect(map.api.fitBounds).toHaveBeenCalledOnce();
});

it("restores a later basemap style on idle with the user's current opacity", async () => {
  const map = mapMock();
  show(map.value);
  await screen.findByText(preview.name);
  await waitFor(() => expect(map.api.addSource).toHaveBeenCalledOnce());
  const slider = screen.getByRole("slider");
  fireEvent.keyDown(slider, {
    key: "ArrowLeft",
    code: "ArrowLeft",
    keyCode: 37,
    which: 37,
  });
  await waitFor(() => expect(slider).toHaveAttribute("aria-valuenow", "99"));
  map.sources.clear();
  map.layers.clear();
  map.api.isStyleLoaded.mockReturnValue(false);
  act(() => map.events.get("style.load")?.());
  expect(map.api.addSource).toHaveBeenCalledOnce();
  map.api.isStyleLoaded.mockReturnValue(true);
  act(() => map.events.get("idle")?.());
  expect(map.api.addSource).toHaveBeenCalledTimes(2);
  expect(map.api.setPaintProperty).toHaveBeenLastCalledWith(
    "compute-output-preview-layer",
    "raster-opacity",
    0.99,
  );
  expect(map.api.fitBounds).toHaveBeenCalledOnce();
});

it("drops an unfinished response when the preview is closed", async () => {
  let resolve!: (value: ComputeMapPreview) => void;
  vi.spyOn(computeApi, "mapPreview").mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const map = mapMock();
  const { unmount } = show(map.value);
  await screen.findByText("正在准备结果预览…");
  unmount();
  await act(async () => {
    resolve(preview);
    await Promise.resolve();
  });
  expect(window.fetch).not.toHaveBeenCalled();
  expect(map.api.addSource).not.toHaveBeenCalled();
});

it("refuses a result from another project and does not issue a preview request", async () => {
  show(mapMock().value, "2");
  await screen.findByText("请切换到结果所属项目后查看。");
  expect(computeApi.mapPreview).not.toHaveBeenCalled();
  expect(window.fetch).not.toHaveBeenCalled();
});

it.each(["无权查看此计算结果", "计算结果已过期"])(
  "clears the private image when repeated authorization reports %s",
  async (reason) => {
    const timeout = vi.spyOn(window, "setTimeout");
    const map = mapMock();
    show(map.value);
    await screen.findByText(preview.name);
    await waitFor(() => expect(map.api.addSource).toHaveBeenCalledOnce());
    const reauthorize = timeout.mock.calls.find(
      (call) => call[1] === 15000,
    )?.[0];
    expect(reauthorize).toBeTypeOf("function");
    vi.spyOn(computeApi, "mapPreview").mockRejectedValue(new Error(reason));
    await act(async () => {
      (reauthorize as () => void)();
      await Promise.resolve();
    });
    await screen.findByText(reason);
    expect(map.sources.size).toBe(0);
    expect(map.layers.size).toBe(0);
  },
);

it("returns to the agent so the user can choose whether to import", async () => {
  show(mapMock().value);
  fireEvent.click(
    screen.getByRole("button", { name: /返回智能体，选择是否入库/ }),
  );
  expect(screen.getByRole("status", { name: "预览位置" })).toHaveTextContent(
    "/agent/workbench",
  );
});
