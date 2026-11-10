import type {
  BrowserSessionRequest,
  BrowserSessionResponse,
} from "../api/generated/types.gen";
import {
  recordResponseDiagnostic,
  ResponseFormatError,
} from "../api/responseDiagnostics";

export const browserSessionStorageKey = "stisp.browser-page-session";
export const browserSessionEndedEvent = "stisp:browser-session-ended";
export const browserSessionRecoveredEvent = "stisp:browser-session-recovered";
const channelName = "stisp.browser-session";
const endpoint = "/api/auth/browser-session/";
const heartbeatIntervalMs = 30_000;
const revalidateAfterMs = 25_000;
const handoffTimeoutMs = 1_500;
const renewalTimeoutMs = 8_000;
type SessionEndReason = "logout" | "expired" | "account-changed";

interface PageCredentials {
  pageId: string;
  token: string;
  sequence: number;
  familyId?: string;
}

let credentials: PageCredentials | null = null;
let active = false;
let timer: ReturnType<typeof setInterval> | undefined;
let channel: BroadcastChannel | null = null;
let startup: Promise<boolean> | null = null;
let renewal: Promise<boolean> | null = null;
let confirmedAt = 0;
let handlersInstalled = false;
let renewalFailed = false;
let lifecycle = 0;
let requests = new AbortController();
export function browserSessionSignal() {
  return requests.signal;
}
export function browserSessionFamily() {
  return credentials?.familyId ?? "";
}
export function invalidateBrowserRequests() {
  lifecycle += 1;
  requests.abort(new DOMException("登录或授权范围已变化", "AbortError"));
  requests = new AbortController();
}

export function observeResponseIdentity(family: string | null) {
  if (
    family &&
    /^[a-f0-9]{32}$/.test(family) &&
    active &&
    credentials?.familyId &&
    family !== credentials.familyId
  ) {
    endBrowserSession(false, "account-changed");
    throw new DOMException("账号已在其他页面切换", "AbortError");
  }
}

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
  retryTransient = true,
): Promise<BrowserSessionResponse> {
  const generation = lifecycle;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), renewalTimeoutMs);
  let response: Response;
  try {
    response = await fetch(
      new Request(endpoint, {
        method: "POST",
        credentials: "include",
        keepalive,
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
        },
        body: JSON.stringify(payload),
      }),
    );
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    recordResponseDiagnostic(
      endpoint,
      response,
      null,
      `browser_session_http:${response.status}`,
    );
    if (
      payload.action === "heartbeat" &&
      retryTransient &&
      [502, 503, 504].includes(response.status)
    ) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      if (
        generation !== lifecycle ||
        !active ||
        credentials?.pageId !== payload.pageId
      )
        throw new DOMException("页面会话已变化", "AbortError");
      return send(payload, keepalive, false);
    }
    throw Object.assign(
      new Error(
        response.status === 401
          ? "请重新登录"
          : `页面登录状态更新失败（HTTP ${response.status}）`,
      ),
      { status: response.status },
    );
  }
  let result: BrowserSessionResponse;
  try {
    result = await response.json();
    if (!result || typeof result.active !== "boolean")
      throw new Error("invalid active state");
  } catch {
    recordResponseDiagnostic(
      endpoint,
      response,
      null,
      "browser_session_invalid_response",
    );
    throw new ResponseFormatError(
      "browserSession",
      "页面会话返回内容异常，请重试",
    );
  }
  if (
    ["start", "join", "resume", "heartbeat"].includes(payload.action) &&
    result.active === false
  )
    throw Object.assign(new Error("页面会话未能续期"), { status: 401 });
  return result;
}

function payload(
  action: BrowserSessionRequest["action"],
  value: PageCredentials,
): BrowserSessionRequest {
  value.sequence += 1;
  storeCredentials(value);
  return {
    action,
    pageId: value.pageId,
    token: value.token,
    sequence: value.sequence,
  };
}

function ensureChannel() {
  if (channel || typeof BroadcastChannel === "undefined") return channel;
  channel = new BroadcastChannel(channelName);
  channel.addEventListener("message", (event) => {
    const data = event.data as {
      kind?: string;
      requestId?: string;
      token?: string;
      familyId?: string;
      reason?: SessionEndReason;
    } | null;
    if (!data) return;
    if (
      data.kind === "signed-in" &&
      typeof data.familyId === "string" &&
      credentials &&
      data.familyId !== credentials.familyId
    ) {
      endBrowserSession(false, "account-changed");
      return;
    }
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
      credentials &&
      (data.familyId && credentials.familyId
        ? data.familyId === credentials.familyId
        : credentials.token === data.token)
    ) {
      endBrowserSession(false, data.reason === "logout" ? "logout" : "expired");
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
    const receive = (event: Event) => {
      const data = (event as MessageEvent).data as {
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
    const timeout = setTimeout(() => finish(null), handoffTimeoutMs);
    peerChannel.addEventListener("message", receive);
    peerChannel.postMessage({ kind: "request", requestId });
  });
}

function install(value: PageCredentials, result: BrowserSessionResponse) {
  if (result.familyId) value.familyId = result.familyId;
  credentials = value;
  active = true;
  confirmedAt = Date.now();
  storeCredentials(value);
  ensureChannel();
  if (timer) clearInterval(timer);
  timer = setInterval(() => {
    void refreshBrowserSession(true).catch(() => {});
  }, heartbeatIntervalMs);
  if (handlersInstalled) return;
  handlersInstalled = true;
  window.addEventListener("pagehide", () => {
    if (!credentials || !active) return;
    invalidateBrowserRequests();
    active = false;
    startup = null;
    renewal = null;
    if (timer) clearInterval(timer);
    void send(payload("suspend", credentials), true).catch(() => {});
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted && credentials) {
      invalidateBrowserRequests();
      active = false;
      startup = null;
      renewal = null;
      if (timer) clearInterval(timer);
      void resumeBrowserSession().catch(() => {});
    }
  });
  const foreground = () => {
    if (document.visibilityState === "visible" && active && credentials)
      void refreshBrowserSession(true).catch(() => {});
  };
  window.addEventListener("focus", foreground);
  document.addEventListener("visibilitychange", foreground);
}

export function browserSessionEpoch() {
  return lifecycle;
}

/** Renew before protected API calls after timers were throttled or the device slept. */
export function refreshBrowserSession(force = false): Promise<boolean> {
  if (!credentials || !active) return Promise.resolve(false);
  if (renewal) return renewal;
  const elapsed = Date.now() - confirmedAt;
  if (!force && elapsed >= 0 && elapsed < revalidateAfterMs)
    return Promise.resolve(true);
  const page = credentials;
  const generation = lifecycle;
  const operation = send(payload("heartbeat", page))
    .then((result) => {
      if (generation !== lifecycle || credentials !== page || !active)
        return false;
      confirmedAt = Date.now();
      if (result.familyId) page.familyId = result.familyId;
      storeCredentials(page);
      if (renewalFailed) {
        renewalFailed = false;
        window.dispatchEvent(new Event(browserSessionRecoveredEvent));
      }
      return true;
    })
    .catch((error: unknown) => {
      if (generation !== lifecycle || credentials !== page || !active)
        return false;
      renewalFailed = true;
      if (error instanceof Error && "status" in error && error.status === 401)
        endBrowserSession(false);
      throw error;
    })
    .finally(() => {
      if (renewal === operation) renewal = null;
    });
  renewal = operation;
  return operation;
}

export function endBrowserSession(
  broadcast = true,
  reason: SessionEndReason = "expired",
) {
  invalidateBrowserRequests();
  if (broadcast && credentials)
    ensureChannel()?.postMessage({
      kind: "signed-out",
      token: credentials.token,
      familyId: credentials.familyId,
      reason,
    });
  credentials = null;
  active = false;
  startup = null;
  renewal = null;
  confirmedAt = 0;
  renewalFailed = false;
  if (timer) clearInterval(timer);
  timer = undefined;
  sessionStorage.removeItem(browserSessionStorageKey);
  window.dispatchEvent(
    new CustomEvent(browserSessionEndedEvent, { detail: { reason } }),
  );
}

export async function startBrowserSession() {
  invalidateBrowserRequests();
  const generation = lifecycle;
  credentials = null;
  active = false;
  startup = null;
  renewal = null;
  confirmedAt = 0;
  if (timer) clearInterval(timer);
  const value = { pageId: randomHex(16), token: randomHex(32), sequence: 0 };
  const result = await send(payload("start", value));
  if (generation !== lifecycle)
    throw new DOMException("登录操作已取消，请重新登录", "AbortError");
  install(value, result);
  if (result.familyId)
    ensureChannel()?.postMessage({
      kind: "signed-in",
      familyId: result.familyId,
    });
  startup = Promise.resolve(true);
}

export function resumeBrowserSession(): Promise<boolean> {
  if (active && credentials) return refreshBrowserSession();
  if (!startup) {
    const operation = restore();
    startup = operation;
    void operation.catch(() => {
      if (startup === operation) startup = null;
    });
  }
  return startup;
}

async function restore(): Promise<boolean> {
  const generation = lifecycle;
  const navigation = performance.getEntriesByType("navigation")[0] as
    | PerformanceNavigationTiming
    | undefined;
  // Retained JS belongs to a live BFCache document; restored storage alone does not.
  let value =
    credentials ?? (navigation?.type === "reload" ? readCredentials() : null);
  let action: "resume" | "join" = "resume";
  if (!value) {
    sessionStorage.removeItem(browserSessionStorageKey);
    const token = await onlinePeerToken();
    if (generation !== lifecycle) return false;
    if (token) value = { pageId: randomHex(16), token, sequence: 0 };
    else {
      value = { pageId: randomHex(16), token: randomHex(32), sequence: 0 };
      action = "join";
    }
  }
  try {
    const result = await send(payload(action, value));
    if (generation !== lifecycle) return false;
    install(value, result);
    return true;
  } catch (error) {
    if (generation !== lifecycle) return false;
    if (!(error instanceof Error && "status" in error && error.status === 401))
      throw error;
    if (action === "join") await send({ action: "abandon" }).catch(() => {});
    endBrowserSession(false);
    return false;
  }
}
