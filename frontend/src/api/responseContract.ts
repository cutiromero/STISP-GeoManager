/** Lightweight metadata checks at the API boundary; no scientific file scans. */
import { ResponseFormatError } from "./responseDiagnostics";

const fail = (path: string): never => {
  throw new ResponseFormatError(
    path,
    "平台接口返回内容不完整，当前有效内容已保留，请重试。",
  );
};
const object = (value: unknown, path: string): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return fail(path);
  return value as Record<string, unknown>;
};
const text = (value: unknown, path: string) => {
  if (typeof value !== "string") fail(path);
};
const number = (value: unknown, path: string) => {
  if (typeof value !== "number" || !Number.isFinite(value)) fail(path);
};
const bool = (value: unknown, path: string) => {
  if (typeof value !== "boolean") fail(path);
};
const array = (value: unknown, path: string): unknown[] => {
  if (!Array.isArray(value)) return fail(path);
  return value;
};

export function jsonContentType(value: string | null) {
  const type = (value ?? "").split(";", 1)[0]?.trim().toLowerCase();
  return (
    type === "application/json" ||
    Boolean(type?.startsWith("application/") && type.endsWith("+json"))
  );
}

export function assertUser(value: unknown, path = "user") {
  const user = object(value, path);
  number(user.id, path + ".id");
  text(user.username, path + ".username");
  array(user.roles, path + ".roles").forEach((role) =>
    text(role, path + ".roles[]"),
  );
  const permissions = object(user.permissions, path + ".permissions");
  for (const [key, value] of Object.entries(permissions))
    bool(value, path + ".permissions." + key);
  for (const key of ["canBrowseData", "canQueryData", "canAccessAdmin"])
    bool(permissions[key], path + ".permissions." + key);
}

export function validateApiContract(
  url: string,
  value: unknown,
  method = "GET",
) {
  const path = new URL(url, window.location.origin).pathname;
  if (path === "/api/bootstrap/") {
    const root = object(value, "bootstrap");
    text(root.systemName, "bootstrap.systemName");
    bool(root.allowRegistration, "bootstrap.allowRegistration");
    const map = object(root.map, "bootstrap.map");
    const center = array(map.defaultCenter, "bootstrap.map.defaultCenter");
    if (center.length !== 2) fail("bootstrap.map.defaultCenter");
    center.forEach((item) => number(item, "bootstrap.map.defaultCenter[]"));
    number(map.defaultZoom, "bootstrap.map.defaultZoom");
    text(map.defaultBasemap, "bootstrap.map.defaultBasemap");
    const limits = object(root.limits, "bootstrap.limits");
    for (const key of [
      "queryResultLimit",
      "uploadMaxMb",
      "maxRasterSidePixels",
    ]) {
      number(limits[key], "bootstrap.limits." + key);
      if ((limits[key] as number) <= 0) fail("bootstrap.limits." + key);
    }
  } else if (path === "/api/auth/me/") {
    const me = object(value, "me");
    bool(me.authenticated, "me.authenticated");
    if (me.authenticated) assertUser(me.user);
    else if (me.user != null) assertUser(me.user);
  } else if (
    [
      "/api/auth/login/",
      "/api/auth/register/",
      "/api/auth/guest-login/",
    ].includes(path)
  ) {
    assertUser(object(value, "login").user);
  } else if (path === "/api/compute/runtime/") {
    const runtime = object(value, "runtime");
    bool(runtime.available, "runtime.available");
    bool(runtime.workerOnline, "runtime.workerOnline");
    text(runtime.detail, "runtime.detail");
    array(runtime.runtimes, "runtime.runtimes");
    const permissions = object(runtime.permissions, "runtime.permissions");
    for (const key of [
      "submit_task",
      "view_own_task",
      "cancel_own_task",
      "manage_algorithms",
      "publish_algorithm",
      "download_algorithm",
      "manage_tasks",
      "download_outputs",
      "import_outputs",
    ])
      bool(permissions[key], "runtime.permissions." + key);
    const limits = object(runtime.limits, "runtime.limits");
    for (const key of [
      "userQueued",
      "globalQueued",
      "inputMiB",
      "outputMiB",
      "timeoutSeconds",
      "retentionDays",
    ])
      number(limits[key], "runtime.limits." + key);
  } else if (
    method === "GET" &&
    [
      "/api/catalog/resources/",
      "/api/catalog/workspaces/",
      "/api/catalog/map-compositions/",
      "/api/catalog/results/",
      "/api/layers/",
    ].includes(path)
  ) {
    const root = object(value, "list");
    for (const raw of array(root.items, "list.items")) {
      const item = object(raw, "list.items[]");
      number(item.id, "list.items[].id");
      text(item.name, "list.items[].name");
      if (path === "/api/catalog/resources/")
        for (const key of ["dataType", "fileFormat"])
          text(item[key], "list.items[]." + key);
    }
  }
}
