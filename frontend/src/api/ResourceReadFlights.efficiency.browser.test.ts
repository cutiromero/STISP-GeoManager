import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, hasCurrentVectorPreview } from "./client";
import { endBrowserSession, startBrowserSession } from "../auth/browserSession";
import { resetProjectSession, setActiveProject } from "../projects/session";
import { createEmptyLayerGroup } from "../utils/layerFactory";
import { setLocale } from "../i18n";

const fetchMock = vi.fn();
const waitFor = vi.waitFor;
const resource = {
  ...createEmptyLayerGroup("input").sourceResource,
  id: 585,
  updatedAt: "2026-11-09T00:00:00Z",
};
function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
  });
}
function deferred() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function profile() {
  return {
    resource,
    fields: [],
    featureCount: 541,
    bounds: [95, 35, 96, 36],
    geometryType: "Polygon",
    vectorTiles: {
      revision: "0".repeat(24),
      tileUrl: "/tiles/{z}/{x}/{y}.pbf",
      sourceLayer: "features",
      minZoom: 0,
      maxZoom: 10,
      bounds: [95, 35, 96, 36],
      clustered: false,
      featureCount: 541,
    },
  };
}

beforeEach(async () => {
  await setLocale("zh-CN");
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation(() =>
    Promise.resolve(json({ active: true, detail: "页面会话已更新" })),
  );
  setActiveProject("3");
  await startBrowserSession();
  fetchMock.mockClear();
});
afterEach(() => {
  endBrowserSession(false);
  resetProjectSession();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

it("shares actual SDK reads across widgets and preserves independent cancellation", async () => {
  const waiting = deferred();
  fetchMock.mockReturnValue(waiting.promise);
  const controller = new AbortController();
  const first = api.resourceProfile(resource, { signal: controller.signal });
  const kept = api.resourceProfile(resource);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  const request = fetchMock.mock.calls[0][0] as Request;
  expect(request.headers.get("X-Project-Id")).toBe("3");
  controller.abort();
  await expect(first).rejects.toMatchObject({ name: "AbortError" });
  expect(request.signal.aborted).toBe(false);
  waiting.resolve(json(profile()));
  const result = await kept;
  expect(result.featureCount).toBe(541);
  expect(hasCurrentVectorPreview(resource, result.vectorTiles)).toBe(true);
  fetchMock.mockResolvedValue(json(profile()));
  await api.resourceProfile(resource);
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("starts a fresh read after a real resource update operation", async () => {
  const old = deferred(),
    current = deferred();
  let gets = 0;
  fetchMock.mockImplementation((request: Request) => {
    if (request.method === "GET")
      return ++gets === 1 ? old.promise : current.promise;
    return Promise.resolve(json({ detail: "updated" }));
  });
  const before = api.resourceProfile(resource);
  await waitFor(() => expect(gets).toBe(1));
  await api.updateAdminDataResource(resource.id, { name: "updated" });
  const after = api.resourceProfile(resource);
  await waitFor(() => expect(gets).toBe(2));
  old.resolve(json(profile()));
  current.resolve(json(profile()));
  const [prior, fresh] = await Promise.all([before, after]);
  expect(hasCurrentVectorPreview(resource, prior.vectorTiles)).toBe(false);
  expect(hasCurrentVectorPreview(resource, fresh.vectorTiles)).toBe(true);
});

it("coalesces identical display POSTs without replaying independent explicit queries", async () => {
  const waiting = deferred();
  fetchMock.mockReturnValue(waiting.promise);
  const payload = {
    attributeFilters: [],
    spatialFilter: null,
    limit: 100,
    displayGeometry: true,
  };
  const first = api.queryResource(resource, payload),
    second = api.queryResource(resource, payload);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  waiting.resolve(
    json({
      geojson: { type: "FeatureCollection", features: [] },
      fields: [],
      warnings: [],
    }),
  );
  await Promise.all([first, second]);
  fetchMock.mockImplementation(() =>
    Promise.resolve(
      json({ geojson: { type: "FeatureCollection", features: [] } }),
    ),
  );
  await Promise.all([
    api.queryResource(resource, { ...payload, displayGeometry: false }),
    api.queryResource(resource, { ...payload, displayGeometry: false }),
  ]);
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

it("records missing tile readiness without retaining the completed profile response", async () => {
  fetchMock.mockImplementation(() =>
    Promise.resolve(json({ ...profile(), vectorTiles: null })),
  );
  const first = await api.resourceProfile(resource);
  expect(hasCurrentVectorPreview(resource, first.vectorTiles)).toBe(true);
  await api.resourceProfile(resource);
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("keeps representation language in both request identity and actual headers", async () => {
  const chinese = deferred(),
    english = deferred();
  let count = 0;
  fetchMock.mockImplementation(() =>
    ++count === 1 ? chinese.promise : english.promise,
  );
  const first = api.resourceProfile(resource);
  await waitFor(() => expect(count).toBe(1));
  await setLocale("en-US");
  const second = api.resourceProfile(resource);
  await waitFor(() => expect(count).toBe(2));
  expect(
    (fetchMock.mock.calls[0][0] as Request).headers.get("Accept-Language"),
  ).toBe("zh-CN");
  expect(
    (fetchMock.mock.calls[1][0] as Request).headers.get("Accept-Language"),
  ).toBe("en-US");
  chinese.resolve(json(profile()));
  english.resolve(json(profile()));
  await Promise.all([first, second]);
});

it("freezes display parameters before an asynchronous request begins", async () => {
  fetchMock.mockImplementation(() =>
    Promise.resolve(
      json({ geojson: { type: "FeatureCollection", features: [] } }),
    ),
  );
  const payload = {
    attributeFilters: [],
    spatialFilter: null,
    limit: 100,
    displayGeometry: true,
  };
  const response = api.queryResource(resource, payload);
  payload.limit = 1;
  await response;
  const request = fetchMock.mock.calls[0][0] as Request;
  expect((await request.clone().json()).limit).toBe(100);
});
