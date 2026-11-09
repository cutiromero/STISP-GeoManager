import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  browserSessionEndedEvent,
  browserSessionSignal,
  observeResponseIdentity,
  browserSessionStorageKey,
  endBrowserSession,
  resumeBrowserSession,
  refreshBrowserSession,
  startBrowserSession,
} from "./browserSession";

class TestChannel extends EventTarget {
  static instances = new Set<TestChannel>();
  constructor(readonly name: string) {
    super();
    TestChannel.instances.add(this);
  }
  postMessage(data: unknown) {
    for (const target of TestChannel.instances) {
      if (target !== this && target.name === this.name) {
        queueMicrotask(() =>
          target.dispatchEvent(new MessageEvent("message", { data })),
        );
      }
    }
  }
  close() {
    TestChannel.instances.delete(this);
  }
}

function savedPage() {
  return JSON.parse(
    sessionStorage.getItem(browserSessionStorageKey) ?? "null",
  ) as {
    pageId: string;
    token: string;
    sequence: number;
    familyId?: string;
  } | null;
}

describe("browser page session lifecycle", () => {
  const fetchMock = vi.fn();
  const peers: TestChannel[] = [];

  beforeEach(() => {
    endBrowserSession(false);
    fetchMock.mockReset();
    fetchMock.mockImplementation(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({ detail: "页面会话已更新", active: true }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("BroadcastChannel", TestChannel);
    vi.spyOn(performance, "getEntriesByType").mockReturnValue([
      { type: "navigate" } as PerformanceNavigationTiming,
    ]);
  });

  afterEach(() => {
    endBrowserSession(false);
    peers.splice(0).forEach((peer) => peer.close());
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  async function body(index: number) {
    const request = fetchMock.mock.calls[index]?.[0] as Request;
    return JSON.parse(await request.clone().text());
  }

  it("starts on HTTP-compatible crypto without randomUUID and suspends on pagehide", async () => {
    vi.stubGlobal("crypto", {
      getRandomValues: crypto.getRandomValues.bind(crypto),
    });
    await startBrowserSession();
    const page = savedPage();
    expect(page).toMatchObject({
      pageId: expect.stringMatching(/^[a-f0-9]{32}$/),
      token: expect.stringMatching(/^[a-f0-9]{64}$/),
      sequence: 1,
    });
    window.dispatchEvent(new PageTransitionEvent("pagehide"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(await body(0)).toEqual({ action: "start", ...page });
    expect(await body(1)).toEqual({ action: "suspend", ...page, sequence: 2 });
    const request = fetchMock.mock.calls[1]?.[0] as Request;
    expect(request.keepalive).toBe(true);
    expect(request.credentials).toBe("include");
  });

  it("distinguishes explicit logout and immediately removes the browser lease", async () => {
    await startBrowserSession();
    const ended = vi.fn();
    window.addEventListener(browserSessionEndedEvent, ended, { once: true });
    endBrowserSession(true, "logout");
    expect(savedPage()).toBeNull();
    expect((ended.mock.calls[0][0] as CustomEvent).detail).toEqual({
      reason: "logout",
    });
  });

  it("ignores an old heartbeat rejection after logout and a new sign in", async () => {
    const intervals = vi.spyOn(window, "setInterval");
    await startBrowserSession();
    let finishHeartbeat: (value: Response) => void = () => {};
    fetchMock.mockReturnValueOnce(
      new Promise((resolve) => {
        finishHeartbeat = resolve;
      }),
    );
    const heartbeat = intervals.mock.calls.find(
      (call) => call[1] === 30_000,
    )?.[0];
    expect(typeof heartbeat).toBe("function");
    if (typeof heartbeat === "function") heartbeat();
    endBrowserSession(false, "logout");
    await startBrowserSession();
    const current = savedPage();
    finishHeartbeat(
      new Response(JSON.stringify({ detail: "旧会话已结束" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(savedPage()).toEqual(current);
  });

  it("does not restore an old page lease after logout or overwrite a newer login", async () => {
    await startBrowserSession();
    const original = sessionStorage.getItem(browserSessionStorageKey)!;
    endBrowserSession(false);
    sessionStorage.setItem(browserSessionStorageKey, original);
    vi.mocked(performance.getEntriesByType).mockReturnValue([
      { type: "reload" } as PerformanceNavigationTiming,
    ]);
    let finishRestore: (value: Response) => void = () => {};
    fetchMock.mockReturnValueOnce(
      new Promise((resolve) => {
        finishRestore = resolve;
      }),
    );
    const restoring = resumeBrowserSession();
    endBrowserSession(false, "logout");
    await startBrowserSession();
    const current = savedPage();
    finishRestore(
      new Response(JSON.stringify({ detail: "ok", active: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    expect(await restoring).toBe(false);
    expect(savedPage()).toEqual(current);

    let finishPageShow: (value: Response) => void = () => {};
    fetchMock.mockReturnValueOnce(
      new Promise((resolve) => {
        finishPageShow = resolve;
      }),
    );
    window.dispatchEvent(
      new PageTransitionEvent("pageshow", { persisted: true }),
    );
    endBrowserSession(false, "logout");
    await startBrowserSession();
    const newest = savedPage();
    finishPageShow(
      new Response(JSON.stringify({ detail: "ok", active: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(savedPage()).toEqual(newest);
  });

  it("resumes the same page after reload with a newer sequence", async () => {
    await startBrowserSession();
    window.dispatchEvent(new PageTransitionEvent("pagehide"));
    const saved = sessionStorage.getItem(browserSessionStorageKey)!;
    const page = savedPage();
    endBrowserSession(false);
    sessionStorage.setItem(browserSessionStorageKey, saved);
    vi.mocked(performance.getEntriesByType).mockReturnValue([
      { type: "reload" } as PerformanceNavigationTiming,
    ]);
    expect(await resumeBrowserSession()).toBe(true);
    expect(await body(2)).toEqual({ action: "resume", ...page, sequence: 3 });
    expect(savedPage()?.pageId).toBe(page?.pageId);
  });

  it.each(["navigate", "back_forward"])(
    "does not accept restored storage for a new %s document without a live peer",
    async (type) => {
      const old = {
        pageId: "old_page_1234567890",
        token: "a".repeat(64),
        sequence: 9,
      };
      sessionStorage.setItem(browserSessionStorageKey, JSON.stringify(old));
      vi.mocked(performance.getEntriesByType).mockReturnValue([
        { type } as PerformanceNavigationTiming,
      ]);
      fetchMock.mockImplementation(async (request: Request) => {
        const message = await request.clone().json();
        return new Response(
          JSON.stringify({ detail: "无在线页面", active: false }),
          {
            status: message.action === "join" ? 401 : 200,
            headers: { "Content-Type": "application/json" },
          },
        );
      });
      expect(await resumeBrowserSession()).toBe(false);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(await body(0)).toMatchObject({ action: "join", sequence: 1 });
      expect((await body(0)).token).not.toBe(old.token);
      expect(await body(1)).toEqual({ action: "abandon" });
      expect(savedPage()).toBeNull();
    },
  );

  it("registers a noopener page without copied storage using a still-online peer's handoff", async () => {
    vi.stubGlobal("opener", null);
    sessionStorage.removeItem(browserSessionStorageKey);
    expect(savedPage()).toBeNull();
    const token = "b".repeat(64);
    const peer = new TestChannel("stisp.browser-session");
    peers.push(peer);
    peer.addEventListener("message", (event) => {
      const data = (event as MessageEvent).data;
      if (data.kind === "request")
        peer.postMessage({ kind: "handoff", requestId: data.requestId, token });
    });
    expect(await resumeBrowserSession()).toBe(true);
    expect(await body(0)).toMatchObject({
      action: "resume",
      token,
      sequence: 1,
    });
    expect(savedPage()?.pageId).toMatch(/^[a-f0-9]{32}$/);
    expect(window.opener).toBeNull();
  });

  it("restores a suspended back-forward-cache page rather than logging it out", async () => {
    await startBrowserSession();
    const first = savedPage();
    window.dispatchEvent(new PageTransitionEvent("pagehide"));
    window.dispatchEvent(
      new PageTransitionEvent("pageshow", { persisted: true }),
    );
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(await body(2)).toEqual({ action: "resume", ...first, sequence: 3 });
  });

  it("only honors sign-out broadcasts for the current login token", async () => {
    await startBrowserSession();
    const first = savedPage();
    const ended = vi.fn();
    window.addEventListener(browserSessionEndedEvent, ended);
    const peer = new TestChannel("stisp.browser-session");
    peers.push(peer);
    try {
      peer.postMessage({ kind: "signed-out", token: "c".repeat(64) });
      await Promise.resolve();
      expect(savedPage()).toEqual(first);
      expect(ended).not.toHaveBeenCalled();
      peer.postMessage({ kind: "signed-out", token: first?.token });
      await vi.waitFor(() => expect(ended).toHaveBeenCalledOnce());
      expect(savedPage()).toBeNull();
    } finally {
      window.removeEventListener(browserSessionEndedEvent, ended);
    }
  });

  it("joins a live Cookie session when a background peer cannot answer", async () => {
    expect(await resumeBrowserSession()).toBe(true);
    expect(await body(0)).toMatchObject({ action: "join", sequence: 1 });
    expect(savedPage()).not.toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("merges foreground and request renewals after background timer throttling", async () => {
    await startBrowserSession();
    const first = savedPage();
    const now = Date.now();
    vi.spyOn(Date, "now").mockReturnValue(now + 180_000);
    let complete: (response: Response) => void = () => {};
    fetchMock.mockReturnValueOnce(
      new Promise((resolve) => {
        complete = resolve;
      }),
    );
    const firstRenewal = refreshBrowserSession();
    const secondRenewal = refreshBrowserSession(true);
    expect(firstRenewal).toBe(secondRenewal);
    expect(await body(1)).toMatchObject({
      action: "heartbeat",
      pageId: first!.pageId,
    });
    complete(
      new Response(JSON.stringify({ active: true, detail: "ok" }), {
        status: 200,
      }),
    );
    expect(await firstRenewal).toBe(true);
    expect(savedPage()?.pageId).toBe(first?.pageId);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("keeps login on a transient renewal failure and retries next time", async () => {
    await startBrowserSession();
    const token = savedPage()?.token;
    fetchMock.mockRejectedValueOnce(new TypeError("offline"));
    await expect(refreshBrowserSession(true)).rejects.toThrow("offline");
    expect(savedPage()?.token).toBe(token);
    expect(await refreshBrowserSession(true)).toBe(true);
  });

  it("recovers immediately when a background document becomes visible", async () => {
    await startBrowserSession();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(await body(1)).toMatchObject({ action: "heartbeat" });
  });

  it("propagates explicit logout to independently joined pages in the same family", async () => {
    const familyId = "d".repeat(32);
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ active: true, detail: "ok", familyId }), {
        status: 200,
      }),
    );
    await startBrowserSession();
    const peer = new TestChannel("stisp.browser-session");
    peers.push(peer);
    peer.postMessage({
      kind: "signed-out",
      token: "e".repeat(64),
      familyId,
      reason: "logout",
    });
    await vi.waitFor(() => expect(savedPage()).toBeNull());
  });

  it("ignores a late heartbeat failure after a BFCache suspension and resume", async () => {
    await startBrowserSession();
    let complete: (response: Response) => void = () => {};
    fetchMock.mockReturnValueOnce(
      new Promise((resolve) => {
        complete = resolve;
      }),
    );
    const old = refreshBrowserSession(true);
    window.dispatchEvent(new PageTransitionEvent("pagehide"));
    window.dispatchEvent(
      new PageTransitionEvent("pageshow", { persisted: true }),
    );
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    complete(
      new Response(JSON.stringify({ detail: "旧请求失效" }), { status: 401 }),
    );
    await old;
    expect(savedPage()).not.toBeNull();
  });
  it("invalidates old requests when another tab signs in as a different identity", async () => {
    const familyId = "a".repeat(32);
    fetchMock.mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ active: true, familyId }))),
    );
    await startBrowserSession();
    const old = browserSessionSignal();
    const ended = vi.fn();
    window.addEventListener(browserSessionEndedEvent, ended, { once: true });
    const peer = new TestChannel("stisp.browser-session");
    peers.push(peer);
    peer.postMessage({ kind: "signed-in", familyId });
    await Promise.resolve();
    expect(old.aborted).toBe(false);
    peer.postMessage({ kind: "signed-in", familyId: "b".repeat(32) });
    await vi.waitFor(() => expect(old.aborted).toBe(true));
    expect(savedPage()).toBeNull();
    expect((ended.mock.calls[0][0] as CustomEvent).detail.reason).toBe(
      "account-changed",
    );
  });
  it("detects a changed response identity without trusting a stale body", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({ active: true, familyId: "a".repeat(32) }),
        ),
      ),
    );
    await startBrowserSession();
    const old = browserSessionSignal();
    expect(() => observeResponseIdentity("a".repeat(32))).not.toThrow();
    expect(() => observeResponseIdentity("b".repeat(32))).toThrow(
      "账号已在其他页面切换",
    );
    expect(old.aborted).toBe(true);
    expect(savedPage()).toBeNull();
  });
});
