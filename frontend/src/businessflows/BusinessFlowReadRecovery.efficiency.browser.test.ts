import { afterEach, expect, it, vi } from "vitest";
import { businessFlowsApi } from "../api/businessFlows";
import { resetProjectSession, setActiveProject } from "../projects/session";
import { endBrowserSession } from "../auth/browserSession";
import { RESPONSE_DIAGNOSTICS_KEY } from "../api/responseDiagnostics";
import { geologyDetail } from "./businessFlow.testFixtures";

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const html = () =>
  new Response("<!doctype html><title>unexpected page</title>", {
    headers: { "Content-Type": "text/html" },
  });
afterEach(() => {
  vi.unstubAllGlobals();
  resetProjectSession();
  endBrowserSession(false);
  sessionStorage.removeItem(RESPONSE_DIAGNOSTICS_KEY);
});

it("recovers a single HTML reply with the same project and a fresh read URL", async () => {
  setActiveProject("3");
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(html())
    .mockResolvedValueOnce(json(geologyDetail));
  vi.stubGlobal("fetch", fetch);
  await expect(businessFlowsApi.detail(1)).resolves.toEqual(geologyDetail);
  expect(fetch).toHaveBeenCalledTimes(2);
  const first = fetch.mock.calls[0]![0] as Request,
    second = fetch.mock.calls[1]![0] as Request;
  expect(first.headers.get("Accept")).toBe("application/json");
  expect(second.headers.get("X-Project-Id")).toBe("3");
  expect(new URL(second.url).pathname).toBe(new URL(first.url).pathname);
  expect(new URL(second.url).searchParams.get("_stisp_read")).toBeTruthy();
  expect(sessionStorage.getItem(RESPONSE_DIAGNOSTICS_KEY)).toContain(
    "unexpected_content_type",
  );
});
it("uses one request when healthy and never retries malformed contracts", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(json(geologyDetail))
    .mockResolvedValueOnce(json({ items: null, canManage: false }));
  vi.stubGlobal("fetch", fetch);
  await businessFlowsApi.detail(1);
  expect(fetch).toHaveBeenCalledTimes(1);
  await expect(businessFlowsApi.list()).rejects.toMatchObject({
    name: "ResponseFormatError",
    issue: "businessFlow.list",
  });
  expect(fetch).toHaveBeenCalledTimes(2);
});
it("stops after two malformed read replies and never replays a start", async () => {
  const fetch = vi.fn().mockImplementation(async () => html());
  vi.stubGlobal("fetch", fetch);
  await expect(businessFlowsApi.detail(1)).rejects.toMatchObject({
    name: "ResponseFormatError",
  });
  expect(fetch).toHaveBeenCalledTimes(2);
  await expect(
    businessFlowsApi.start(1, {
      inputs: {},
      idempotencyKey: "bounded-start-key",
    }),
  ).rejects.toMatchObject({ name: "ResponseFormatError" });
  expect(fetch).toHaveBeenCalledTimes(3);
});
it.each([401, 403, 404])(
  "does not disguise a real %s access failure with transport recovery",
  async (status) => {
    const fetch = vi
      .fn()
      .mockResolvedValue(json({ detail: "不可访问" }, status));
    vi.stubGlobal("fetch", fetch);
    await expect(businessFlowsApi.detail(1)).rejects.toMatchObject({ status });
    expect(fetch).toHaveBeenCalledTimes(1);
  },
);
it("does not issue recovery after project change or cancellation", async () => {
  setActiveProject("3");
  const controller = new AbortController();
  const fetch = vi.fn().mockImplementation(async () => {
    controller.abort();
    setActiveProject("1");
    return html();
  });
  vi.stubGlobal("fetch", fetch);
  await expect(
    businessFlowsApi.detail(1, { signal: controller.signal }),
  ).rejects.toMatchObject({ name: "AbortError" });
  expect(fetch).toHaveBeenCalledTimes(1);
});
