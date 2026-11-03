import {
  getActiveProject,
  attachProjectHeader,
  projectSignal,
  fetchProjectRequest,
  releaseProjectResponse,
} from "../projects/session";
import { combineAbortSignals } from "../utils/abortSignals";
import {
  recordResponseDiagnostic,
  ResponseFormatError,
} from "./responseDiagnostics";
import type {
  AdminDashboard,
  AdminDashboardServer,
  AdminBackupOverview,
  AdminBackupRun,
  AdminBackupRunCreate,
  AdminBackupRunFilters,
  AdminBackupSettings,
  AdminBackupSettingsUpdate,
  AdminBackupTargetTestPayload,
  AdminBackupTargetTestResult,
  AdminDataResource,
  AdminDataResourceGroup,
  AdminDataResourceGroupUpdate,
  AdminDataResourceExportFilters,
  AdminDataResourceFilters,
  AdminDataResourceList,
  AdminDataResourceUpdate,
  AdminOperationLog,
  AdminOperationLogQuery,
  AdminProfile,
  AdminProfilePasswordUpdate,
  AdminProfilePermissionsUpdate,
  AdminProfileUpdate,
  AdminSettings,
  AdminSettingsUpdate,
  AdminSystemLog,
  AdminSystemLogQuery,
  AdminWorkspaceFilters,
  AdminWorkspaceList,
  AdminWorkspaceScene,
  AdminWorkspaceUpdate,
  Bootstrap,
  DataCatalog,
  DataSchemaSummary,
  DataResourceProfile,
  ExportLayersPayload,
  GermplasmAccessionFilters,
  GermplasmAccessionList,
  Group,
  GroupCreateRequest,
  GroupListResponse,
  GroupUpdateRequest,
  ImportCommitPayload,
  ImportCommitResult,
  ImportPreview,
  ImportValidatePayload,
  ImportValidateResult,
  VectorImportCommitPayload,
  VectorImportCommitResult,
  VectorImportPreview,
  VectorImportValidatePayload,
  VectorImportValidateResult,
  MapLayerListItem,
  NonGeoAnalytics,
  NonGeoTableQueryPayload,
  NonGeoTableQueryResult,
  LoginOverviewResponse,
  MapComposition,
  MapCompositionCreateRequest,
  MapCompositionDeleteResponse,
  MapCompositionListResponse,
  MapCompositionPublishRequest,
  MapCompositionRestoreProjectRequest,
  MapCompositionRestoreProjectResponse,
  MapCompositionUpdateRequest,
  MapCompositionVersion,
  MapCompositionVersionCreatePayload,
  RasterJob,
  RasterImportCommitPayload,
  RasterImportPreview,
  RasterRenderResult,
  RasterUniqueValuesResult,
  RegisterRequest,
  RegisterResponse,
  ResourceFilters,
  ResourceListItem,
  ResourceQueryPayload,
  ResourceQueryResult,
  ResourceVisualizationSummary,
  ResultArtifact,
  ResultArtifactCreatePayload,
  ResultArtifactDeleteResponse,
  ResultArtifactListResponse,
  ResultArtifactSourceType,
  ResultArtifactType,
  ResultArtifactUpdateRequest,
  SearchResult,
  RoleApplicationListItem,
  RoleApplicationListResponse,
  RoleApplicationReviewRequest,
  RoleApplicationStatus,
  User,
  UserCreateRequest,
  UserCreateResponse,
  UserGroupUpdateRequest,
  UserPasswordResetResponse,
  UserPermissionUpdateRequest,
  UserUpdateRequest,
  WorkspaceScene,
  WorkspaceSceneCreateRequest,
  WorkspaceSceneKind,
  WorkspaceSceneListResponse,
  WorkspaceSceneUpdateRequest,
} from "../types";
import type * as sdkTypes from "./generated/sdk.gen";
import type {
  ResourceBulkDeleteRequest,
  ResourceBulkDeleteResponse,
  ResourceDeletePreviewRequest,
  ResourceDeletePreviewResponse,
} from "./generated/types.gen";
import { filenameFromHeaders } from "./downloadFilename";
import i18n, { currentLocale } from "../i18n";
import {
  endBrowserSession,
  resumeBrowserSession,
  startBrowserSession,
} from "../auth/browserSession";

interface ListResponse<T> {
  items: T[];
}

interface PaginatedListResponse<T> extends ListResponse<T> {
  total: number;
}

interface MeResponse {
  authenticated: boolean;
  user: User;
}

class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(message: string, status: number, data?: unknown) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

type SdkModule = typeof sdkTypes;
type SdkFunction = (...args: never[]) => Promise<HeyApiResponse>;
let sdkPromise: Promise<SdkModule> | null = null;
let sdkConfigured = false;
const sdk = new Proxy({} as SdkModule, {
  get(_target, property: keyof SdkModule) {
    return (...args: never[]) =>
      getSdk()
        .then((module) => (module[property] as SdkFunction)(...args))
        .then((result) => {
          releaseProjectResponse(result.response);
          return result;
        });
  },
});

function getSdk() {
  sdkPromise ??= Promise.all([
    import("./generated/client.gen"),
    import("./generated/sdk.gen"),
  ])
    .then(([clientModule, sdkModule]) => {
      if (!sdkConfigured) {
        clientModule.client.setConfig({
          baseUrl: "",
          credentials: "include",
          fetch: (request) =>
            request instanceof Request
              ? fetchProjectRequest(request)
              : fetch(request),
        });
        clientModule.client.interceptors.request.use((request) => {
          request.headers.set("Accept-Language", currentLocale());
          if (request.method !== "GET") {
            request.headers.set("X-CSRFToken", getCookie("csrftoken") ?? "");
          }
          return attachProjectHeader(request);
        });
        sdkConfigured = true;
      }
      return sdkModule;
    })
    .catch((error: unknown) => {
      sdkPromise = null;
      throw error;
    });
  return sdkPromise;
}

interface HeyApiResponse<T = unknown> {
  data?: T;
  error?: unknown;
  response?: Response;
}

interface RequestLifecycleOptions {
  signal?: AbortSignal;
}

async function unwrap<T>(request: Promise<HeyApiResponse>): Promise<T> {
  const { data, error, response } = await request;
  if (error !== undefined) {
    if (isAbortError(error)) {
      throw error;
    }
    const status = response?.status ?? 0;
    notifyAuthorizationFailure(status, response?.url);
    throw new ApiError(errorMessage(error, status), status, error);
  }
  return data as T;
}

async function unwrapBlob(
  request: Promise<HeyApiResponse>,
): Promise<{ blob: Blob; filename: string }> {
  const { data, error, response } = await request;
  const status = response?.status ?? 0;
  if (error !== undefined) {
    notifyAuthorizationFailure(status, response?.url);
    throw new ApiError(errorMessage(error, status), status, error);
  }
  if (!(data instanceof Blob)) {
    throw new ApiError(i18n.t("common.exportEmpty"), status, data);
  }
  return {
    blob: data,
    filename: response ? filenameFromHeaders(response.headers) : "download.bin",
  };
}

function errorMessage(error: unknown, status: number) {
  if (typeof error === "string" && error) {
    return readableErrorText(error, status);
  }
  if (isRecord(error) && typeof error.detail === "string") {
    return localizedServerDetail(error.detail);
  }
  return status > 0
    ? i18n.t("common.requestFailed", { status })
    : i18n.t("common.networkFailed");
}

function localizedServerDetail(detail: string) {
  if (currentLocale() !== "en-US") return detail;
  const knownDetails: Record<string, string> = {
    请先登录: i18n.t("errors.unauthorized"),
    "CSRF 验证失败": i18n.t("errors.csrfFailed"),
    "请求体不是有效 JSON": i18n.t("errors.invalidJson"),
    账号或密码错误: i18n.t("auth.accountOrPasswordIncorrect"),
    当前系统未开放自助注册: "Self-registration is currently disabled",
    无权访问该图层: "You do not have access to this layer",
    无权访问该数据资源: "You do not have access to this data resource",
    无权查看该任务: "You do not have access to this task",
    该图层没有已预处理的栅格数据集:
      "This layer does not have a preprocessed raster dataset",
    栅格数据集不存在: "The raster dataset does not exist",
    用户不存在: "The user does not exist",
    角色不存在: "The role does not exist",
    角色名称已存在: "The role name already exists",
    账号已存在: "The account already exists",
    邮箱已被使用: "The email address is already in use",
    当前密码不正确: "The current password is incorrect",
    两次输入的新密码不一致: "The new passwords do not match",
    新密码不能与当前密码相同:
      "The new password must differ from the current password",
    密码已更新: "The password was updated",
    系统内置角色不能删除: "Built-in system roles cannot be deleted",
    "角色仍有关联用户，不能删除":
      "The role cannot be deleted while users are assigned to it",
    用户已删除: "The user was deleted",
    不能删除当前登录用户: "You cannot delete the signed-in account",
    不能停用当前登录用户: "You cannot disable the signed-in account",
    用户未设置头像: "The user has no profile image",
    请选择头像文件: "Select a profile image",
    "头像格式仅支持 JPG 和 PNG": "Profile images must be JPG or PNG",
    "头像文件大小不能超过 2MB": "The profile image cannot exceed 2 MB",
    头像文件不是有效图片: "The profile image is not valid",
    保存失败: "Save failed",
    "缺少 layerId 或 datasetId": "Missing layerId or datasetId",
    "缺少 sourcePath": "Missing sourcePath",
    角色申请不存在: "The role application does not exist",
    角色申请状态不存在: "The role-application status does not exist",
    已退出: "Signed out",
  };
  return knownDetails[detail] ?? detail;
}

function readableErrorText(text: string, status: number) {
  const trimmed = text.trim();
  if (/^<!doctype html/i.test(trimmed) || /^<html[\s>]/i.test(trimmed)) {
    const title = trimmed.match(/<title>(.*?)<\/title>/is)?.[1];
    const cleanedTitle = title ? stripHtml(title).trim() : "";
    return cleanedTitle
      ? `服务器内部错误：${cleanedTitle}`
      : `服务器内部错误：${status}`;
  }
  return trimmed.length > 240 ? `${trimmed.slice(0, 240)}...` : trimmed;
}

function stripHtml(text: string) {
  return text
    .replace(/<[^>]*>/g, "")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isAbortError(error: unknown) {
  return isRecord(error) && error.name === "AbortError";
}

function getCookie(name: string): string | null {
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

export async function requestJson<T>(
  url: string,
  options: {
    method?: string;
    body?: unknown;
    projectTagId?: string;
    signal?: AbortSignal;
    validate?: (data: unknown) => void;
  } = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const headers = new Headers();
  headers.set("Accept-Language", currentLocale());
  headers.set("X-Project-Id", options.projectTagId ?? getActiveProject());
  const cancellation = combineAbortSignals(
    options.signal ? [projectSignal(), options.signal] : [projectSignal()],
  );
  const init: RequestInit = {
    method,
    credentials: "include",
    headers,
    signal: cancellation.signal,
  };
  if (method !== "GET") {
    headers.set("X-CSRFToken", getCookie("csrftoken") ?? "");
  }
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(options.body);
  }
  try {
    const request = new Request(url, init);
    const response = await fetch(request);
    if (!response.ok) notifyAuthorizationFailure(response.status, request.url);
    let data: unknown;
    try {
      data = await parseResponseBody(response);
    } catch (error) {
      if (isAbortError(error)) throw error;
      if (!options.validate) throw error;
      recordResponseDiagnostic(
        request.url,
        response,
        undefined,
        "invalid_json",
      );
      if (!response.ok)
        throw new ApiError(
          errorMessage(null, response.status),
          response.status,
        );
      throw new ResponseFormatError("response: invalid JSON");
    }
    if (!response.ok) {
      if (options.validate)
        recordResponseDiagnostic(
          request.url,
          response,
          data,
          `http:${response.status}`,
        );
      throw new ApiError(
        errorMessage(data, response.status),
        response.status,
        data,
      );
    }
    try {
      options.validate?.(data);
    } catch (error) {
      recordResponseDiagnostic(
        request.url,
        response,
        data,
        error instanceof ResponseFormatError
          ? error.issue
          : "invalid_structure",
      );
      throw error;
    }
    return data as T;
  } finally {
    cancellation.dispose();
  }
}

interface FormRequestOptions {
  onUploadProgress?: (percent: number) => void;
  projectTagId?: number;
}

export async function requestForm<T>(
  url: string,
  formData: FormData,
  options: FormRequestOptions = {},
): Promise<T> {
  if (options.onUploadProgress) {
    return requestFormWithUploadProgress<T>(url, formData, options);
  }
  const headers = new Headers();
  headers.set("Accept-Language", currentLocale());
  headers.set(
    "X-Project-Id",
    String(options.projectTagId ?? getActiveProject()),
  );
  headers.set("X-CSRFToken", getCookie("csrftoken") ?? "");
  const response = await fetch(
    new Request(url, {
      method: "POST",
      signal: projectSignal(),
      credentials: "include",
      headers,
      body: formData,
    }),
  );
  const data = await parseResponseBody(response);
  if (!response.ok) {
    notifyAuthorizationFailure(response.status, response.url || url);
    throw new ApiError(
      errorMessage(data, response.status),
      response.status,
      data,
    );
  }
  return data as T;
}

function requestFormWithUploadProgress<T>(
  url: string,
  formData: FormData,
  options: FormRequestOptions,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    const signal = projectSignal();
    const abort = () => xhr.abort();
    signal.addEventListener("abort", abort, { once: true });
    xhr.addEventListener(
      "loadend",
      () => signal.removeEventListener("abort", abort),
      { once: true },
    );
    xhr.setRequestHeader("Accept-Language", currentLocale());
    xhr.setRequestHeader(
      "X-Project-Id",
      String(options.projectTagId ?? getActiveProject()),
    );
    xhr.withCredentials = true;
    xhr.setRequestHeader("X-CSRFToken", getCookie("csrftoken") ?? "");

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || event.total <= 0) {
        return;
      }
      options.onUploadProgress?.(
        Math.min(99, Math.round((event.loaded / event.total) * 100)),
      );
    };

    xhr.onerror = () => {
      reject(new ApiError("网络请求失败", xhr.status || 0));
    };

    xhr.onload = () => {
      const data = parseXhrBody(xhr);
      if (xhr.status < 200 || xhr.status >= 300) {
        notifyAuthorizationFailure(xhr.status, url);
        reject(new ApiError(errorMessage(data, xhr.status), xhr.status, data));
        return;
      }
      options.onUploadProgress?.(100);
      resolve(data as T);
    };

    xhr.send(formData);
  });
}

function parseXhrBody(xhr: XMLHttpRequest) {
  if (xhr.status === 204 || !xhr.responseText) {
    return undefined;
  }
  const contentType = xhr.getResponseHeader("Content-Type") ?? "";
  if (contentType.includes("application/json")) {
    try {
      return JSON.parse(xhr.responseText);
    } catch {
      return xhr.responseText;
    }
  }
  return xhr.responseText;
}

async function parseResponseBody(response: Response) {
  if (response.status === 204) {
    return undefined;
  }
  const contentType = response.headers.get("Content-Type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

type ForbiddenHandler = () => void | Promise<void>;
let onForbiddenHandler: ForbiddenHandler | null = null;
let authorizationRefreshInFlight = false;

const EXPECTED_UNAUTHENTICATED_PATHS = new Set([
  "/api/auth/csrf/",
  "/api/auth/me/",
  "/api/auth/login/",
  "/api/auth/guest-login/",
  "/api/auth/register/",
  "/api/auth/logout/",
]);

function notifyAuthorizationFailure(status: number, url?: string) {
  if (!onForbiddenHandler || (status !== 401 && status !== 403)) {
    return;
  }
  if (status === 401 && isExpectedUnauthenticatedRequest(url)) {
    return;
  }
  if (authorizationRefreshInFlight) {
    return;
  }
  authorizationRefreshInFlight = true;
  try {
    void Promise.resolve(onForbiddenHandler())
      .catch(() => undefined)
      .finally(() => {
        authorizationRefreshInFlight = false;
      });
  } catch {
    authorizationRefreshInFlight = false;
  }
}

function isExpectedUnauthenticatedRequest(url?: string) {
  if (!url) {
    return false;
  }
  try {
    return EXPECTED_UNAUTHENTICATED_PATHS.has(
      new URL(url, window.location.origin).pathname,
    );
  } catch {
    return false;
  }
}

export function registerForbiddenHandler(handler: ForbiddenHandler) {
  onForbiddenHandler = handler;
}

export function unregisterForbiddenHandler() {
  onForbiddenHandler = null;
  authorizationRefreshInFlight = false;
}

export const api = {
  bootstrap: () => requestJson<Bootstrap>("/api/bootstrap/"),
  loginOverview: () => unwrap<LoginOverviewResponse>(sdk.getLoginOverview()),
  csrf: () => requestJson<{ detail: string }>("/api/auth/csrf/"),
  me: async () => {
    if (!(await resumeBrowserSession()))
      throw new ApiError(i18n.t("errors.unauthorized"), 401);
    return requestJson<MeResponse>("/api/auth/me/");
  },
  login: async (username: string, password: string, remember = false) => {
    const response = await requestJson<{ user: User }>("/api/auth/login/", {
      method: "POST",
      body: { username, password, remember },
    });
    await startBrowserSession();
    return response;
  },
  guestLogin: async () => {
    const response = await requestJson<{ user: User }>(
      "/api/auth/guest-login/",
      { method: "POST" },
    );
    await startBrowserSession();
    return response;
  },
  register: async (payload: RegisterRequest) => {
    const response = await unwrap<RegisterResponse>(
      sdk.register({ body: payload }),
    );
    await startBrowserSession();
    return response;
  },
  logout: async () => {
    const response = await requestJson<{ detail: string }>(
      "/api/auth/logout/",
      { method: "POST" },
    );
    endBrowserSession();
    return response;
  },
  adminProfile: () => unwrap<AdminProfile>(sdk.getAdminProfile()),
  updateAdminProfile: (payload: AdminProfileUpdate) =>
    unwrap<AdminProfile>(sdk.updateAdminProfile({ body: payload })),
  updateAdminProfilePermissions: (payload: AdminProfilePermissionsUpdate) =>
    unwrap<AdminProfile>(sdk.updateAdminProfilePermissions({ body: payload })),
  updateAdminProfilePassword: (payload: AdminProfilePasswordUpdate) =>
    unwrap<{ detail: string }>(
      sdk.updateAdminProfilePassword({ body: payload }),
    ),
  adminOperationLogs: (filters: AdminOperationLogQuery = {}) =>
    unwrap<PaginatedListResponse<AdminOperationLog>>(
      sdk.listAdminOperationLogs({ query: filters }),
    ),
  adminSystemLogs: (filters: AdminSystemLogQuery = {}) =>
    unwrap<AdminSystemLog>(sdk.listAdminSystemLogs({ query: filters })),
  adminDashboard: (
    period: "day" | "week" | "month" = "day",
    options: RequestLifecycleOptions = {},
  ) =>
    unwrap<AdminDashboard>(
      sdk.getAdminDashboard({ query: { period }, signal: options.signal }),
    ),
  adminDashboardServer: (options: RequestLifecycleOptions = {}) =>
    unwrap<AdminDashboardServer>(
      sdk.getAdminDashboardServer({ signal: options.signal }),
    ),
  adminUsers: () => unwrap<ListResponse<User>>(sdk.listUsers()),
  roleApplications: (status?: RoleApplicationStatus) =>
    unwrap<RoleApplicationListResponse>(
      sdk.listRoleApplications({ query: status ? { status } : {} }),
    ),
  reviewRoleApplication: (
    applicationId: number,
    payload: RoleApplicationReviewRequest,
  ) =>
    unwrap<RoleApplicationListItem>(
      sdk.reviewRoleApplication({
        path: { applicationId },
        body: payload,
      }),
    ),
  createAdminUser: (payload: UserCreateRequest) =>
    unwrap<UserCreateResponse>(sdk.createUser({ body: payload })),
  updateAdminUserGroups: (userId: number, payload: UserGroupUpdateRequest) =>
    unwrap<User>(sdk.updateUserGroups({ path: { userId }, body: payload })),
  updateAdminUserPermissions: (
    userId: number,
    payload: UserPermissionUpdateRequest,
  ) =>
    unwrap<User>(
      sdk.updateUserPermissions({ path: { userId }, body: payload }),
    ),
  updateAdminUser: (userId: number, payload: UserUpdateRequest) =>
    unwrap<User>(sdk.updateUserOrDelete({ path: { userId }, body: payload })),
  resetAdminUserPassword: (userId: number) =>
    unwrap<UserPasswordResetResponse>(
      sdk.resetUserPassword({ path: { userId } }),
    ),
  deleteAdminUser: (userId: number) =>
    unwrap<{ detail: string }>(
      sdk.updateUserOrDelete({
        path: { userId },
        body: { action: "delete" },
      }),
    ),
  adminGroups: () => unwrap<GroupListResponse>(sdk.listGroups()),
  createAdminGroup: (payload: GroupCreateRequest) =>
    unwrap<Group>(sdk.createGroup({ body: payload })),
  updateAdminGroup: (groupId: number, payload: GroupUpdateRequest) =>
    unwrap<Group>(
      sdk.updateOrDeleteGroup({ path: { groupId }, body: payload }),
    ),
  deleteAdminGroup: (groupId: number) =>
    unwrap<{ detail: string }>(
      sdk.updateOrDeleteGroup({
        path: { groupId },
        body: { action: "delete" },
      }),
    ),
  adminSettings: () => unwrap<AdminSettings>(sdk.getAdminSettings()),
  updateAdminSettings: (payload: AdminSettingsUpdate) =>
    unwrap<AdminSettings>(sdk.updateAdminSettings({ body: payload })),
  adminBackupOverview: (options: RequestLifecycleOptions = {}) =>
    unwrap<AdminBackupOverview>(
      sdk.getAdminBackupOverview({ signal: options.signal }),
    ),
  adminBackupSettings: () =>
    unwrap<AdminBackupSettings>(sdk.getAdminBackupSettings()),
  updateAdminBackupSettings: (payload: AdminBackupSettingsUpdate) =>
    unwrap<AdminBackupSettings>(
      sdk.updateAdminBackupSettings({ body: payload }),
    ),
  testAdminBackupTarget: (payload: AdminBackupTargetTestPayload) =>
    unwrap<AdminBackupTargetTestResult>(
      sdk.testAdminBackupTarget({ body: payload }),
    ),
  adminBackupRuns: (
    filters: AdminBackupRunFilters = {},
    options: RequestLifecycleOptions = {},
  ) =>
    unwrap<PaginatedListResponse<AdminBackupRun>>(
      sdk.listAdminBackupRuns({ query: filters, signal: options.signal }),
    ),
  createAdminBackupRun: (payload: AdminBackupRunCreate) =>
    unwrap<AdminBackupRun>(sdk.createAdminBackupRun({ body: payload })),
  adminBackupRun: (runId: number, options: RequestLifecycleOptions = {}) =>
    unwrap<AdminBackupRun>(
      sdk.getAdminBackupRun({ path: { runId }, signal: options.signal }),
    ),
  downloadAdminBackupRun: (runId: number) =>
    unwrapBlob(
      sdk.downloadAdminBackupRun({
        path: { runId },
        parseAs: "blob",
      }),
    ),
  dataSchemaSummary: () =>
    unwrap<DataSchemaSummary>(sdk.getDataSchemaSummary()),
  germplasmAccessions: (filters: GermplasmAccessionFilters = {}) =>
    unwrap<GermplasmAccessionList>(
      sdk.listGermplasmAccessions({ query: filters }),
    ),
  adminDataResources: (filters: AdminDataResourceFilters = {}) =>
    unwrap<AdminDataResourceList>(
      sdk.listAdminDataResources({ query: filters }),
    ),
  updateAdminDataResource: (
    resourceId: number,
    payload: AdminDataResourceUpdate,
  ) =>
    unwrap<AdminDataResource | { detail: string }>(
      sdk.updateAdminDataResource({
        path: { id: resourceId },
        body: payload,
      }),
    ),
  createAdminDataResourceGroup: (payload: AdminDataResourceGroupUpdate) =>
    unwrap<AdminDataResourceGroup>(
      sdk.createAdminDataResourceGroup({
        body: payload,
      }),
    ),
  updateAdminDataResourceGroup: (
    groupId: number,
    payload: AdminDataResourceGroupUpdate,
  ) =>
    unwrap<AdminDataResourceGroup | { detail: string }>(
      sdk.updateAdminDataResourceGroup({
        path: { groupId },
        body: payload,
      }),
    ),
  exportAdminDataResources: (filters: AdminDataResourceExportFilters) =>
    unwrapBlob(
      sdk.exportAdminDataResources({
        query: filters,
        parseAs: "blob",
      }),
    ),
  adminWorkspaces: (filters: AdminWorkspaceFilters = {}) =>
    unwrap<AdminWorkspaceList>(sdk.listAdminWorkspaces({ query: filters })),
  updateAdminWorkspace: (workspaceId: number, payload: AdminWorkspaceUpdate) =>
    unwrap<AdminWorkspaceScene | { detail: string }>(
      sdk.updateAdminWorkspace({
        path: { workspaceId },
        body: payload,
      }),
    ),
  catalogs: () => unwrap<ListResponse<DataCatalog>>(sdk.getDirectories()),
  resources: (filters: ResourceFilters = {}) =>
    unwrap<ListResponse<ResourceListItem>>(
      sdk.getResources({ query: filters }),
    ),
  previewResourceDeletion: (
    payload: ResourceDeletePreviewRequest,
    projectTagId: string = getActiveProject(),
  ) =>
    unwrap<ResourceDeletePreviewResponse>(
      sdk.previewResourceDeletion({
        body: payload,
        headers: { "X-Project-Id": Number(projectTagId) },
      }),
    ),
  deleteResources: (
    payload: ResourceBulkDeleteRequest,
    projectTagId: string = getActiveProject(),
  ) =>
    unwrap<ResourceBulkDeleteResponse>(
      sdk.bulkDeleteResources({
        body: payload,
        headers: { "X-Project-Id": Number(projectTagId) },
      }),
    ),
  scanCatalogSources: () =>
    unwrap<ListResponse<ResourceListItem> & { count: number }>(
      sdk.scanCatalogSources(),
    ),
  workspaces: (
    query: {
      kind?: WorkspaceSceneKind;
      q?: string;
      limit?: number;
      offset?: number;
    } = {},
  ) => unwrap<WorkspaceSceneListResponse>(sdk.listCatalogWorkspaces({ query })),
  createWorkspace: (payload: WorkspaceSceneCreateRequest) =>
    unwrap<WorkspaceScene>(sdk.createCatalogWorkspace({ body: payload })),
  workspace: (workspaceId: number) =>
    unwrap<WorkspaceScene>(sdk.getCatalogWorkspace({ path: { workspaceId } })),
  updateWorkspace: (
    workspaceId: number,
    payload: WorkspaceSceneUpdateRequest,
  ) =>
    unwrap<WorkspaceScene | { detail: string }>(
      sdk.updateCatalogWorkspace({
        path: { workspaceId },
        body: payload,
      }),
    ),
  deleteWorkspace: (workspaceId: number) =>
    unwrap<{ detail: string }>(
      sdk.updateCatalogWorkspace({
        path: { workspaceId },
        body: { action: "delete" },
      }),
    ),
  mapCompositions: (
    filters: {
      projectId?: number;
      status?: MapComposition["status"];
    } = {},
  ) =>
    unwrap<MapCompositionListResponse>(
      sdk.listMapCompositions({ query: filters }),
    ),
  resultArtifacts: (
    filters: {
      q?: string;
      sourceType?: ResultArtifactSourceType;
      resultType?: ResultArtifactType;
      categoryCode?: string;
    } = {},
  ) =>
    unwrap<ResultArtifactListResponse>(
      sdk.listResultArtifacts({ query: filters }),
    ),
  createResultArtifact: (
    file: File,
    payload: ResultArtifactCreatePayload,
    projectTagId: number = 1,
  ) =>
    unwrap<ResultArtifact>(
      sdk.createResultArtifact({
        headers: { "X-Project-Id": String(projectTagId) },
        body: { file, payload: JSON.stringify(payload) },
      }),
    ),
  resultArtifact: (resultId: number) =>
    unwrap<ResultArtifact>(sdk.getResultArtifact({ path: { resultId } })),
  updateResultArtifact: (
    resultId: number,
    payload: ResultArtifactUpdateRequest,
  ) =>
    unwrap<ResultArtifact | ResultArtifactDeleteResponse>(
      sdk.updateResultArtifact({ path: { resultId }, body: payload }),
    ),
  downloadResultArtifact: (
    resultId: number,
    variant: "artifact" | "preview" = "artifact",
  ) =>
    unwrapBlob(
      sdk.downloadResultArtifact({
        path: { resultId },
        query: { variant },
        parseAs: "blob",
      }),
    ),
  createMapComposition: (payload: MapCompositionCreateRequest) =>
    unwrap<MapComposition>(sdk.createMapComposition({ body: payload })),
  mapComposition: (compositionId: number) =>
    unwrap<MapComposition>(sdk.getMapComposition({ path: { compositionId } })),
  updateMapComposition: (
    compositionId: number,
    payload: MapCompositionUpdateRequest,
  ) =>
    unwrap<MapComposition | { detail: string }>(
      sdk.updateMapComposition({
        path: { compositionId },
        body: payload,
      }),
    ),
  deleteMapComposition: (compositionId: number) =>
    unwrap<MapCompositionDeleteResponse>(
      sdk.updateMapComposition({
        path: { compositionId },
        body: { action: "delete" },
      }),
    ),
  publishMapComposition: (
    compositionId: number,
    payload: MapCompositionPublishRequest,
  ) =>
    unwrap<MapComposition>(
      sdk.publishMapComposition({
        path: { compositionId },
        body: payload,
      }),
    ),
  unpublishMapComposition: (compositionId: number) =>
    unwrap<MapComposition>(
      sdk.unpublishMapComposition({ path: { compositionId } }),
    ),
  restoreMapCompositionProject: (
    compositionId: number,
    payload: MapCompositionRestoreProjectRequest,
  ) =>
    unwrap<MapCompositionRestoreProjectResponse>(
      sdk.restoreMapCompositionProject({
        path: { compositionId },
        body: payload,
      }),
    ),
  createMapCompositionVersion: (
    compositionId: number,
    image: Blob,
    payload: MapCompositionVersionCreatePayload,
  ) =>
    unwrap<MapCompositionVersion>(
      sdk.createMapCompositionVersion({
        path: { compositionId },
        body: { image, payload: JSON.stringify(payload) },
      }),
    ),
  downloadMapCompositionVersion: (
    compositionId: number,
    versionNumber: number,
    variant: "artifact" | "preview" = "artifact",
  ) =>
    unwrapBlob(
      sdk.downloadMapCompositionVersion({
        path: { compositionId, versionNumber },
        query: { variant },
        parseAs: "blob",
      }),
    ),
  importPreview: (
    file: File,
    sheetName?: string | null,
    projectTagId: number = 1,
  ) => {
    const formData = new FormData();
    formData.append("file", file);
    if (sheetName) {
      formData.append("sheetName", sheetName);
    }
    return requestForm<ImportPreview>(
      "/api/catalog/import/preview/",
      formData,
      { projectTagId },
    );
  },
  importCommit: (
    file: File,
    payload: ImportCommitPayload,
    projectTagId: number = 1,
  ) =>
    unwrap<ImportCommitResult>(
      sdk.importCommit({
        body: { file, payload: JSON.stringify(payload) },
        headers: { "X-Project-Id": String(projectTagId) },
      }),
    ),
  importValidate: (
    file: File,
    payload: ImportValidatePayload,
    projectTagId: number = 1,
  ) =>
    unwrap<ImportValidateResult>(
      sdk.importValidate({
        body: { file, payload: JSON.stringify(payload) },
        headers: { "X-Project-Id": String(projectTagId) },
      }),
    ),
  previewVectorImport: (
    file: File,
    encoding?: string | null,
    projectTagId: number = 1,
  ) =>
    unwrap<VectorImportPreview>(
      sdk.previewVectorImport({
        headers: { "X-Project-Id": String(projectTagId) },
        body: { file, encoding: encoding?.trim() || undefined },
      }),
    ),
  validateVectorImport: (
    file: File,
    payload: VectorImportValidatePayload,
    projectTagId: number = 1,
  ) =>
    unwrap<VectorImportValidateResult>(
      sdk.validateVectorImport({
        headers: { "X-Project-Id": String(projectTagId) },
        body: { file, payload: JSON.stringify(payload) },
      }),
    ),
  commitVectorImport: (
    file: File,
    payload: VectorImportCommitPayload,
    projectTagId: number = 1,
  ) =>
    unwrap<VectorImportCommitResult>(
      sdk.commitVectorImport({
        headers: { "X-Project-Id": String(projectTagId) },
        body: { file, payload: JSON.stringify(payload) },
      }),
    ),
  previewRasterImport: (
    files: File[],
    primaryFileName?: string,
    projectTagId: number = 1,
  ) => {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    if (primaryFileName) {
      formData.append("primaryFileName", primaryFileName);
    }
    return requestForm<RasterImportPreview>(
      "/api/raster/import/preview/",
      formData,
      { projectTagId },
    );
  },
  importRaster: (
    fileOrFiles: File | File[],
    payloadOrName: RasterImportCommitPayload | string,
    onUploadProgress?: (percent: number) => void,
    projectTagId: number = 1,
  ) => {
    const formData = new FormData();
    const files = Array.isArray(fileOrFiles) ? fileOrFiles : [fileOrFiles];
    files.forEach((file) => formData.append("files", file));
    if (typeof payloadOrName === "string") {
      if (payloadOrName.trim()) {
        formData.append("name", payloadOrName.trim());
      }
    } else {
      formData.append("payload", JSON.stringify(payloadOrName));
    }
    return requestForm<RasterJob>("/api/raster/import/", formData, {
      onUploadProgress,
      projectTagId,
    });
  },
  resourceProfile: (resource: ResourceListItem) =>
    unwrap<DataResourceProfile>(
      sdk.getResourceProfile({ path: { id: resource.id } }),
    ),
  resourceVisualizationSummary: (
    resource: ResourceListItem,
    params: { topN?: number; histogramBins?: number } = {},
  ) =>
    unwrap<ResourceVisualizationSummary>(
      sdk.getResourceVisualizationSummary({
        path: { id: resource.id },
        query: params,
      }),
    ),
  nonGeoAnalysis: (resourceId: number) =>
    requestJson<NonGeoAnalytics>(
      `/api/catalog/resources/${resourceId}/nongeo-analysis/`,
    ),
  nonGeoQuery: (resourceId: number, payload: NonGeoTableQueryPayload = {}) =>
    requestJson<NonGeoTableQueryResult>(
      `/api/catalog/resources/${resourceId}/nongeo-query/`,
      { method: "POST", body: payload },
    ),
  queryResource: (resource: ResourceListItem, payload: ResourceQueryPayload) =>
    unwrap<ResourceQueryResult>(
      sdk.queryResource({
        path: { id: resource.id },
        body: payload,
      }),
    ),
  exportLayers: (payload: ExportLayersPayload) =>
    unwrapBlob(sdk.exportLayers({ body: payload, parseAs: "blob" })),
  exportLayersAsync: (payload: ExportLayersPayload) =>
    unwrap<RasterJob>(sdk.exportLayersAsync({ body: payload })),
  downloadExport: (jobId: string) =>
    unwrapBlob(
      sdk.downloadExport({
        path: { job_id: jobId },
        parseAs: "blob",
      }),
    ),
  layers: () => unwrap<ListResponse<MapLayerListItem>>(sdk.getLayers()),
  search: (query: string) =>
    unwrap<SearchResult>(sdk.search({ query: { q: query } })),
  renderRaster: (
    layerId: number,
    rulesMode: "default" | "custom" = "default",
    rules?: Record<string, unknown>,
  ) =>
    unwrap<RasterRenderResult>(
      sdk.renderRaster({ body: { layerId, rulesMode, rules } }),
    ),
  renderRasterAsync: (
    payload: {
      layerId?: number | null;
      datasetId?: number | null;
      rules?: Record<string, unknown>;
      rulesMode?: "default" | "custom";
    },
    options: RequestLifecycleOptions = {},
  ) =>
    unwrap<RasterJob>(
      sdk.renderRasterAsync({ body: payload, signal: options.signal }),
    ),
  rasterJob: (
    jobId: string,
    options: RequestLifecycleOptions & { projectTagId?: number } = {},
  ) =>
    unwrap<RasterJob>(
      sdk.getJobStatus({
        path: { job_id: jobId },
        headers:
          options.projectTagId === undefined
            ? undefined
            : { "X-Project-Id": String(options.projectTagId) },
        signal: options.signal,
      }),
    ),
  classifyRasterUniqueValues: (datasetId: number, band: number) =>
    unwrap<RasterUniqueValuesResult>(
      sdk.getUniqueValues({ body: { datasetId, band } }),
    ),
  scanRasterSources: () => unwrap<RasterJob>(sdk.scanRasterSources()),
};

export { ApiError };
