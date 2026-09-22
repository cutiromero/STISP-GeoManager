import type { Map as MapboxMap } from "mapbox-gl";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  initialBasemapDiagnostics,
  type ActiveBasemapDescriptor,
} from "../map/basemapStatus";
import {
  areRequiredBasemapSourcesLoaded,
  BasemapSourceLoadCycle,
  BasemapTileRequestTimings,
  createStrictBasemapReadinessTimer,
  expectedBasemapSourceIds,
  loadingBasemapDiagnosticsAfterReadinessTimeout,
  probePlatformHealth,
  readyBasemapDiagnostics,
  strictBasemapReadinessTimeoutMsFor,
} from "./useBasemapStatus";

afterEach(() => {
  vi.useRealTimers();
});

describe("BasemapTileRequestTimings", () => {
  it("removes a completed or failed tile timing when it is consumed", () => {
    const timings = new BasemapTileRequestTimings();
    timings.start("tile-a", 120);

    expect(timings.finish("tile-a")).toBe(120);
    expect(timings.finish("tile-a")).toBeUndefined();
  });

  it("evicts the oldest unfinished tile at the capacity limit", () => {
    const timings = new BasemapTileRequestTimings(2);
    timings.start("tile-a", 100);
    timings.start("tile-b", 200);
    timings.start("tile-c", 300);

    expect(timings.finish("tile-a")).toBeUndefined();
    expect(timings.finish("tile-b")).toBe(200);
    expect(timings.finish("tile-c")).toBe(300);
  });
});

describe("readyBasemapDiagnostics", () => {
  it("does not replace a tile response sample with a whole-view completion time", () => {
    const current = {
      ...initialBasemapDiagnostics({
        online: true,
        effectiveType: "4g",
        rttMs: 80,
        downlinkMbps: 10,
      }),
      basemap: "loading" as const,
      basemapLatencyMs: 80,
      basemapLoadingSince: 1_000,
    };

    expect(readyBasemapDiagnostics(current, null)).toMatchObject({
      basemap: "ready",
      basemapLatencyMs: 80,
      basemapLoadingSince: null,
    });
  });
});

describe("BasemapSourceLoadCycle", () => {
  it("waits for every active source before reporting ready", () => {
    const cycle = new BasemapSourceLoadCycle(["tianditu-vec", "tianditu-cva"]);

    cycle.loading("tianditu-vec");
    cycle.loading("tianditu-cva");
    expect(cycle.loaded("tianditu-vec")).toBe(false);
    expect(cycle.loaded("tianditu-cva")).toBe(true);
  });

  it("does not let idle recover a failed load cycle", () => {
    const sources = ["tianditu-vec", "tianditu-cva"];
    const cycle = new BasemapSourceLoadCycle(sources);

    cycle.fail(sources);

    expect(cycle.hasFailure()).toBe(true);
    expect(cycle.completeFromMapLifecycle(sources)).toBe(false);
    expect(cycle.hasFailure()).toBe(true);
  });

  it("requires a complete successful round after an error", () => {
    const sources = ["tianditu-vec", "tianditu-cva"];
    const cycle = new BasemapSourceLoadCycle(sources);

    expect(cycle.loaded("tianditu-vec", sources)).toBe(false);
    cycle.fail(sources);
    expect(cycle.loaded("tianditu-cva", sources)).toBe(false);
    expect(cycle.completeFromMapLifecycle(sources)).toBe(false);
    expect(cycle.loaded("tianditu-vec", sources)).toBe(true);
    expect(cycle.hasFailure()).toBe(false);
  });

  it("allows an explicit retry to begin a fresh recovery cycle", () => {
    const sources = ["tianditu-vec", "tianditu-cva"];
    const cycle = new BasemapSourceLoadCycle(sources);
    cycle.fail(sources);

    cycle.reset(sources);

    expect(cycle.hasFailure()).toBe(false);
    expect(cycle.completeFromMapLifecycle(sources)).toBe(true);
  });
});

describe("strict basemap source readiness", () => {
  const strictBasemap: ActiveBasemapDescriptor = {
    id: "tianditu-vector",
    generation: 1,
    sourceIds: ["tianditu-vec", "tianditu-cva"],
    requireAllSourceIds: true,
    readinessTimeoutMs: 45_000,
    resourceMarkers: ["tianditu.gov.cn"],
  };

  it("keeps the complete declared source contract when one source is absent", () => {
    const present = new Set(["tianditu-vec"]);
    const loaded = new Set(["tianditu-vec"]);
    const map = {
      getStyle: () => ({ sources: { "tianditu-vec": {} } }),
      getSource: (sourceId: string) =>
        present.has(sourceId) ? { id: sourceId } : undefined,
      isSourceLoaded: (sourceId: string) => loaded.has(sourceId),
    } as unknown as MapboxMap;

    expect(expectedBasemapSourceIds(map, strictBasemap)).toEqual([
      "tianditu-vec",
      "tianditu-cva",
    ]);
    expect(areRequiredBasemapSourcesLoaded(map, strictBasemap)).toBe(false);

    present.add("tianditu-cva");
    expect(areRequiredBasemapSourcesLoaded(map, strictBasemap)).toBe(false);
    loaded.add("tianditu-cva");
    expect(areRequiredBasemapSourcesLoaded(map, strictBasemap)).toBe(true);
  });

  it("preserves candidate-source behavior for non-strict Mapbox styles", () => {
    const mapboxBasemap: ActiveBasemapDescriptor = {
      id: "mapbox-satellite",
      generation: 1,
      sourceIds: ["composite", "mapbox-satellite", "mapbox"],
      resourceMarkers: ["api.mapbox.com"],
    };
    const map = {
      getStyle: () => ({ sources: { composite: {}, business: {} } }),
    } as unknown as MapboxMap;

    expect(expectedBasemapSourceIds(map, mapboxBasemap)).toEqual(["composite"]);
    expect(areRequiredBasemapSourcesLoaded(map, mapboxBasemap)).toBe(true);
  });

  it("uses a provider-specific readiness timeout for paced tile services", () => {
    expect(strictBasemapReadinessTimeoutMsFor(strictBasemap)).toBe(45_000);
    expect(strictBasemapReadinessTimeoutMsFor(undefined)).toBe(15_000);
    expect(
      strictBasemapReadinessTimeoutMsFor({
        ...strictBasemap,
        readinessTimeoutMs: Number.NaN,
      }),
    ).toBe(15_000);
  });
});

describe("StrictBasemapReadinessTimer", () => {
  it("clears the pending timeout when an idle-ready path settles", async () => {
    vi.useFakeTimers();
    const onReady = vi.fn();
    const onTimedOut = vi.fn();
    const timer = createStrictBasemapReadinessTimer({
      isCurrentScope: () => true,
      sourcesReady: () => false,
      onReady,
      onTimedOut,
      timeoutMs: 1_000,
    });

    timer.enterLoading();
    timer.settle();
    await vi.advanceTimersByTimeAsync(1_000);

    expect(onReady).not.toHaveBeenCalled();
    expect(onTimedOut).not.toHaveBeenCalled();
  });

  it("arms a new timeout for a later strict loading cycle", async () => {
    vi.useFakeTimers();
    const onTimedOut = vi.fn();
    const timer = createStrictBasemapReadinessTimer({
      isCurrentScope: () => true,
      sourcesReady: () => false,
      onReady: vi.fn(),
      onTimedOut,
      timeoutMs: 1_000,
    });

    timer.enterLoading();
    timer.settle();
    timer.enterLoading();
    await vi.advanceTimersByTimeAsync(999);
    expect(onTimedOut).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);

    expect(onTimedOut).toHaveBeenCalledOnce();
  });

  it("restarts the timeout for an explicit refresh", async () => {
    vi.useFakeTimers();
    const onTimedOut = vi.fn();
    const timer = createStrictBasemapReadinessTimer({
      isCurrentScope: () => true,
      sourcesReady: () => false,
      onReady: vi.fn(),
      onTimedOut,
      timeoutMs: 1_000,
    });

    timer.enterLoading();
    await vi.advanceTimersByTimeAsync(600);
    timer.restartLoading();
    await vi.advanceTimersByTimeAsync(600);
    expect(onTimedOut).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(400);

    expect(onTimedOut).toHaveBeenCalledOnce();
  });

  it("converges to ready when required sources are loaded at timeout", async () => {
    vi.useFakeTimers();
    const onReady = vi.fn();
    const onTimedOut = vi.fn();
    const timer = createStrictBasemapReadinessTimer({
      isCurrentScope: () => true,
      sourcesReady: () => true,
      onReady,
      onTimedOut,
      timeoutMs: 1_000,
    });

    timer.enterLoading();
    await vi.advanceTimersByTimeAsync(1_000);

    expect(onReady).toHaveBeenCalledOnce();
    expect(onTimedOut).not.toHaveBeenCalled();
  });

  it("does not fail a paced basemap at the legacy 15-second boundary", async () => {
    vi.useFakeTimers();
    const onTimedOut = vi.fn();
    const pacedBasemap: ActiveBasemapDescriptor = {
      id: "tianditu-vector",
      generation: 1,
      sourceIds: ["tianditu-vec", "tianditu-cva"],
      requireAllSourceIds: true,
      readinessTimeoutMs: 45_000,
      resourceMarkers: ["tianditu.gov.cn"],
    };
    const timer = createStrictBasemapReadinessTimer({
      isCurrentScope: () => true,
      sourcesReady: () => false,
      onReady: vi.fn(),
      onTimedOut,
      timeoutMs: strictBasemapReadinessTimeoutMsFor(pacedBasemap),
    });

    timer.enterLoading();
    await vi.advanceTimersByTimeAsync(15_000);
    expect(onTimedOut).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(29_999);
    expect(onTimedOut).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);

    expect(onTimedOut).toHaveBeenCalledOnce();
  });

  it("ignores a timeout from an obsolete basemap generation", async () => {
    vi.useFakeTimers();
    let generation = 1;
    const onReady = vi.fn();
    const onTimedOut = vi.fn();
    const timer = createStrictBasemapReadinessTimer({
      isCurrentScope: () => generation === 1,
      sourcesReady: () => false,
      onReady,
      onTimedOut,
      timeoutMs: 1_000,
    });

    timer.enterLoading();
    generation = 2;
    await vi.advanceTimersByTimeAsync(1_000);

    expect(onReady).not.toHaveBeenCalled();
    expect(onTimedOut).not.toHaveBeenCalled();
  });
});

describe("loadingBasemapDiagnosticsAfterReadinessTimeout", () => {
  const network = {
    online: true,
    effectiveType: "4g",
    rttMs: 80,
    downlinkMbps: 10,
  };

  it("keeps a slow visible basemap loading without recording a failure", () => {
    const current = {
      ...initialBasemapDiagnostics(network),
      basemap: "loading" as const,
      basemapLoadingSince: 1_000,
    };

    expect(
      loadingBasemapDiagnosticsAfterReadinessTimeout(current, 45_000, 60_000),
    ).toMatchObject({
      basemap: "loading",
      basemapLoadingSince: 1_000,
      recentBasemapFailures: 0,
    });
  });

  it("does not overwrite an explicit tile failure", () => {
    const current = {
      ...initialBasemapDiagnostics(network),
      basemap: "failed" as const,
      recentBasemapFailures: 1,
    };

    expect(
      loadingBasemapDiagnosticsAfterReadinessTimeout(current, 45_000, 60_000),
    ).toBe(current);
  });
});

describe("probePlatformHealth", () => {
  it("reports a real request timeout as unreachable", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        }),
    );

    const resultPromise = probePlatformHealth({
      fetchImpl,
      timeoutMs: 5_000,
    });
    await vi.advanceTimersByTimeAsync(5_000);

    await expect(resultPromise).resolves.toEqual({
      status: "unreachable",
      latencyMs: null,
    });
  });

  it("keeps a superseded request distinct from a timeout", async () => {
    const externalController = new AbortController();
    const fetchImpl = vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        }),
    );

    const resultPromise = probePlatformHealth({
      fetchImpl,
      signal: externalController.signal,
    });
    externalController.abort();

    await expect(resultPromise).resolves.toEqual({
      status: "cancelled",
      latencyMs: null,
    });
  });

  it("returns measured latency for a successful health response", async () => {
    const samples = [100, 145];
    const result = await probePlatformHealth({
      fetchImpl: vi.fn(async () => new Response("{}", { status: 200 })),
      now: () => samples.shift() ?? 145,
    });

    expect(result).toEqual({ status: "reachable", latencyMs: 45 });
  });
});
