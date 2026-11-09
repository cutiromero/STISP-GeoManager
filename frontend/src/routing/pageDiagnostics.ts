import packageInfo from "../../package.json";
import {
  RESPONSE_DIAGNOSTICS_KEY,
  observedServerBuild,
} from "../api/responseDiagnostics";
import { moduleEntry } from "./clientBuild";

export const PAGE_ERROR_KEY = "platform:last-page-error";
const PAGE_ERRORS_KEY = "platform:page-errors";

function readStored(key: string, fallback: unknown): unknown {
  try {
    const value = sessionStorage.getItem(key);
    return value === null ? fallback : JSON.parse(value);
  } catch {
    return fallback;
  }
}

function trace(value: string | undefined) {
  return value?.slice(0, 9000).replace(/https?:\/\/[^\s)]+/g, (address) => {
    try {
      const url = new URL(address);
      return url.origin + url.pathname;
    } catch {
      return "[url]";
    }
  });
}

function loadedScripts() {
  let resources: string[] = [];
  try {
    resources = performance
      .getEntriesByType("resource")
      .map((entry) => entry.name);
  } catch {
    // A restricted performance API must not break the recovery page.
  }
  const names = [
    ...Array.from(document.scripts, (script) => script.src),
    ...resources,
  ];
  return [
    ...new Set(
      names.flatMap((name) => {
        try {
          const url = new URL(name, location.origin);
          return url.origin === location.origin && url.pathname.endsWith(".js")
            ? [url.pathname]
            : [];
        } catch {
          return [];
        }
      }),
    ),
  ].slice(-100);
}

export function pageErrorRecord(
  error: Error,
  componentStack?: string | null,
  path?: string,
) {
  return {
    time: new Date().toISOString(),
    version: packageInfo.version,
    clientEntry: moduleEntry(document),
    serverBuild: observedServerBuild() || null,
    path: (path ?? location.pathname).split(/[?#]/)[0],
    name: error.name,
    message: trace(error.message.slice(0, 800)),
    stack: trace(error.stack),
    componentStack: trace(componentStack ?? undefined),
    scripts: loadedScripts(),
    browser: navigator.userAgent,
  };
}

export function recordPageError(
  error: Error,
  componentStack?: string | null,
  path?: string,
) {
  const record = pageErrorRecord(error, componentStack, path);
  try {
    sessionStorage.setItem(PAGE_ERROR_KEY, JSON.stringify(record));
    const stored = readStored(PAGE_ERRORS_KEY, []);
    const previous = Array.isArray(stored) ? stored : [];
    sessionStorage.setItem(
      PAGE_ERRORS_KEY,
      JSON.stringify([...previous.slice(-4), record]),
    );
  } catch {
    // The visible error can still be exported when session storage is blocked.
  }
}

export function collectPageDiagnostics(error?: Error) {
  const errors = readStored(PAGE_ERRORS_KEY, []);
  const apiErrors = readStored(RESPONSE_DIAGNOSTICS_KEY, []);
  return {
    version: packageInfo.version,
    exportedAt: new Date().toISOString(),
    clientEntry: moduleEntry(document),
    serverBuild: observedServerBuild() || null,
    navigationType:
      (
        performance.getEntriesByType("navigation")[0] as
          | PerformanceNavigationTiming
          | undefined
      )?.type ?? null,
    origin: location.origin,
    path: location.pathname,
    browser: navigator.userAgent,
    scripts: loadedScripts(),
    pageError: readStored(
      PAGE_ERROR_KEY,
      error ? pageErrorRecord(error) : null,
    ),
    recentPageErrors: Array.isArray(errors) ? errors.slice(-5) : [],
    apiResponseErrors: Array.isArray(apiErrors) ? apiErrors.slice(-20) : [],
  };
}

export function downloadPageDiagnostics(error?: Error) {
  const blob = new Blob(
    [JSON.stringify(collectPageDiagnostics(error), null, 2)],
    {
      type: "application/json;charset=utf-8",
    },
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `平台异常诊断-${packageInfo.version}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
