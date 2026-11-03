import { combineAbortSignals } from "../utils/abortSignals";

const requestCleanups = new WeakMap<Request, () => void>();
const responseCleanups = new WeakMap<Response, () => void>();
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
    const group = combineAbortSignals([request.signal, controller.signal]);
    const scoped = new Request(request, { signal: group.signal });
    requestCleanups.set(scoped, group.dispose);
    return scoped;
  }
  return request;
}

export async function fetchProjectRequest(request: Request) {
  const dispose = requestCleanups.get(request);
  try {
    const response = await fetch(request);
    if (dispose) responseCleanups.set(response, dispose);
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
  responseCleanups.get(response)?.();
  responseCleanups.delete(response);
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
