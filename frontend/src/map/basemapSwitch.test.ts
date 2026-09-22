import type { Map as MapboxMap } from "mapbox-gl";
import { describe, expect, it, vi } from "vitest";
import {
  createBasemapCatalog,
  resolveBasemapDefinition,
} from "./basemapCatalog";
import { getMapState } from "./mapState";
import {
  areBasemapSourcesReady,
  basemapSwitchTimeoutMsForProvider,
  basemapErrorMessage,
  createStableReadinessGate,
  isBasemapRateLimitError,
  isHardTiandituSourceDataError,
  isHardBasemapStyleError,
  isTolerableTiandituTileError,
  isTrippedTiandituTransientError,
  mapboxBasemapSwitchTimeoutMs,
  readBasemapCamera,
  readTiandituTileFailure,
  redactBasemapCredentials,
  restoreBasemapCamera,
  restoreSelectedFeatureState,
  resolveBasemapRateLimitFallback,
  tiandituBasemapSwitchTimeoutMs,
} from "./basemapSwitch";

describe("basemapSwitch", () => {
  it("captures and restores the complete camera without fitting bounds", () => {
    const jumpTo = vi.fn();
    const map = {
      getCenter: () => ({ lng: 80.25, lat: 41.75 }),
      getZoom: () => 7.5,
      getBearing: () => 18,
      getPitch: () => 35,
      jumpTo,
    } as unknown as MapboxMap;

    const snapshot = readBasemapCamera(map);
    restoreBasemapCamera(map, snapshot);

    expect(jumpTo).toHaveBeenCalledWith({
      center: [80.25, 41.75],
      zoom: 7.5,
      bearing: 18,
      pitch: 35,
    });
  });

  it("restores the selected feature only when its source exists", () => {
    const setFeatureState = vi.fn();
    const map = {
      getSource: (sourceId: string) =>
        sourceId === "loaded-vector" ? {} : undefined,
      setFeatureState,
    } as unknown as MapboxMap;
    const target = { source: "loaded-vector", id: 7 };

    expect(restoreSelectedFeatureState(map, target)).toBe(true);
    expect(setFeatureState).toHaveBeenCalledWith(target, { selected: true });
    expect(getMapState(map).selectedFeature).toEqual(target);

    expect(restoreSelectedFeatureState(map, { source: "missing", id: 8 })).toBe(
      false,
    );
    expect(getMapState(map).selectedFeature).toBeUndefined();
  });

  it("redacts browser and server map credentials from errors", () => {
    expect(
      redactBasemapCredentials(
        "https://example.test/tile?tk=visible-value&access_token=pk.visible-token",
      ),
    ).toBe("https://example.test/tile?tk=[已隐藏]&access_token=[已隐藏]");
    expect(basemapErrorMessage({ error: new Error("HTTP 403") })).toContain(
      "HTTP 403",
    );
  });

  it("recognizes authorization failures as hard style errors", () => {
    expect(isHardBasemapStyleError(new Error("HTTP 401 Unauthorized"))).toBe(
      true,
    );
    expect(isHardBasemapStyleError(new Error("tile request timed out"))).toBe(
      false,
    );
  });

  it("tolerates only classified transient Tianditu failures below the window threshold", () => {
    const isolated = {
      sourceId: "basemap-tianditu-vector",
      error: tiandituFailure("transient", false),
    };
    const sustained = {
      sourceId: "basemap-tianditu-vector",
      error: tiandituFailure("transient", true),
    };
    const credentials = {
      sourceId: "basemap-tianditu-vector",
      error: tiandituFailure("credentials", true),
    };

    expect(isTolerableTiandituTileError(isolated)).toBe(true);
    expect(isHardBasemapStyleError(isolated)).toBe(false);
    expect(isTolerableTiandituTileError(sustained)).toBe(false);
    expect(isTrippedTiandituTransientError(sustained)).toBe(true);
    expect(isHardBasemapStyleError(sustained)).toBe(true);
    expect(isHardBasemapStyleError(credentials)).toBe(true);
    expect(readTiandituTileFailure(isolated)).toMatchObject({
      businessCode: "TEMPORARY",
      failureKind: "transient",
      layer: "vec",
      node: "t1",
      retryAfterMs: 120_000,
      status: 403,
    });
  });

  it("keeps unclassified legacy 403 errors hard", () => {
    expect(isTolerableTiandituTileError(new Error("HTTP 403 Forbidden"))).toBe(
      false,
    );
    expect(isHardBasemapStyleError(new Error("HTTP 403 Forbidden"))).toBe(true);
  });

  it.each(["img", "cia"] as const)(
    "preserves the structured Tianditu imagery layer %s",
    (layer) => {
      expect(
        readTiandituTileFailure({
          ...tiandituFailure("transient", false),
          layer,
        }),
      ).toMatchObject({ layer });
    },
  );

  it("requires the strict Tianditu provider identity and a normalized window", () => {
    const window = tiandituFailure("transient", false).failureWindow;
    expect(
      isTolerableTiandituTileError({
        failureKind: "transient",
        failureWindow: window,
      }),
    ).toBe(false);
    expect(
      isTolerableTiandituTileError({
        ...tiandituFailure("transient", false),
        failureWindow: { tripped: false },
      }),
    ).toBe(false);
  });

  it("does not escalate an unstructured Tianditu sourcedata error", () => {
    expect(
      isHardTiandituSourceDataError({
        provider: "tianditu",
        sourceDataType: "error",
        error: undefined,
      }),
    ).toBe(false);
    expect(
      isHardTiandituSourceDataError({
        provider: "tianditu",
        sourceDataType: "error",
        error: new Error("HTTP 404 Not Found"),
      }),
    ).toBe(false);
    expect(
      isHardTiandituSourceDataError({
        provider: "tianditu",
        sourceDataType: "error",
        error: tiandituFailure("transient", false),
      }),
    ).toBe(false);
    expect(
      isHardTiandituSourceDataError({
        provider: "tianditu",
        sourceDataType: "error",
        error: tiandituFailure("credentials", true),
      }),
    ).toBe(true);
    expect(
      isHardTiandituSourceDataError({
        provider: "mapbox",
        sourceDataType: "error",
        error: undefined,
      }),
    ).toBe(false);
  });

  it("recognizes rate limiting as a hard error without mistaking tile coordinates", () => {
    expect(isBasemapRateLimitError({ status: 429 })).toBe(true);
    expect(
      isBasemapRateLimitError(new Error("HTTP 429 Too Many Requests")),
    ).toBe(true);
    expect(isHardBasemapStyleError({ statusCode: "429" })).toBe(true);
    expect(basemapErrorMessage({ response: { status: 429 } })).toContain(
      "请求过于频繁",
    );
    expect(
      isBasemapRateLimitError(
        "https://t0.tianditu.gov.cn/vec_w/wmts?TILECOL=429",
      ),
    ).toBe(false);
    expect(
      isBasemapRateLimitError({
        status: 0,
        error: {
          status: 429,
          url: "https://t0.tianditu.gov.cn/vec_w/wmts?TILECOL=1",
        },
      }),
    ).toBe(true);
    expect(
      isBasemapRateLimitError("https://example.test/rate-limit/tiles"),
    ).toBe(false);
    expect(
      isBasemapRateLimitError(new Error("request was not rate limited")),
    ).toBe(false);
  });

  it("requires both Tianditu raster sources before reporting readiness", () => {
    const catalog = createBasemapCatalog({
      mapboxAccessToken: "mapbox-test-token",
      tiandituKey: "tianditu-test-key",
    });
    const definition = resolveBasemapDefinition(catalog, "tianditu-vector")!;
    const present = new Set([definition.sourceIds[0]]);
    const loaded = new Set(definition.sourceIds);
    const map = {
      getSource: (sourceId: string) =>
        present.has(sourceId) ? { id: sourceId } : undefined,
      isSourceLoaded: (sourceId: string) => loaded.has(sourceId),
    } as unknown as MapboxMap;

    expect(areBasemapSourcesReady(map, definition)).toBe(false);
    present.add(definition.sourceIds[1]);
    expect(areBasemapSourcesReady(map, definition)).toBe(true);
    loaded.delete(definition.sourceIds[1]);
    expect(areBasemapSourcesReady(map, definition)).toBe(false);
  });

  it("allows paced Tianditu loading a two-minute switch window", () => {
    expect(basemapSwitchTimeoutMsForProvider("tianditu")).toBe(
      tiandituBasemapSwitchTimeoutMs,
    );
    expect(basemapSwitchTimeoutMsForProvider("mapbox")).toBe(
      mapboxBasemapSwitchTimeoutMs,
    );
    expect(mapboxBasemapSwitchTimeoutMs).toBe(60_000);
    expect(basemapSwitchTimeoutMsForProvider("osm")).toBe(15_000);
    expect(tiandituBasemapSwitchTimeoutMs).toBe(120_000);
  });

  it("selects a stable rate-limit fallback without reselecting Tianditu", () => {
    const allAvailable = createBasemapCatalog({
      mapboxAccessToken: "mapbox-test-token",
      tiandituKey: "tianditu-test-key",
    });
    expect(
      resolveBasemapRateLimitFallback(allAvailable, "tianditu-vector")?.id,
    ).toBe("mapbox-satellite");

    const noMapbox = createBasemapCatalog({
      tiandituKey: "tianditu-test-key",
    });
    expect(
      resolveBasemapRateLimitFallback(noMapbox, "tianditu-vector")?.id,
    ).toBe("osm");
  });

  it("rechecks readiness after the stability window before committing", () => {
    vi.useFakeTimers();
    try {
      let ready = true;
      const onReady = vi.fn();
      const gate = createStableReadinessGate(() => ready, onReady, 100);

      gate.check();
      ready = false;
      vi.advanceTimersByTime(100);
      expect(onReady).not.toHaveBeenCalled();

      ready = true;
      gate.check();
      vi.advanceTimersByTime(100);
      expect(onReady).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

function tiandituFailure(
  failureKind: "credentials" | "transient",
  tripped: boolean,
) {
  return {
    name: "TiandituTileHttpError",
    provider: "tianditu",
    status: 403,
    attempts: 2,
    businessCode: "TEMPORARY",
    failureKind,
    failureWindow: {
      consecutiveFailures: tripped ? 3 : 1,
      failureCount: tripped ? 3 : 1,
      failureRate: tripped ? 0.5 : 0.1,
      sampleCount: tripped ? 6 : 10,
      tripped,
      windowMs: 15_000,
    },
    layer: "vec",
    node: "t1",
    retryAfterMs: 120_000,
  };
}
