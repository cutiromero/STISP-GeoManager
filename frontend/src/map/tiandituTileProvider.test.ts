import { afterEach, describe, expect, it, vi } from "vitest";
import {
  RequestStartScheduler,
  TiandituFailureWindow,
  TiandituNodeCircuitBreaker,
  TiandituTileProvider,
  parseRetryAfterMs,
} from "./tiandituTileProvider.js";

afterEach(() => {
  vi.useRealTimers();
});

describe("TiandituTileProvider", () => {
  it.each([
    ["img", 16],
    ["cia", 18],
    ["vec", 18],
    ["cva", 18],
  ] as const)(
    "returns complete %s TileJSON metadata with maxzoom %s",
    async (layer, maxzoom) => {
      const rawKey = "metadata key/+?&";
      const fetchImpl = vi.fn();

      const metadata = await provider({ fetchImpl }).load({
        request: { url: tiandituMetadataUrl(layer, rawKey) },
      });

      expect(fetchImpl).not.toHaveBeenCalled();
      expect(metadata).toMatchObject({
        attribution: "© 天地图",
        maxzoom,
        minzoom: 0,
        scheme: "xyz",
        tileSize: 256,
        tilejson: "3.0.0",
      });
      expect(metadata.tiles).toHaveLength(8);
      expect(
        metadata.tiles.every(
          (url: string, index: number) =>
            url.startsWith(
              `https://t${index}.tianditu.gov.cn/${layer}_w/wmts?`,
            ) &&
            url.includes(`LAYER=${layer}`) &&
            url.includes(`tk=${encodeURIComponent(rawKey)}`) &&
            !url.includes(rawKey),
        ),
      ).toBe(true);
    },
  );

  it("rejects invalid source metadata without leaking its key", async () => {
    const secret = "must-not-appear";
    const load = provider({}).load({
      request: {
        url: `https://example.test/img_w/wmts?LAYER=img&tk=${secret}`,
      },
    });

    await expect(load).rejects.toThrow(/metadata request is invalid/);
    await expect(load).rejects.not.toThrow(new RegExp(secret));
  });

  it("overrides same-origin policy so browser keys can send the platform origin", async () => {
    const fetchImpl = vi.fn(async (_url: string, init: RequestInit) => {
      expect(init.referrerPolicy).toBe("strict-origin-when-cross-origin");
      return tileResponse(200);
    });

    await provider({
      scheduler: new RequestStartScheduler({ minStartIntervalMs: 0 }),
      fetchImpl,
    }).loadTile(tile(1), {
      request: {
        url: "https://tiles.example.test/vec",
        referrerPolicy: "same-origin",
      },
      signal: new AbortController().signal,
    });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("classifies a domain credential error without retrying or leaking details", async () => {
    const fetchImpl = vi.fn(async () =>
      errorResponse(
        403,
        JSON.stringify({
          code: "301007",
          message: "domain whitelist rejected tk=must-not-appear",
        }),
      ),
    );
    const load = provider({ fetchImpl }).loadTile(
      tile(1),
      tiandituLoadOptions("t0", "vec", new AbortController()),
    );

    await expect(load).rejects.toMatchObject({
      attempts: 1,
      businessCode: "301007",
      failureKind: "credentials",
      failureWindow: { tripped: true },
      layer: "vec",
      node: "t0",
      retryable: false,
      status: 403,
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await expect(load).rejects.not.toThrow(/must-not-appear/);
  });

  it.each(["img", "cia"] as const)(
    "reports the Tianditu imagery layer %s in structured failures",
    async (layer) => {
      const load = provider({
        fetchImpl: vi.fn(async () =>
          errorResponse(403, JSON.stringify({ code: "301007" })),
        ),
      }).loadTile(
        tile(1),
        tiandituLoadOptions("t0", layer, new AbortController()),
      );

      await expect(load).rejects.toMatchObject({
        failureKind: "credentials",
        layer,
      });
    },
  );

  it("confirms a 301018 key-type response once on an alternate node", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        errorResponse(403, JSON.stringify({ code: "301018" })),
      )
      .mockResolvedValueOnce(tileResponse(200));
    const load = provider({ fetchImpl }).loadTile(
      tile(1),
      tiandituLoadOptions("t0", "vec", new AbortController()),
    );

    await vi.runAllTimersAsync();
    await expect(load).resolves.toMatchObject({
      data: expect.any(ArrayBuffer),
    });
    expect(
      fetchImpl.mock.calls.map(([url]) => new URL(String(url)).hostname),
    ).toEqual(["t0.tianditu.gov.cn", "t1.tianditu.gov.cn"]);
  });

  it("raises one hard credential failure when 301018 is confirmed", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(async () =>
      errorResponse(
        403,
        JSON.stringify({
          code: "301018",
          message: "unsupported key type tk=must-not-appear",
        }),
      ),
    );
    const load = provider({ fetchImpl }).loadTile(
      tile(1),
      tiandituLoadOptions("t0", "vec", new AbortController()),
    );
    const rejection = expect(load).rejects.toMatchObject({
      attempts: 2,
      businessCode: "301018",
      failureKind: "credentials",
      failureWindow: { tripped: true },
      node: "t1",
      status: 403,
    });

    await vi.runAllTimersAsync();
    await rejection;
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    await expect(load).rejects.not.toThrow(/must-not-appear/);
  });

  it.each([
    ["JSON status", '{"status":"301007"}', "301007"],
    ["XML status", "<response><status>301018</status></response>", "301018"],
    ["plain text", "service rejected request: 301007", "301007"],
  ])(
    "extracts credential business codes from %s",
    async (_label, body, code) => {
      const load = provider({
        fetchImpl: vi.fn(async () => errorResponse(403, body)),
      }).loadTile(
        tile(1),
        tiandituLoadOptions("t0", "vec", new AbortController()),
      );

      await expect(load).rejects.toMatchObject({
        businessCode: code,
        failureKind: "credentials",
      });
    },
  );

  it("does not treat generic domain or permission wording as credentials", async () => {
    const load = provider({
      fetchImpl: vi.fn(async () =>
        errorResponse(
          403,
          "upstream domain permission temporarily denied 来源 权限",
        ),
      ),
      maxRetries: 0,
    }).loadTile(
      tile(1),
      tiandituLoadOptions("t0", "vec", new AbortController()),
    );

    await expect(load).rejects.toMatchObject({
      businessCode: null,
      failureKind: "transient",
      failureWindow: { tripped: false },
    });
  });

  it("falls back safely when reading a 403 response body fails", async () => {
    const fetchImpl = vi.fn(async () => ({
      ...errorResponse(403, ""),
      text: async () => {
        throw new Error("unreadable response tk=must-not-appear");
      },
    })) as unknown as typeof fetch;
    const load = provider({ fetchImpl, maxRetries: 0 }).loadTile(
      tile(1),
      tiandituLoadOptions("t0", "vec", new AbortController()),
    );

    await expect(load).rejects.toMatchObject({
      businessCode: null,
      failureKind: "transient",
    });
    await expect(load).rejects.not.toThrow(/must-not-appear/);
  });

  it("does not expose an upstream status phrase", async () => {
    const response = errorResponse(403, "temporary forbidden");
    (response as unknown as { statusText: string }).statusText =
      "Forbidden tk=must-not-appear";
    const load = provider({
      fetchImpl: vi.fn(async () => response),
      maxRetries: 0,
    }).loadTile(
      tile(1),
      tiandituLoadOptions("t0", "vec", new AbortController()),
    );

    await expect(load).rejects.toMatchObject({ failureKind: "transient" });
    await expect(load).rejects.not.toThrow(/must-not-appear/);
  });

  it("retries an unclassified 403 once on an alternate healthy node", async () => {
    vi.useFakeTimers();
    const failureWindow = new TiandituFailureWindow();
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(errorResponse(403, "temporary forbidden"))
      .mockResolvedValueOnce(tileResponse(200));
    const load = provider({
      failureWindow,
      fetchImpl,
      random: () => 0.5,
      transientRetryDelayMs: 250,
    }).loadTile(
      tile(1),
      tiandituLoadOptions("t0", "cva", new AbortController()),
    );

    await vi.advanceTimersByTimeAsync(249);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await expect(load).resolves.toMatchObject({
      data: expect.any(ArrayBuffer),
    });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(
      fetchImpl.mock.calls.map(([url]) => new URL(String(url)).hostname),
    ).toEqual(["t0.tianditu.gov.cn", "t1.tianditu.gov.cn"]);
    expect(failureWindow.snapshot()).toMatchObject({
      failureCount: 0,
      sampleCount: 1,
      tripped: false,
    });
  });

  it("retries an upstream 404 on alternate nodes and keeps its structured failure visible", async () => {
    vi.useFakeTimers();
    const failureWindow = new TiandituFailureWindow();
    const nodeCircuit = new TiandituNodeCircuitBreaker();
    const scheduler = new RequestStartScheduler({ minStartIntervalMs: 0 });
    const fetchImpl = vi.fn(async () => errorResponse(404, "not found"));
    const load = provider({
      failureWindow,
      fetchImpl,
      nodeCircuit,
      random: () => 0.5,
      scheduler,
    }).loadTile(
      tile(1),
      tiandituLoadOptions("t0", "vec", new AbortController()),
    );
    const rejection = expect(load).rejects.toMatchObject({
      attempts: 2,
      failureKind: "transient",
      failureReason: "missing-tile",
      failureWindow: {
        failureCount: 1,
        sampleCount: 1,
        tripped: false,
      },
      status: 0,
      statusCode: 0,
      upstreamStatus: 404,
    });

    await vi.runAllTimersAsync();
    await rejection;
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(nodeCircuit.nodes.size).toBe(0);
    expect(scheduler.rateLimitPenaltyUntil).toBe(0);
    scheduler.dispose();
  });

  it("does not trip the whole basemap on only three missing tiles", async () => {
    const failureWindow = new TiandituFailureWindow();
    const fetchImpl = vi.fn(async () => errorResponse(404, "not found"));
    const tileProvider = provider({
      delay: async () => undefined,
      failureWindow,
      fetchImpl,
      maxRetries: 0,
    });

    for (let index = 0; index < 3; index += 1) {
      await expect(
        tileProvider.loadTile(
          tile(index),
          tiandituLoadOptions("t0", "vec", new AbortController()),
        ),
      ).rejects.toMatchObject({
        failureReason: "missing-tile",
        failureWindow: {
          consecutiveFailures: 0,
          tripped: false,
        },
      });
    }

    expect(failureWindow.snapshot()).toMatchObject({
      consecutiveFailures: 0,
      failureCount: 3,
      sampleCount: 3,
      tripped: false,
    });

    for (let index = 3; index < 8; index += 1) {
      await expect(
        tileProvider.loadTile(
          tile(index),
          tiandituLoadOptions("t0", "vec", new AbortController()),
        ),
      ).rejects.toMatchObject({ failureReason: "missing-tile" });
    }

    expect(failureWindow.snapshot()).toMatchObject({
      consecutiveFailures: 0,
      failureCount: 8,
      failureRate: 1,
      sampleCount: 8,
      tripped: true,
    });
  });

  it("treats a missing tile as a break in a transient failure streak", () => {
    const failureWindow = new TiandituFailureWindow();

    failureWindow.recordFailure();
    failureWindow.recordFailure();
    failureWindow.recordFailure({ countsTowardConsecutive: false });
    const snapshot = failureWindow.recordFailure();

    expect(snapshot).toMatchObject({
      consecutiveFailures: 1,
      failureCount: 4,
      sampleCount: 4,
      tripped: false,
    });
  });

  it("records one logical failure after the bounded 403 retry is exhausted", async () => {
    vi.useFakeTimers();
    const failureWindow = new TiandituFailureWindow();
    const fetchImpl = vi.fn(async () =>
      errorResponse(403, "temporary forbidden"),
    );
    const load = provider({
      failureWindow,
      fetchImpl,
      random: () => 0.5,
      transientRetryDelayMs: 10,
    }).loadTile(
      tile(1),
      tiandituLoadOptions("t2", "vec", new AbortController()),
    );
    const rejection = expect(load).rejects.toMatchObject({
      attempts: 2,
      failureKind: "transient",
      failureWindow: {
        failureCount: 1,
        failureRate: 1,
        sampleCount: 1,
        tripped: false,
      },
      retryExhausted: true,
    });

    await vi.runAllTimersAsync();
    await rejection;
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("retries a network failure on an alternate node and records one success", async () => {
    vi.useFakeTimers();
    const failureWindow = new TiandituFailureWindow();
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch secret-url"))
      .mockResolvedValueOnce(tileResponse(200));
    const load = provider({
      failureWindow,
      fetchImpl,
      random: () => 0.5,
      transientRetryDelayMs: 250,
    }).loadTile(
      tile(1),
      tiandituLoadOptions("t0", "vec", new AbortController()),
    );

    await vi.advanceTimersByTimeAsync(249);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await expect(load).resolves.toMatchObject({
      data: expect.any(ArrayBuffer),
    });
    expect(
      fetchImpl.mock.calls.map(([url]) => new URL(String(url)).hostname),
    ).toEqual(["t0.tianditu.gov.cn", "t1.tianditu.gov.cn"]);
    expect(failureWindow.snapshot()).toMatchObject({
      failureCount: 0,
      sampleCount: 1,
    });
  });

  it("raises one redacted logical failure after bounded network retries", async () => {
    vi.useFakeTimers();
    const failureWindow = new TiandituFailureWindow();
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("Failed to fetch https://example.test/?tk=secret");
    });
    const load = provider({
      failureWindow,
      fetchImpl,
      maxRetries: 2,
      random: () => 0.5,
      transientRetryDelayMs: 10,
    }).loadTile(
      tile(1),
      tiandituLoadOptions("t0", "cva", new AbortController()),
    );
    const rejection = expect(load).rejects.toMatchObject({
      attempts: 3,
      businessCode: null,
      failureKind: "transient",
      failureReason: "network-error",
      failureWindow: { failureCount: 1, sampleCount: 1 },
    });

    await vi.runAllTimersAsync();
    await rejection;
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect(
      fetchImpl.mock.calls.map(([url]) => new URL(String(url)).hostname),
    ).toEqual([
      "t0.tianditu.gov.cn",
      "t1.tianditu.gov.cn",
      "t2.tianditu.gov.cn",
    ]);
    await expect(load).rejects.not.toThrow(/secret/);
  });

  it("times out stalled fetches, releases the queue, and retries alternate nodes", async () => {
    vi.useFakeTimers();
    const scheduler = new RequestStartScheduler({ minStartIntervalMs: 0 });
    const failureWindow = new TiandituFailureWindow();
    const fetchImpl = vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
        }),
    );
    const load = provider({
      failureWindow,
      fetchImpl,
      maxRetries: 2,
      requestTimeoutMs: 1_000,
      scheduler,
      transientRetryDelayMs: 10,
    }).loadTile(
      tile(1),
      tiandituLoadOptions("t0", "vec", new AbortController()),
    );
    const rejection = expect(load).rejects.toMatchObject({
      attempts: 3,
      failureKind: "transient",
      failureReason: "request-timeout",
      failureWindow: { failureCount: 1, sampleCount: 1 },
    });

    await vi.runAllTimersAsync();
    await rejection;

    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect(scheduler.activeRequests).toBe(0);
    expect(
      fetchImpl.mock.calls.map(([url]) => new URL(String(url)).hostname),
    ).toEqual([
      "t0.tianditu.gov.cn",
      "t1.tianditu.gov.cn",
      "t2.tianditu.gov.cn",
    ]);
    scheduler.dispose();
  });

  it("retries transient 503 responses across distinct nodes", async () => {
    vi.useFakeTimers();
    const failureWindow = new TiandituFailureWindow();
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(errorResponse(503, "upstream unavailable"))
      .mockResolvedValueOnce(errorResponse(503, "upstream unavailable"))
      .mockResolvedValueOnce(tileResponse(200));
    const load = provider({
      failureWindow,
      fetchImpl,
      random: () => 0.5,
      transientRetryDelayMs: 10,
    }).loadTile(
      tile(1),
      tiandituLoadOptions("t0", "vec", new AbortController()),
    );

    await vi.runAllTimersAsync();
    await expect(load).resolves.toMatchObject({
      data: expect.any(ArrayBuffer),
    });
    expect(
      fetchImpl.mock.calls.map(([url]) => new URL(String(url)).hostname),
    ).toEqual([
      "t0.tianditu.gov.cn",
      "t1.tianditu.gov.cn",
      "t2.tianditu.gov.cn",
    ]);
    expect(failureWindow.snapshot()).toMatchObject({
      failureCount: 0,
      sampleCount: 1,
      tripped: false,
    });
  });

  it("trips only after sustained logical tile failures", () => {
    const window = new TiandituFailureWindow({
      failureRateThreshold: 0.5,
      minFailures: 3,
      minSamples: 8,
    });

    expect(window.recordFailure().tripped).toBe(false);
    expect(window.recordSuccess().tripped).toBe(false);
    expect(window.recordFailure().tripped).toBe(false);
    expect(window.recordSuccess().tripped).toBe(false);
    expect(window.recordFailure().tripped).toBe(false);
    expect(window.recordSuccess().tripped).toBe(false);
    expect(window.recordFailure().tripped).toBe(false);
    expect(window.recordSuccess()).toMatchObject({
      failureCount: 4,
      failureRate: 0.5,
      sampleCount: 8,
      tripped: true,
    });
  });

  it("recomputes consecutive failures after old samples leave the window", () => {
    let now = 0;
    const window = new TiandituFailureWindow({ now: () => now });

    window.recordFailure();
    now = 10_000;
    window.recordFailure();
    now = 20_000;
    expect(window.recordFailure()).toMatchObject({
      consecutiveFailures: 2,
      failureCount: 2,
      sampleCount: 2,
      tripped: false,
    });
  });

  it("keeps at most twelve samples and expires them after fifteen seconds", () => {
    let now = 0;
    const cappedWindow = new TiandituFailureWindow({ now: () => now });
    cappedWindow.recordFailure();
    for (let index = 1; index <= 12; index += 1) {
      now = index;
      cappedWindow.recordSuccess();
    }
    expect(cappedWindow.snapshot()).toMatchObject({
      failureCount: 0,
      sampleCount: 12,
    });

    now = 0;
    const expiringWindow = new TiandituFailureWindow({ now: () => now });
    expiringWindow.recordFailure();
    now = 15_000;
    expect(expiringWindow.snapshot()).toMatchObject({ sampleCount: 1 });
    now = 15_001;
    expect(expiringWindow.snapshot()).toMatchObject({
      consecutiveFailures: 0,
      failureCount: 0,
      sampleCount: 0,
      tripped: false,
    });
  });

  it("opens a failing node circuit and probes it again after cooldown", () => {
    let now = 1_000;
    const circuit = new TiandituNodeCircuitBreaker({
      cooldownMs: 30_000,
      failureThreshold: 2,
      failureWindowMs: 15_000,
      now: () => now,
    });
    const url = tiandituUrl("t0", "vec");

    circuit.recordFailure("t0");
    circuit.recordFailure("t0");
    expect(new URL(circuit.route(url).url).hostname).toBe("t1.tianditu.gov.cn");

    now += 30_000;
    expect(new URL(circuit.route(url).url).hostname).toBe("t0.tianditu.gov.cn");
  });

  it("does not let a late in-flight success close an open circuit", () => {
    let now = 1_000;
    const circuit = new TiandituNodeCircuitBreaker({
      cooldownMs: 30_000,
      now: () => now,
    });
    const url = tiandituUrl("t0", "vec");
    circuit.recordFailure("t0");
    circuit.recordFailure("t0");

    circuit.recordSuccess("t0");
    expect(new URL(circuit.route(url).url).hostname).toBe("t1.tianditu.gov.cn");

    now += 30_000;
    expect(new URL(circuit.route(url).url).hostname).toBe("t0.tianditu.gov.cn");
    circuit.recordSuccess("t0");
    expect(new URL(circuit.route(url).url).hostname).toBe("t0.tianditu.gov.cn");
  });

  it("uses a different alternate when the original node is already open", async () => {
    vi.useFakeTimers();
    const circuit = new TiandituNodeCircuitBreaker();
    circuit.recordFailure("t0");
    circuit.recordFailure("t0");
    const fetchImpl = vi.fn(async () => errorResponse(403, "temporary"));
    const load = provider({
      fetchImpl,
      nodeCircuit: circuit,
      random: () => 0.5,
      transientRetryDelayMs: 10,
    }).loadTile(
      tile(1),
      tiandituLoadOptions("t0", "vec", new AbortController()),
    );
    const rejection = expect(load).rejects.toMatchObject({
      failureKind: "transient",
    });

    await vi.runAllTimersAsync();
    await rejection;
    expect(
      fetchImpl.mock.calls.map(([url]) => new URL(String(url)).hostname),
    ).toEqual(["t1.tianditu.gov.cn", "t2.tianditu.gov.cn"]);
  });

  it("fails locally without fetching when every node circuit is open", async () => {
    const circuit = new TiandituNodeCircuitBreaker();
    for (let index = 0; index < 8; index += 1) {
      circuit.recordFailure(`t${index}`);
      circuit.recordFailure(`t${index}`);
    }
    const fetchImpl = vi.fn(async () => tileResponse(200));
    const load = provider({ fetchImpl, nodeCircuit: circuit }).loadTile(
      tile(1),
      tiandituLoadOptions("t0", "cva", new AbortController()),
    );

    await expect(load).rejects.toMatchObject({
      attempts: 0,
      failureKind: "transient",
      failureReason: "circuit-open",
      node: null,
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("rewrites only HTTPS Tianditu node URLs", () => {
    const circuit = new TiandituNodeCircuitBreaker();
    circuit.recordFailure("t0");
    circuit.recordFailure("t0");
    const insecureUrl = tiandituUrl("t0", "vec").replace("https:", "http:");

    expect(circuit.route(insecureUrl)).toMatchObject({
      available: true,
      node: null,
      url: insecureUrl,
    });
  });

  it("paces request starts across vector and label provider instances", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    const starts: number[] = [];
    const scheduler = new RequestStartScheduler({
      maxConcurrentRequests: 4,
    });
    const fetchImpl = vi.fn(async () => {
      starts.push(Date.now());
      return tileResponse(200);
    });
    const vector = provider({ scheduler, fetchImpl });
    const labels = provider({ scheduler, fetchImpl });

    const requests = [
      vector.loadTile(tile(1), loadOptions("vec", new AbortController())),
      labels.loadTile(tile(2), loadOptions("cva", new AbortController())),
      vector.loadTile(tile(3), loadOptions("vec", new AbortController())),
    ];

    await vi.advanceTimersByTimeAsync(199);
    expect(starts).toEqual([10_000, 10_100]);
    await vi.advanceTimersByTimeAsync(1);
    await Promise.all(requests);
    expect(starts).toEqual([10_000, 10_100, 10_200]);
    scheduler.dispose();
  });

  it("allows six requests in flight when responses are slow", async () => {
    const releases: Array<(value: ArrayBuffer) => void> = [];
    const scheduler = new RequestStartScheduler({ minStartIntervalMs: 0 });
    const fetchImpl = vi.fn(async () =>
      tileResponse(
        200,
        {},
        () => new Promise<ArrayBuffer>((resolve) => releases.push(resolve)),
      ),
    );
    const tileProvider = provider({ scheduler, fetchImpl });
    const loads = Array.from({ length: 7 }, (_, index) =>
      tileProvider.loadTile(
        tile(index),
        loadOptions("vec", new AbortController()),
      ),
    );

    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(6));
    releases[0](new ArrayBuffer(0));
    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(7));
    for (const release of releases.slice(1)) release(new ArrayBuffer(0));
    await Promise.all(loads);
    scheduler.dispose();
  });

  it("pauses the shared vector and label queue after any 429", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(30_000);
    const starts: Array<{ layer: string; at: number }> = [];
    let vectorAttempts = 0;
    const scheduler = new RequestStartScheduler({
      minStartIntervalMs: 100,
      maxConcurrentRequests: 6,
    });
    const fetchImpl = vi.fn(async (url: string) => {
      const layer = url.includes("/cva") ? "cva" : "vec";
      starts.push({ layer, at: Date.now() });
      if (layer === "vec" && vectorAttempts++ === 0) {
        return tileResponse(429, { "retry-after": "1" });
      }
      return tileResponse(200);
    });
    const vector = provider({ scheduler, fetchImpl });
    const labels = provider({ scheduler, fetchImpl });

    const loads = [
      vector.loadTile(tile(1), loadOptions("vec", new AbortController())),
      labels.loadTile(tile(2), loadOptions("cva", new AbortController())),
    ];

    await vi.advanceTimersByTimeAsync(999);
    expect(starts).toEqual([{ layer: "vec", at: 30_000 }]);
    expect(scheduler.minStartIntervalMs).toBe(200);
    expect(scheduler.maxConcurrentRequests).toBe(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(starts).toEqual([
      { layer: "vec", at: 30_000 },
      { layer: "cva", at: 31_000 },
    ]);
    await vi.advanceTimersByTimeAsync(200);
    await Promise.all(loads);
    expect(starts).toEqual([
      { layer: "vec", at: 30_000 },
      { layer: "cva", at: 31_000 },
      { layer: "vec", at: 31_200 },
    ]);
    scheduler.dispose();
  });

  it("coalesces a burst of 429 responses and backs off again after cooldown", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(40_000);
    const scheduler = new RequestStartScheduler({
      minStartIntervalMs: 100,
      maxConcurrentRequests: 6,
      maxAdaptiveStartIntervalMs: 600,
    });

    scheduler.recordRateLimit(1_000);
    expect(scheduler.minStartIntervalMs).toBe(200);
    expect(scheduler.maxConcurrentRequests).toBe(3);

    await vi.advanceTimersByTimeAsync(100);
    scheduler.recordRateLimit(1_000);
    expect(scheduler.minStartIntervalMs).toBe(200);
    expect(scheduler.maxConcurrentRequests).toBe(3);

    await vi.advanceTimersByTimeAsync(1_000);
    scheduler.recordRateLimit(1_000);
    expect(scheduler.minStartIntervalMs).toBe(400);
    expect(scheduler.maxConcurrentRequests).toBe(2);

    await vi.advanceTimersByTimeAsync(1_000);
    scheduler.recordRateLimit(1_000);
    expect(scheduler.minStartIntervalMs).toBe(600);
    expect(scheduler.maxConcurrentRequests).toBe(2);
    scheduler.dispose();
  });

  it("recovers speed gradually after a sustained run of successful tiles", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(50_000);
    const scheduler = new RequestStartScheduler({
      minStartIntervalMs: 100,
      maxConcurrentRequests: 6,
      recoverySuccessThreshold: 2,
    });

    scheduler.recordRateLimit(1_000);
    scheduler.recordSuccess();
    scheduler.recordSuccess();
    expect(scheduler.minStartIntervalMs).toBe(200);
    expect(scheduler.maxConcurrentRequests).toBe(3);

    await vi.advanceTimersByTimeAsync(1_000);
    scheduler.recordSuccess();
    scheduler.recordSuccess();
    expect(scheduler.minStartIntervalMs).toBe(100);
    expect(scheduler.maxConcurrentRequests).toBe(4);

    scheduler.recordSuccess();
    scheduler.recordSuccess();
    expect(scheduler.minStartIntervalMs).toBe(100);
    expect(scheduler.maxConcurrentRequests).toBe(5);

    scheduler.recordSuccess();
    scheduler.recordSuccess();
    scheduler.recordSuccess();
    expect(scheduler.minStartIntervalMs).toBe(100);
    expect(scheduler.maxConcurrentRequests).toBe(6);
    scheduler.dispose();
  });

  it("honors Retry-After before retrying a 429 response", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(20_000);
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(tileResponse(429, { "retry-after": "2" }))
      .mockResolvedValueOnce(tileResponse(200));
    const load = provider({
      scheduler: new RequestStartScheduler({ minStartIntervalMs: 0 }),
      fetchImpl,
    }).loadTile(tile(1), loadOptions("vec", new AbortController()));

    await vi.advanceTimersByTimeAsync(1_999);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await expect(load).resolves.toMatchObject({
      data: expect.any(ArrayBuffer),
    });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("does not truncate Retry-After to the exponential backoff cap", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(20_000);
    const starts: number[] = [];
    const fetchImpl = vi
      .fn()
      .mockImplementationOnce(async () => {
        starts.push(Date.now());
        return tileResponse(429, { "retry-after": "30" });
      })
      .mockImplementationOnce(async () => {
        starts.push(Date.now());
        return tileResponse(200);
      });
    const load = provider({
      scheduler: new RequestStartScheduler({ minStartIntervalMs: 0 }),
      fetchImpl,
      maxInlineRetryAfterMs: 30_000,
      maxRetryDelayMs: 1_000,
    }).loadTile(tile(1), loadOptions("vec", new AbortController()));

    await vi.advanceTimersByTimeAsync(29_999);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await load;

    expect(starts).toEqual([20_000, 50_000]);
  });

  it("applies a long Retry-After as shared cooldown without blocking one tile for minutes", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(20_000);
    const scheduler = new RequestStartScheduler({ minStartIntervalMs: 0 });
    const delay = vi.fn(async () => undefined);
    const fetchImpl = vi.fn(async () =>
      tileResponse(429, { "retry-after": "120" }),
    );
    const load = provider({ delay, fetchImpl, scheduler }).loadTile(
      tile(1),
      loadOptions("vec", new AbortController()),
    );

    await expect(load).rejects.toMatchObject({
      attempts: 1,
      failureKind: "rate-limit",
      failureWindow: { tripped: true },
      retryAfterMs: 120_000,
      status: 429,
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(delay).not.toHaveBeenCalled();
    expect(scheduler.nextStartAt).toBe(140_000);
    expect(scheduler.activeRequests).toBe(0);
    scheduler.dispose();
  });

  it("caps a long shared Retry-After cooldown at the provider safety limit", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(20_000);
    const scheduler = new RequestStartScheduler({ minStartIntervalMs: 0 });
    const load = provider({
      fetchImpl: vi.fn(async () => tileResponse(429, { "retry-after": "600" })),
      scheduler,
    }).loadTile(tile(1), loadOptions("vec", new AbortController()));

    await expect(load).rejects.toMatchObject({
      attempts: 1,
      retryAfterMs: 120_000,
    });
    expect(scheduler.nextStartAt).toBe(140_000);
    scheduler.dispose();
  });

  it("keeps an external abort after a response from recording a failure", async () => {
    const controller = new AbortController();
    const failureWindow = new TiandituFailureWindow();
    const scheduler = new RequestStartScheduler({ minStartIntervalMs: 0 });
    const load = provider({
      failureWindow,
      fetchImpl: vi.fn(async () => {
        controller.abort();
        return tileResponse(429, { "retry-after": "120" });
      }),
      scheduler,
    }).loadTile(tile(1), loadOptions("vec", controller));

    await expect(load).rejects.toMatchObject({ name: "AbortError" });
    expect(failureWindow.snapshot()).toMatchObject({
      failureCount: 0,
      sampleCount: 0,
    });
    expect(scheduler.activeRequests).toBe(0);
    scheduler.dispose();
  });

  it("keeps every 429 retry on the originally routed node", async () => {
    const circuit = new TiandituNodeCircuitBreaker();
    const hosts: string[] = [];
    const fetchImpl = vi.fn(async (url: string) => {
      hosts.push(new URL(url).hostname);
      return hosts.length === 1 ? tileResponse(429) : tileResponse(200);
    });
    const load = provider({
      baseRetryDelayMs: 0,
      delay: async () => {
        circuit.recordFailure("t0");
        circuit.recordFailure("t0");
      },
      fetchImpl,
      maxRetries: 1,
      maxRetryDelayMs: 0,
      nodeCircuit: circuit,
    }).loadTile(
      tile(1),
      tiandituLoadOptions("t0", "vec", new AbortController()),
    );

    await expect(load).resolves.toMatchObject({
      data: expect.any(ArrayBuffer),
    });
    expect(hosts).toEqual(["t0.tianditu.gov.cn", "t0.tianditu.gov.cn"]);
  });

  it("applies shared rate-limit cooldown even on the terminal 429", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(70_000);
    const scheduler = new RequestStartScheduler({
      maxConcurrentRequests: 6,
      minStartIntervalMs: 100,
      now: () => Date.now(),
    });
    const load = provider({
      baseRetryDelayMs: 1_000,
      fetchImpl: vi.fn(async () => tileResponse(429)),
      maxRetries: 0,
      scheduler,
    }).loadTile(tile(1), loadOptions("vec", new AbortController()));

    await expect(load).rejects.toMatchObject({
      failureKind: "rate-limit",
      status: 429,
    });
    expect(scheduler.nextStartAt).toBe(71_000);
    expect(scheduler.minStartIntervalMs).toBe(200);
    expect(scheduler.maxConcurrentRequests).toBe(3);
    scheduler.dispose();
  });

  it("uses bounded exponential delay when Retry-After is absent", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(tileResponse(429))
      .mockResolvedValueOnce(tileResponse(200));
    const load = provider({
      scheduler: new RequestStartScheduler({ minStartIntervalMs: 0 }),
      fetchImpl,
      baseRetryDelayMs: 250,
      maxRetryDelayMs: 1_000,
    }).loadTile(tile(1), loadOptions("vec", new AbortController()));

    await vi.advanceTimersByTimeAsync(249);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await load;
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("stops after the retry limit and raises a structured redacted 429 error", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(async () => tileResponse(429));
    const load = provider({
      scheduler: new RequestStartScheduler({ minStartIntervalMs: 0 }),
      fetchImpl,
      maxRetries: 2,
      baseRetryDelayMs: 10,
      maxRetryDelayMs: 20,
    }).loadTile(
      tile(1),
      loadOptions("vec?tk=must-not-appear", new AbortController()),
    );
    const rejection = expect(load).rejects.toMatchObject({
      name: "TiandituTileHttpError",
      status: 429,
      statusCode: 429,
      attempts: 3,
    });

    await vi.runAllTimersAsync();
    await rejection;
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    await expect(load).rejects.not.toThrow(/must-not-appear/);
  });

  it("removes an aborted request while it is queued", async () => {
    vi.useFakeTimers();
    const scheduler = new RequestStartScheduler({
      minStartIntervalMs: 1_000,
      maxConcurrentRequests: 2,
    });
    const first = scheduler.schedule(
      async () => "first",
      new AbortController().signal,
    );
    const queuedController = new AbortController();
    const queued = scheduler.schedule(
      async () => "queued",
      queuedController.signal,
    );

    queuedController.abort();
    await expect(queued).rejects.toMatchObject({ name: "AbortError" });
    await expect(first).resolves.toBe("first");
    await vi.runAllTimersAsync();
    scheduler.dispose();
  });

  it("passes cancellation through to an in-flight fetch", async () => {
    const controller = new AbortController();
    const failureWindow = new TiandituFailureWindow();
    const fetchImpl = vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
        }),
    );
    const load = provider({
      failureWindow,
      scheduler: new RequestStartScheduler({ minStartIntervalMs: 0 }),
      fetchImpl,
    }).loadTile(tile(1), loadOptions("vec", controller));

    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));
    controller.abort();
    await expect(load).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(failureWindow.snapshot()).toMatchObject({
      failureCount: 0,
      sampleCount: 0,
    });
  });

  it("parses both Retry-After seconds and HTTP dates", () => {
    expect(parseRetryAfterMs("1.5", 0)).toBe(1_500);
    expect(parseRetryAfterMs("Thu, 01 Jan 1970 00:00:03 GMT", 1_000)).toBe(
      2_000,
    );
    expect(parseRetryAfterMs("invalid", 0)).toBeNull();
  });
});

function provider(dependencies: Record<string, unknown>) {
  return new TiandituTileProvider(
    {},
    {
      failureWindow: new TiandituFailureWindow(),
      nodeCircuit: new TiandituNodeCircuitBreaker(),
      scheduler: new RequestStartScheduler({ minStartIntervalMs: 0 }),
      ...dependencies,
    },
  );
}

function tile(x: number) {
  return { z: 3, x, y: 2 };
}

function loadOptions(layer: string, controller: AbortController) {
  return {
    request: { url: `https://tiles.example.test/${layer}` },
    signal: controller.signal,
  };
}

function tiandituLoadOptions(
  node: `t${number}`,
  layer: TiandituLayer,
  controller: AbortController,
) {
  return {
    request: { url: tiandituUrl(node, layer) },
    signal: controller.signal,
  };
}

type TiandituLayer = "vec" | "cva" | "img" | "cia";

function tiandituUrl(node: `t${number}`, layer: TiandituLayer) {
  return `https://${node}.tianditu.gov.cn/${layer}_w/wmts?LAYER=${layer}&tk=must-not-appear`;
}

function tiandituMetadataUrl(layer: TiandituLayer, key: string) {
  return `https://t0.tianditu.gov.cn/${layer}_w/wmts?SERVICE=WMTS&REQUEST=GetCapabilities&LAYER=${layer}&tk=${encodeURIComponent(key)}`;
}

function tileResponse(
  status: number,
  headers: Record<string, string> = {},
  arrayBuffer: () => Promise<ArrayBuffer> = async () =>
    new Uint8Array([1, 2, 3]).buffer,
  body = "",
) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText:
      status === 403
        ? "Forbidden"
        : status === 429
          ? "Too Many Requests"
          : "OK",
    headers: new Headers(headers),
    arrayBuffer,
    text: async () => body,
  } as Response;
}

function errorResponse(
  status: number,
  body: string,
  headers: Record<string, string> = {},
) {
  return tileResponse(status, headers, async () => new ArrayBuffer(0), body);
}
