import { afterEach, expect, it, vi } from "vitest";
import { api, requestJson } from "./client";
import { computeApi } from "./compute";
import { RESPONSE_DIAGNOSTICS_KEY } from "./responseDiagnostics";
import { resetProjectSession } from "../projects/session";
import { endBrowserSession } from "../auth/browserSession";

const user = {
  id: 1,
  username: "valid",
  roles: [],
  permissions: {
    canBrowseData: true,
    canQueryData: true,
    canAccessAdmin: false,
  },
};
const bootstrap = {
  systemName: "STISP",
  allowRegistration: false,
  map: { defaultCenter: [100, 30], defaultZoom: 3, defaultBasemap: "osm" },
  limits: {
    uploadMaxMb: 512,
    queryResultLimit: 5000,
    maxRasterSidePixels: 12000,
  },
};
const json = (value: unknown) =>
  new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });
afterEach(() => {
  vi.unstubAllGlobals();
  resetProjectSession();
  endBrowserSession(false);
  sessionStorage.removeItem(RESPONSE_DIAGNOSTICS_KEY);
});

it.each(["JSON", "SDK"])(
  "rejects HTML200 through %s with bounded private diagnostics",
  async (kind) => {
    const html =
      '<!doctype html><html><title>登录 private content</title><div id="root"></div><script type="module" src="/static/assets/index-old.js"></script><body>PRIVATE_STRING</body></html>';
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(html, {
            headers: {
              "Content-Type": "text/html",
              "X-STISP-Build": "/static/assets/current.js",
              "X-Request-Id": "correlation-id",
            },
          }),
      ),
    );
    await expect(
      kind === "SDK" ? api.resources() : api.bootstrap(),
    ).rejects.toMatchObject({ name: "ResponseFormatError" });
    const stored = sessionStorage.getItem(RESPONSE_DIAGNOSTICS_KEY)!;
    expect(stored).toContain("correlation-id");
    expect(stored).toContain("current.js");
    expect(stored).not.toContain("PRIVATE_STRING");
    expect(stored).not.toContain("private content");
  },
);
it("rejects missing bootstrap limits and accepts the real contract on retry", async () => {
  const { limits: _, ...broken } = bootstrap;
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(json(broken))
      .mockResolvedValueOnce(json(bootstrap)),
  );
  await expect(api.bootstrap()).rejects.toMatchObject({
    name: "ResponseFormatError",
    issue: "bootstrap.limits",
  });
  await expect(api.bootstrap()).resolves.toEqual(bootstrap);
});
it("rejects incomplete authorization and runtime metadata without inventing permissions", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(json({ user: { id: 1 } }))
      .mockResolvedValueOnce(
        json({
          available: true,
          detail: "ok",
          workerOnline: true,
          runtimes: [],
        }),
      ),
  );
  await expect(
    requestJson("/api/auth/login/", { method: "POST" }),
  ).rejects.toMatchObject({ name: "ResponseFormatError" });
  await expect(computeApi.runtime()).rejects.toMatchObject({
    name: "ResponseFormatError",
    issue: "runtime.permissions",
  });
});
it("allows valid login metadata, list GET and single-object POST on the same URL", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(json({ user }))
      .mockResolvedValueOnce(json({ items: [] }))
      .mockResolvedValueOnce(json({ id: 1, name: "created" })),
  );
  await expect(
    requestJson("/api/auth/login/", { method: "POST" }),
  ).resolves.toEqual({ user });
  await expect(api.resources()).resolves.toEqual({ items: [] });
  await expect(
    requestJson("/api/catalog/results/", { method: "POST" }),
  ).resolves.toEqual({ id: 1, name: "created" });
});
