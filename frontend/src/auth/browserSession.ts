import type {
  BrowserSessionRequest,
  BrowserSessionResponse,
} from "../api/generated/types.gen";

export const browserSessionStorageKey = "stisp.browser-page-session";
export const browserSessionEndedEvent = "stisp:browser-session-ended";
const channelName = "stisp.browser-session";
const endpoint = "/api/auth/browser-session/";

interface PageCredentials {
  pageId: string;
  token: string;
  sequence: number;
}

let credentials: PageCredentials | null = null;
let active = false;
let timer: ReturnType<typeof setInterval> | undefined;
let channel: BroadcastChannel | null = null;
let startup: Promise<boolean> | null = null;
let handlersInstalled = false;

function randomHex(bytes: number) {
  return Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

function validCredentials(value: unknown): value is PageCredentials {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<PageCredentials>;
  return (
    typeof item.pageId === "string" &&
    /^[A-Za-z0-9_-]{16,80}$/.test(item.pageId) &&
    typeof item.token === "string" &&
    /^[a-f0-9]{64}$/.test(item.token) &&
    Number.isSafeInteger(item.sequence) &&
    (item.sequence ?? 0) >= 0
  );
}

function readCredentials(): PageCredentials | null {
  try {
    const value: unknown = JSON.parse(
      sessionStorage.getItem(browserSessionStorageKey) ?? "null",
    );
    return validCredentials(value) ? value : null;
  } catch {
    return null;
  }
}

function storeCredentials(value: PageCredentials) {
  sessionStorage.setItem(browserSessionStorageKey, JSON.stringify(value));
}

function csrfToken() {
  const row = document.cookie
    .split("; ")
    .find((item) => item.startsWith("csrftoken="));
  return row ? decodeURIComponent(row.slice("csrftoken=".length)) : "";
}

async function send(
  payload: BrowserSessionRequest,
  keepalive = false,
): Promise<BrowserSessionResponse> {
  const response = await fetch(
    new Request(endpoint, {
      method: "POST",
      credentials: "include",
      keepalive,
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
      },
      body: JSON.stringify(payload),
    }),
  );
  if (!response.ok) {
    const error = new Error(
      response.status === 401 ? "请重新登录" : "页面登录状态更新失败",
    );
    throw Object.assign(error, { status: response.status });
  }
  return response.json();
}

function payload(
  action: BrowserSessionRequest["action"],
  value: PageCredentials,
): BrowserSessionRequest {
  value.sequence += 1;
  storeCredentials(value);
  return { action, ...value };
}

function ensureChannel() {
  if (channel || typeof BroadcastChannel === "undefined") return channel;
  channel = new BroadcastChannel(channelName);
  channel.addEventListener("message", (event) => {
    const data = event.data as {
      kind?: string;
      requestId?: string;
      token?: string;
    } | null;
    if (!data) return;
    if (
      data.kind === "request" &&
      typeof data.requestId === "string" &&
      active &&
      credentials
    ) {
      channel?.postMessage({
        kind: "handoff",
        requestId: data.requestId,
        token: credentials.token,
      });
    } else if (
      data.kind === "signed-out" &&
      credentials?.token === data.token
    ) {
      endBrowserSession(false);
    }
  });
  return channel;
}

async function onlinePeerToken(): Promise<string | null> {
  const peerChannel = ensureChannel();
  if (!peerChannel) return null;
  const requestId = randomHex(16);
  return new Promise((resolve) => {
    const finish = (value: string | null) => {
      clearTimeout(timeout);
      peerChannel.removeEventListener("message", receive);
      resolve(value);
    };
    const receive = (event: MessageEvent) => {
      const data = event.data as {
        kind?: string;
        requestId?: string;
        token?: string;
      } | null;
      if (
        data?.kind === "handoff" &&
        data.requestId === requestId &&
        typeof data.token === "string" &&
        /^[a-f0-9]{64}$/.test(data.token)
      )
        finish(data.token);
    };
    const timeout = setTimeout(() => finish(null), 400);
    peerChannel.addEventListener("message", receive);
    peerChannel.postMessage({ kind: "request", requestId });
  });
}

function install(value: PageCredentials) {
  credentials = value;
  active = true;
  storeCredentials(value);
  ensureChannel();
  if (timer) clearInterval(timer);
  timer = setInterval(() => {
    if (!credentials || !active) return;
    void send(payload("heartbeat", credentials)).catch((error) => {
      if (error instanceof Error && "status" in error && error.status === 401)
        endBrowserSession();
    });
  }, 30_000);
  if (handlersInstalled) return;
  handlersInstalled = true;
  window.addEventListener("pagehide", () => {
    if (!credentials || !active) return;
    active = false;
    if (timer) clearInterval(timer);
    void send(payload("suspend", credentials), true).catch(() => {});
  });
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted || !credentials) return;
    const saved = credentials;
    void send(payload("resume", saved))
      .then(() => install(saved))
      .catch(() => endBrowserSession());
  });
}

export function endBrowserSession(broadcast = true) {
  if (broadcast && credentials)
    ensureChannel()?.postMessage({
      kind: "signed-out",
      token: credentials.token,
    });
  credentials = null;
  active = false;
  startup = null;
  if (timer) clearInterval(timer);
  timer = undefined;
  sessionStorage.removeItem(browserSessionStorageKey);
  window.dispatchEvent(new Event(browserSessionEndedEvent));
}

export async function startBrowserSession() {
  const token = randomHex(32);
  const value = { pageId: randomHex(16), token, sequence: 0 };
  await send(payload("start", value));
  install(value);
  startup = Promise.resolve(true);
}

export function resumeBrowserSession(): Promise<boolean> {
  startup ??= restore();
  return startup;
}

async function restore(): Promise<boolean> {
  if (active && credentials) return true;
  const navigation = performance.getEntriesByType("navigation")[0] as
    | PerformanceNavigationTiming
    | undefined;
  const cached = readCredentials();
  let value = navigation?.type === "reload" ? cached : null;
  if (!value) {
    sessionStorage.removeItem(browserSessionStorageKey);
    const token = await onlinePeerToken();
    if (token) value = { pageId: randomHex(16), token, sequence: 0 };
  }
  try {
    if (!value) {
      await send({ action: "abandon" });
      return false;
    }
    await send(payload("resume", value));
    install(value);
    return true;
  } catch (error) {
    if (!(error instanceof Error && "status" in error && error.status === 401))
      throw error;
    endBrowserSession(false);
    return false;
  }
}
