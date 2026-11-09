import {
  refreshBrowserSession,
  browserSessionEpoch,
  browserSessionSignal,
  browserSessionFamily,
  observeResponseIdentity,
} from "../auth/browserSession";
import { combineAbortSignals } from "../utils/abortSignals";
import { noteApiResponse } from "../api/responseDiagnostics";

const requestCleanups = new WeakMap<Request, () => void>();
const responseCleanups = new WeakMap<Response, () => void>();
const responseScopes = new WeakMap<Response, () => void>();
const responseUrls = new WeakMap<Response, string>();
const responseMethods = new WeakMap<Response, string>();
export function responseRequestMethod(response: Response) {
  return responseMethods.get(response) ?? "GET";
}
export function responseRequestUrl(response: Response) {
  return response.url || responseUrls.get(response) || window.location.href;
}

export function requestScope() {
  const epoch = browserSessionEpoch(),
    project = getActiveProject(),
    auth = browserSessionSignal(),
    scope = projectSignal();
  return () => {
    auth.throwIfAborted();
    scope.throwIfAborted();
    if (epoch !== browserSessionEpoch() || project !== getActiveProject())
      throw new DOMException("请求所属账号或项目已变化", "AbortError");
  };
}
export function assertResponseScope(response?: Response) {
  if (response) responseScopes.get(response)?.();
}
let activeProject = "1";
let controller = new AbortController();

export function getActiveProject() {
  return activeProject;
}
export function normalizeProjectSelection(value: string) {
  return /^[1-9]\d*$/.test(value) ? value : "1";
}
export function setActiveProject(value: string) {
  value = normalizeProjectSelection(value);
  if (value !== activeProject) {
    controller.abort();
    controller = new AbortController();
  }
  activeProject = value;
}
export function resetProjectSession() {
  controller.abort();
  controller = new AbortController();
  activeProject = "1";
}

export function projectSignal() {
  return controller.signal;
}

export function projectUrl(value: string) {
  if (!value.startsWith("/api/")) return value;
  const url = new URL(value, window.location.origin);
  if (!url.searchParams.has("projectTagId"))
    url.searchParams.set("projectTagId", activeProject);
  return `${url.pathname}${url.search}${url.hash}`;
}

export function attachProjectHeader(request: Request) {
  if (
    new URL(request.url).origin === window.location.origin &&
    new URL(request.url).pathname.startsWith("/api/")
  ) {
    if (!request.headers.has("X-Project-Id"))
      request.headers.set("X-Project-Id", activeProject);
    if (browserSessionFamily())
      request.headers.set("X-STISP-Session", browserSessionFamily());
    const group = combineAbortSignals([
      request.signal,
      controller.signal,
      browserSessionSignal(),
    ]);
    const scoped = new Request(request, { signal: group.signal });
    requestCleanups.set(scoped, group.dispose);
    return scoped;
  }
  return request;
}

export async function fetchProjectRequest(request: Request) {
  const dispose = requestCleanups.get(request);
  const check = requestScope();
  try {
    const epoch = browserSessionEpoch();
    await refreshBrowserSession();
    if (epoch !== browserSessionEpoch())
      throw new DOMException("登录状态已变化，已取消旧请求", "AbortError");
    const replayable =
      ["GET", "HEAD"].includes(request.method) ||
      request.headers.get("Content-Type")?.includes("application/json");
    const retry = replayable ? request.clone() : null;
    let response = await fetch(request, { cache: "no-store" });
    if (epoch !== browserSessionEpoch())
      throw new DOMException("登录状态已变化，已取消旧请求", "AbortError");
    if (
      response.status === 401 &&
      retry &&
      (await refreshBrowserSession(true))
    ) {
      await response.body?.cancel();
      if (epoch !== browserSessionEpoch())
        throw new DOMException("登录状态已变化，已取消旧请求", "AbortError");
      response = await fetch(retry, { cache: "no-store" });
    }
    if (epoch !== browserSessionEpoch())
      throw new DOMException("登录状态已变化，已取消旧请求", "AbortError");
    check();
    noteApiResponse(response);
    observeResponseIdentity(response.headers.get("X-STISP-Session"));
    if (dispose) responseCleanups.set(response, dispose);
    responseScopes.set(response, check);
    responseUrls.set(response, request.url);
    responseMethods.set(response, request.method);
    return response;
  } catch (error) {
    dispose?.();
    throw error;
  } finally {
    requestCleanups.delete(request);
  }
}

/** Run after SDK body parsing, so a project switch also cancels body reads. */
export function releaseProjectResponse(response?: Response) {
  if (!response) return;
  try {
    assertResponseScope(response);
  } finally {
    responseCleanups.get(response)?.();
    responseCleanups.delete(response);
    responseScopes.delete(response);
  }
}

export function projectTransformRequest(url: string) {
  const parsed = new URL(url, window.location.origin);
  if (
    parsed.origin === window.location.origin &&
    parsed.pathname.startsWith("/api/")
  ) {
    if (!parsed.searchParams.has("projectTagId"))
      parsed.searchParams.set("projectTagId", activeProject);
    return { url: parsed.href, credentials: "include" as const };
  }
  return { url };
}
