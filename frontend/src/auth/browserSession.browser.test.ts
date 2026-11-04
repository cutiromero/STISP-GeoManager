import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  browserSessionEndedEvent,
  browserSessionStorageKey,
  endBrowserSession,
  resumeBrowserSession,
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
      expect(await resumeBrowserSession()).toBe(false);
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(await body(0)).toEqual({ action: "abandon" });
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
});
