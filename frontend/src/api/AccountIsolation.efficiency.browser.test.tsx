/** Every response and error belongs to the identity that initiated it. */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import {
  api,
  requestJson,
  registerForbiddenHandler,
  unregisterForbiddenHandler,
} from "./client";
import {
  browserSessionEpoch,
  browserSessionStorageKey,
  endBrowserSession,
  startBrowserSession,
} from "../auth/browserSession";
import { resetProjectSession, setActiveProject } from "../projects/session";
import { AppContext } from "../contexts/AppContext";
import { RequireManageAuth } from "../router";
import type { Bootstrap, User } from "../types";

const fetchMock = vi.fn();
const json = (value: unknown) =>
  new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  setActiveProject("1");
});
afterEach(() => {
  endBrowserSession(false);
  resetProjectSession();
  unregisterForbiddenHandler();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

it.each([
  ["requestJson", "account"],
  ["SDK", "account"],
  ["requestJson", "project"],
  ["SDK", "project"],
] as const)(
  "checks an old %s response body finishing after a %s change",
  async (kind, boundary) => {
    let source!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        source = controller;
      },
    });
    const response = new Response(body, {
      headers: { "Content-Type": "application/json" },
    });
    fetchMock.mockImplementation((request: Request) =>
      new URL(request.url).pathname === "/api/auth/browser-session/"
        ? Promise.resolve(json({ active: true, detail: "ok" }))
        : Promise.resolve(response),
    );
    await startBrowserSession();
    const before = browserSessionEpoch();
    const pending =
      kind === "SDK"
        ? api.resources()
        : requestJson<{ items: unknown[] }>("/api/account-switch-analysis/");
    await vi.waitFor(() => expect(response.body?.locked).toBe(true));
    if (boundary === "account") {
      endBrowserSession(false, "logout");
      await startBrowserSession();
      expect(browserSessionEpoch()).toBeGreaterThan(before);
    } else setActiveProject("2");
    const old = { items: [{ id: 900001, name: "SYNTHETIC_OLD_ACCOUNT_DATA" }] };
    source.enqueue(new TextEncoder().encode(JSON.stringify(old)));
    source.close();
    const observed = await pending.then(
      (value) => ({ accepted: true, value }),
      (error) => ({ accepted: false, name: error.name }),
    );
    console.log(
      JSON.stringify({
        diagnostic: true,
        kind,
        responseBodyDelayedUntilAfterLoginChange: true,
        oldBodyAccepted: observed.accepted,
      }),
    );
    // Delayed bodies must never cross an identity boundary.
    expect(observed).toEqual({ accepted: false, name: "AbortError" });
  },
);

it("valid lower permissions redirect the protected route without crashing", async () => {
  const user = {
    id: 2,
    username: "admin",
    displayName: "admin",
    email: "",
    avatarUrl: "",
    department: "",
    isStaff: false,
    isSuperuser: false,
    roles: ["超级管理员"],
    operationLogGroupIds: [],
    permissions: { canManageAuth: true },
  } as User;
  const low = {
    ...user,
    id: 15,
    username: "low",
    roles: ["科研用户"],
    permissions: { ...user.permissions, canManageAuth: false },
  };
  const bootstrap = {
    systemName: "STISP",
    allowRegistration: false,
    map: {
      defaultCenter: [0, 0],
      defaultZoom: 1,
      defaultBasemap: "osm",
      mapboxAccessToken: "",
    },
    limits: { uploadMaxMb: 1, queryResultLimit: 10, maxRasterSidePixels: 10 },
  } as Bootstrap;
  const View = ({ account }: { account: User }) => (
    <AppContext.Provider
      value={{
        bootstrap,
        user: account,
        setUser: () => {},
        setBootstrap: () => {},
      }}
    >
      <MemoryRouter initialEntries={["/restricted"]}>
        <Routes>
          <Route element={<RequireManageAuth />}>
            <Route path="/restricted" element={<p>PRIVATE_FUNCTION</p>} />
          </Route>
          <Route
            path="/admin/profile"
            element={<p>SAFE_PERMISSION_FALLBACK</p>}
          />
        </Routes>
      </MemoryRouter>
    </AppContext.Provider>
  );
  const view = render(<View account={user} />);
  expect(screen.getByText("PRIVATE_FUNCTION")).toBeVisible();
  view.rerender(<View account={low} />);
  await waitFor(() =>
    expect(screen.getByText("SAFE_PERMISSION_FALLBACK")).toBeVisible(),
  );
  expect(screen.queryByText("PRIVATE_FUNCTION")).not.toBeInTheDocument();
  console.log(
    JSON.stringify({
      diagnostic: true,
      validHighToLowPermissions: true,
      safeRedirect: true,
    }),
  );
});

it("old SDK 401 neither notifies nor clears a newer login", async () => {
  let source!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      source = controller;
    },
  });
  const delayed = new Response(body, {
    status: 401,
    headers: { "Content-Type": "application/json" },
  });
  let attempts = 0;
  fetchMock.mockImplementation((request: Request) => {
    if (new URL(request.url).pathname === "/api/auth/browser-session/")
      return Promise.resolve(json({ active: true, detail: "ok" }));
    attempts++;
    return Promise.resolve(
      attempts === 1
        ? new Response(JSON.stringify({ detail: "retry old session" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
          })
        : delayed,
    );
  });
  await startBrowserSession();
  const forbidden = vi.fn(() => Promise.resolve());
  registerForbiddenHandler(forbidden);
  const pending = api.resources().then(
    () => ({ rejected: false }),
    (error) => ({ rejected: true, name: error.name }),
  );
  await vi.waitFor(() => expect(delayed.body?.locked).toBe(true));
  endBrowserSession(false, "logout");
  await startBrowserSession();
  expect(sessionStorage.getItem(browserSessionStorageKey)).not.toBeNull();
  source.enqueue(
    new TextEncoder().encode(JSON.stringify({ detail: "old account 401" })),
  );
  source.close();
  expect(await pending).toEqual({ rejected: true, name: "AbortError" });
  const newerLoginCleared =
    sessionStorage.getItem(browserSessionStorageKey) === null;
  console.log(
    JSON.stringify({
      diagnostic: true,
      oldSdk401BodyAfterNewLogin: true,
      newerLoginCleared,
      newContextNotified: forbidden.mock.calls.length,
    }),
  );
  expect(newerLoginCleared).toBe(false);
  expect(forbidden).not.toHaveBeenCalled();
});
