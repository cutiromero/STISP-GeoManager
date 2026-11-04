import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ExportLayersPayload, ResourceListItem } from "../types";
import {
  ApiError,
  api,
  requestJson,
  registerForbiddenHandler,
  unregisterForbiddenHandler,
} from "./client";
import { setLocale } from "../i18n";
import { setActiveProject, resetProjectSession } from "../projects/session";
import {
  browserSessionStorageKey,
  endBrowserSession,
  startBrowserSession,
} from "../auth/browserSession";

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  return new Response(JSON.stringify(body), { ...init, headers });
}

function setTestCookie(value: string) {
  // oxlint-disable-next-line unicorn/no-document-cookie -- tests need to seed document.cookie for CSRF coverage.
  document.cookie = value;
}

function capturedRequest(fetchMock: ReturnType<typeof vi.fn>, index = 0) {
  return fetchMock.mock.calls[index]?.[0] as Request;
}

function requestPath(request: Request) {
  const url = new URL(request.url);
  return `${url.pathname}${url.search}`;
}

describe("api client", () => {
  const fetchMock = vi.fn();

  beforeEach(async () => {
    fetchMock.mockReset();
    await setLocale("zh-CN");
    vi.stubGlobal("fetch", fetchMock);
    setTestCookie("csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/");
  });

  afterEach(() => {
    endBrowserSession(false);
    resetProjectSession();
    unregisterForbiddenHandler();
    vi.unstubAllGlobals();
  });

  it("ends the local lease immediately and signs in only after the previous logout response", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ detail: "ok" })),
    );
    await startBrowserSession();
    let finishLogout: (response: Response) => void = () => {};
    fetchMock.mockReturnValueOnce(
      new Promise((resolve) => {
        finishLogout = resolve;
      }),
    );
    const logout = api.logout();
    expect(sessionStorage.getItem(browserSessionStorageKey)).toBeNull();
    const login = api.login("next-user", "next-password");
    await Promise.resolve();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    finishLogout(jsonResponse({ detail: "已退出" }));
    await logout;
    await login;
    expect(requestPath(capturedRequest(fetchMock, 2))).toBe("/api/auth/login/");
    expect(sessionStorage.getItem(browserSessionStorageKey)).not.toBeNull();
  });

  it("keeps the local lease ended even when server logout fails", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ detail: "ok" })),
    );
    await startBrowserSession();
    fetchMock.mockRejectedValueOnce(new TypeError("network unavailable"));
    await expect(api.logout()).rejects.toThrow("network unavailable");
    expect(sessionStorage.getItem(browserSessionStorageKey)).toBeNull();
    await api.login("retry-user", "retry-password");
    expect(requestPath(capturedRequest(fetchMock, 2))).toBe("/api/auth/login/");
    expect(sessionStorage.getItem(browserSessionStorageKey)).not.toBeNull();
  });

  it("bounds a hanging logout and releases the next login after the timeout", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ detail: "ok" })),
    );
    const timeoutSpy = vi.spyOn(window, "setTimeout");
    try {
      fetchMock.mockImplementationOnce(
        (request: Request) =>
          new Promise((_, reject) => {
            request.signal.addEventListener(
              "abort",
              () => reject(request.signal.reason),
              { once: true },
            );
          }),
      );
      const logout = api.logout();
      const login = api.login("after-timeout", "retry-password");
      const rejection = expect(logout).rejects.toThrow("退出确认超时");
      const timeout = timeoutSpy.mock.calls.find(
        (call) => call[1] === 10_000,
      )?.[0];
      expect(typeof timeout).toBe("function");
      if (typeof timeout === "function") timeout();
      await rejection;
      await login;
      expect(requestPath(capturedRequest(fetchMock, 1))).toBe(
        "/api/auth/login/",
      );
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("forwards caller cancellation to the real Request without aborting other project reads", async () => {
    setActiveProject("3");
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ items: [] })),
    );
    const caller = new AbortController();
    await requestJson("/api/compute/inputs/", { signal: caller.signal });
    await requestJson("/api/agent/workflows/");
    const catalog = capturedRequest(fetchMock, 0);
    const history = capturedRequest(fetchMock, 1);
    expect(catalog.signal.aborted).toBe(false);
    caller.abort();
    expect(catalog.signal.aborted).toBe(true);
    expect(history.signal.aborted).toBe(false);
    setActiveProject("4");
    expect(history.signal.aborted).toBe(true);
  });

  it("loads JSON and generated SDK requests without native AbortSignal.any", async () => {
    const original = AbortSignal.any;
    Object.defineProperty(AbortSignal, "any", {
      value: undefined,
      configurable: true,
    });
    try {
      fetchMock.mockImplementation(() =>
        Promise.resolve(jsonResponse({ items: [] })),
      );
      const caller = new AbortController();
      await requestJson("/api/compute/inputs/", { signal: caller.signal });
      await api.resources({});
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(capturedRequest(fetchMock, 0).signal.aborted).toBe(false);
      expect(capturedRequest(fetchMock, 1).headers.get("X-Project-Id")).toBe(
        "1",
      );
    } finally {
      Object.defineProperty(AbortSignal, "any", {
        value: original,
        configurable: true,
      });
    }
  });

  it.each(["1", "9", "all"])(
    "uses the explicit upload destination throughout the flow while browsing %s",
    async (browsing) => {
      setActiveProject(browsing);
      fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({})));
      const file = new File(["name,value\nA,1\n"], "survey.csv", {
        type: "text/csv",
      });
      const table = {
        name: "调查表",
        tableName: "survey",
        importMode: "table" as const,
        domainType: "other" as const,
      };
      const vector = {
        name: "矢量",
        tableName: "survey",
        sourceLayerName: "survey",
        domainType: "vector" as const,
        categoryCode: "spatial",
      };
      await api.importPreview(file, undefined, 2);
      await api.importValidate(file, table, 2);
      await api.importCommit(file, table, 2);
      await api.previewVectorImport(file, undefined, 2);
      await api.validateVectorImport(file, vector, 2);
      await api.commitVectorImport(file, vector, 2);
      await api.previewRasterImport([file], file.name, 2);
      await api.importRaster([file], "调查栅格", undefined, 2);
      await api.rasterJob("test-job", { projectTagId: 2 });
      await api.createResultArtifact(
        file,
        {
          name: "成果",
          sourceType: "direct_import",
          resultType: "table",
          categoryCode: "non_spatial",
          accessGroupIds: [],
        },
        2,
      );
      expect(fetchMock).toHaveBeenCalledTimes(10);
      for (let index = 0; index < 10; index++) {
        expect(
          capturedRequest(fetchMock, index).headers.get("X-Project-Id"),
        ).toBe("2");
      }
    },
  );

  it("sends JSON POST requests with CSRF token and included credentials", async () => {
    setTestCookie("csrftoken=secure%20token");
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ user: { id: 1 }, active: true })),
    );

    await api.login("tester", "pass12345", true);

    const request = capturedRequest(fetchMock);
    const headers = request.headers;
    expect(requestPath(request)).toBe("/api/auth/login/");
    expect(request.method).toBe("POST");
    expect(request.credentials).toBe("include");
    expect(headers.get("X-CSRFToken")).toBe("secure token");
    expect(headers.get("Accept-Language")).toBe("zh-CN");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(JSON.parse(await request.clone().text())).toEqual({
      username: "tester",
      password: "pass12345",
      remember: true,
    });
    const pageRequest = capturedRequest(fetchMock, 1);
    expect(requestPath(pageRequest)).toBe("/api/auth/browser-session/");
    expect(pageRequest.credentials).toBe("include");
    expect(pageRequest.headers.get("X-CSRFToken")).toBe("secure token");
    expect(JSON.parse(await pageRequest.clone().text())).toMatchObject({
      action: "start",
      sequence: 1,
    });
  });

  it("submits confirmed resource deletion with an explicit project and returns actual item results", async () => {
    setActiveProject("8");
    setTestCookie("csrftoken=delete-token");
    const outcome = {
      items: [
        {
          resourceId: 10,
          name: "临时调查表",
          status: "deleted",
          detail: "已删除",
        },
        {
          resourceId: 11,
          name: "计算输入",
          status: "blocked",
          detail: "被任务引用",
        },
      ],
      deletedIds: [10],
      deletedCount: 1,
      failedCount: 1,
    };
    fetchMock.mockResolvedValue(jsonResponse(outcome));
    const result = await api.deleteResources(
      { resourceIds: [10, 11], confirmed: true },
      "6",
    );
    const request = capturedRequest(fetchMock);
    expect(requestPath(request)).toBe("/api/catalog/resources/delete/");
    expect(request.method).toBe("POST");
    expect(request.headers.get("X-Project-Id")).toBe("6");
    expect(request.headers.get("X-CSRFToken")).toBe("delete-token");
    expect(JSON.parse(await request.clone().text())).toEqual({
      resourceIds: [10, 11],
      confirmed: true,
    });
    expect(result).toEqual(outcome);
  });

  it("sends the selected English locale and localizes known legacy errors", async () => {
    await setLocale("en-US");
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "账号或密码错误" }, { status: 400 }),
    );

    await expect(api.login("tester", "wrong", false)).rejects.toMatchObject({
      message: "Incorrect account or password",
    });
    expect(capturedRequest(fetchMock).headers.get("Accept-Language")).toBe(
      "en-US",
    );
  });

  it("does not force JSON content type for FormData uploads", async () => {
    setTestCookie("csrftoken=form-token");
    fetchMock.mockResolvedValue(
      jsonResponse({
        columns: [],
        rows: [],
        rowCount: 0,
        suggestedTableName: "survey",
        suggestedName: "survey",
        detected: {
          isGeographic: false,
          longitudeColumn: null,
          latitudeColumn: null,
          coordinateStats: null,
          validationIssues: [],
        },
        limitations: [],
      }),
    );

    await api.importPreview(
      new File(["name\nA\n"], "survey.csv", { type: "text/csv" }),
    );

    const request = capturedRequest(fetchMock);
    const headers = request.headers;
    const body = await request.clone().formData();
    const contentType = headers.get("Content-Type");
    expect(body.get("file")).toBeInstanceOf(File);
    expect(headers.get("X-CSRFToken")).toBe("form-token");
    expect(
      contentType === null || contentType.startsWith("multipart/form-data"),
    ).toBe(true);
  });

  it("throws ApiError with server detail for JSON errors", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "无权访问该数据资源" }, { status: 403 }),
    );

    let capturedError: unknown;
    try {
      await api.layers();
    } catch (error) {
      capturedError = error;
    }

    expect(capturedError).toBeInstanceOf(ApiError);
    expect(capturedError).toMatchObject({
      status: 403,
      message: "无权访问该数据资源",
      data: { detail: "无权访问该数据资源" },
    });
  });

  it("notifies once when concurrent business requests report an expired session", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ detail: "请先登录" }, { status: 401 })),
    );
    let finishRefresh: (() => void) | undefined;
    const refresh = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finishRefresh = resolve;
        }),
    );
    registerForbiddenHandler(refresh);

    const requests = [api.layers(), api.layers()];
    await Promise.allSettled(requests);

    expect(refresh).toHaveBeenCalledTimes(1);
    finishRefresh?.();
    await Promise.resolve();
  });

  it("does not treat expected authentication 401 responses as session expiry", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ detail: "请先登录" }, { status: 401 })),
    );
    const refresh = vi.fn();
    registerForbiddenHandler(refresh);

    await expect(api.me()).rejects.toMatchObject({ status: 401 });
    await expect(api.login("missing", "wrong", false)).rejects.toMatchObject({
      status: 401,
    });

    expect(refresh).not.toHaveBeenCalled();
  });

  it("does not surface full HTML debug pages as the error message", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        "<!DOCTYPE html><html><head><title>OperationalError at /api/admin/data/resources/</title></head><body>debug</body></html>",
        {
          status: 500,
          headers: { "Content-Type": "text/html" },
        },
      ),
    );

    await expect(api.adminDataResources()).rejects.toMatchObject({
      status: 500,
      message:
        "平台处理时出错，本次操作没有完成。请稍后重试；如果一直出现，请联系管理员。（错误代码 500）",
    });
  });

  it("uses data-resource endpoints for registered resources", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    const resource = {
      id: 7,
      name: "样地资源",
      dataType: "vector",
    } as ResourceListItem;

    await api.resourceProfile(resource);

    expect(requestPath(capturedRequest(fetchMock))).toBe(
      "/api/catalog/resources/7/profile/",
    );
  });

  it("serializes import validation payload into multipart form data", async () => {
    setTestCookie("csrftoken=validate-token");
    fetchMock.mockResolvedValue(
      jsonResponse({
        coordinateStats: {
          totalRows: 3,
          validRows: 3,
          missingRows: 0,
          errorMinMeters: 0.05,
          errorMaxMeters: 0.55,
        },
        validationIssues: [],
        duplicateTarget: null,
      }),
    );

    await api.importValidate(
      new File(["sample_id,lon,lat\nTP-1,87.600,43.800\n"], "points.csv", {
        type: "text/csv",
      }),
      {
        importMode: "geographic",
        tableName: "tarim_poplar_monitoring_2026",
        longitudeColumn: "lon",
        latitudeColumn: "lat",
      },
    );

    const request = capturedRequest(fetchMock);
    const body = await request.clone().formData();
    expect(requestPath(request)).toBe("/api/catalog/import/validate/");
    expect(request.method).toBe("POST");
    expect(request.headers.get("X-CSRFToken")).toBe("validate-token");
    expect(JSON.parse(String(body.get("payload")))).toEqual({
      importMode: "geographic",
      tableName: "tarim_poplar_monitoring_2026",
      longitudeColumn: "lon",
      latitudeColumn: "lat",
    });
  });

  it("serializes vector import payloads through generated multipart endpoints", async () => {
    setTestCookie("csrftoken=vector-token");
    fetchMock.mockResolvedValue(
      jsonResponse({
        mode: "vector",
        resourceId: 8,
        resourceName: "新疆自治区边界",
        vectorDatasetId: 3,
        layerId: 9,
        layerName: "xinjiang_boundary",
        sourceLayerName: "boundary",
        importedFeatures: 1,
        skippedFeatures: 0,
        bounds: [73.5, 34.3, 96.3, 49.1],
        geometryType: "Polygon",
        coordinateSystem: "EPSG:4326",
        sourceEncoding: "GB18030",
        validationIssues: [],
      }),
    );

    await api.commitVectorImport(
      new File(["vector"], "boundary.zip", { type: "application/zip" }),
      {
        name: "新疆自治区边界",
        domainType: "vector",
        sourceLayerName: "boundary",
        tableName: "xinjiang_boundary",
        encoding: "GB18030",
        sourceCrs: null,
        repairInvalidGeometries: false,
        skipInvalidGeometries: false,
        duplicateConfirmed: false,
        accessGroupIds: [],
        fieldMetadata: { Name: "名称" },
      },
    );

    const request = capturedRequest(fetchMock);
    const body = await request.clone().formData();
    expect(requestPath(request)).toBe("/api/catalog/vector-import/commit/");
    expect(request.headers.get("X-CSRFToken")).toBe("vector-token");
    expect(JSON.parse(String(body.get("payload")))).toMatchObject({
      domainType: "vector",
      sourceLayerName: "boundary",
      encoding: "GB18030",
    });
  });

  it("uploads raster packages with a selected primary file", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        primaryFileName: "scene.dat",
        sourceFormat: "ENVI",
        files: [],
        metadata: {
          size: [512, 512],
          driver: "ENVI",
          coordinateSystem: 32645,
          bands: [],
        },
        bounds4326: [88, 40, 88.1, 40.1],
        defaultRules: { mode: "gray", bands: [1] },
        suggestedName: "scene",
        rasterKind: "continuous",
        resampling: "bilinear",
        warnings: [],
      }),
    );

    await api.previewRasterImport(
      [new File(["data"], "scene.dat"), new File(["ENVI"], "scene.hdr")],
      "scene.dat",
    );

    const request = capturedRequest(fetchMock);
    const body = await request.clone().formData();
    expect(requestPath(request)).toBe("/api/raster/import/preview/");
    expect(body.getAll("files")).toHaveLength(2);
    expect(body.get("primaryFileName")).toBe("scene.dat");
  });

  it("serializes raster import configuration with all package files", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        id: "raster-import-job",
        kind: "import",
        status: "queued",
        stage: "queued",
        progressPercent: 0,
        messages: [],
        result: null,
        error: "",
        startedAt: 1,
        finishedAt: null,
      }),
    );

    await api.importRaster([new File(["tif"], "worldview.tif")], {
      primaryFileName: "worldview.tif",
      name: "WorldView 影像",
      rasterKind: "imagery",
      resampling: "bilinear",
      defaultRules: { mode: "rgb", bands: [5, 3, 2] },
      accessGroupIds: [2],
    });

    const request = capturedRequest(fetchMock);
    const body = await request.clone().formData();
    expect(requestPath(request)).toBe("/api/raster/import/");
    expect(body.getAll("files")).toHaveLength(1);
    expect(JSON.parse(String(body.get("payload")))).toMatchObject({
      primaryFileName: "worldview.tif",
      rasterKind: "imagery",
      defaultRules: { bands: [5, 3, 2] },
      accessGroupIds: [2],
    });
  });

  it("keeps the selected project on the raster upload progress transport", async () => {
    setActiveProject("all");
    const header = vi.spyOn(XMLHttpRequest.prototype, "setRequestHeader");
    const send = vi
      .spyOn(XMLHttpRequest.prototype, "send")
      .mockImplementation(function (this: XMLHttpRequest) {
        Object.defineProperty(this, "status", { value: 202 });
        Object.defineProperty(this, "responseText", { value: "{}" });
        queueMicrotask(() => {
          this.dispatchEvent(new ProgressEvent("load"));
          this.dispatchEvent(new ProgressEvent("loadend"));
        });
      });
    try {
      const progress = vi.fn();
      await api.importRaster(
        [new File(["raster"], "selected.tif")],
        "归属测试",
        progress,
        3,
      );
      expect(header).toHaveBeenCalledWith("X-Project-Id", "3");
      expect(progress).toHaveBeenCalledWith(100);
    } finally {
      send.mockRestore();
      header.mockRestore();
    }
  });

  it("uses data-resource query endpoint for registered resources", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    const resource = {
      id: 7,
      name: "样地资源",
      dataType: "vector",
    } as ResourceListItem;

    await api.queryResource(resource, {
      attributeFilters: [],
      spatialFilter: null,
      limit: 10,
    });

    expect(requestPath(capturedRequest(fetchMock))).toBe(
      "/api/catalog/resources/7/query/",
    );
  });

  it("starts custom raster rendering with explicit rules mode and dataset reference", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        id: "raster-render-job",
        status: "queued",
        progressPercent: 0,
        messages: [],
      }),
    );

    await api.renderRasterAsync({
      datasetId: 2,
      layerId: null,
      rulesMode: "custom",
      rules: {
        mode: "unique",
        bands: [1],
        palette: "poplar",
        uniqueValues: [
          { value: 1, color: "#2f7d62", label: "胡杨" },
          { value: 2, color: "#d8b365", label: "其他植被" },
        ],
      },
    });

    const request = capturedRequest(fetchMock);
    expect(requestPath(request)).toBe("/api/raster/render/async/");
    expect(JSON.parse(await request.clone().text())).toMatchObject({
      datasetId: 2,
      layerId: null,
      rulesMode: "custom",
      rules: {
        mode: "unique",
        bands: [1],
      },
    });
  });

  it("extracts export filenames from content-disposition headers", async () => {
    fetchMock.mockResolvedValue(
      new Response("zip-content", {
        status: 200,
        headers: {
          "Content-Disposition": 'attachment; filename="layers.zip"',
        },
      }),
    );
    const payload = {
      epsg: 4326,
      reproject: false,
      clip: false,
      clipGeometry: null,
      items: [],
    } as ExportLayersPayload;

    const result = await api.exportLayers(payload);

    expect(result.filename).toBe("layers.zip");
    expect(await result.blob.text()).toBe("zip-content");
  });

  it("decodes UTF-8 map composition filenames instead of using the zip fallback", async () => {
    fetchMock.mockResolvedValue(
      new Response("%PDF-1.4", {
        status: 200,
        headers: {
          "Content-Type": "application/pdf",
          "Content-Disposition":
            "attachment; filename*=utf-8''text2%E4%B8%93%E9%A2%98%E5%9B%BE_V2.pdf",
        },
      }),
    );

    const result = await api.downloadMapCompositionVersion(2, 2);

    expect(result.filename).toBe("text2专题图_V2.pdf");
    expect(await result.blob.text()).toBe("%PDF-1.4");
  });
});
