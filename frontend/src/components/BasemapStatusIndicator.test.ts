import { describe, expect, it } from "vitest";
import {
  basemapDetail,
  formatBasemapServiceDetail,
  formatTiandituFailureDiagnostic,
  primaryLatency,
} from "./BasemapStatusIndicator";
import {
  classifyBasemapStatus,
  initialBasemapDiagnostics,
} from "../map/basemapStatus";

describe("formatBasemapServiceDetail", () => {
  it("prefixes the diagnostic with the active basemap name", () => {
    expect(
      formatBasemapServiceDetail(
        "Mapbox 卫星实景图",
        "可访问 / 最近响应 620 ms",
      ),
    ).toBe("Mapbox 卫星实景图 / 可访问 / 最近响应 620 ms");
  });

  it("keeps the existing diagnostic when no display name is provided", () => {
    expect(formatBasemapServiceDetail(undefined, "正在加载当前视野")).toBe(
      "正在加载当前视野",
    );
    expect(formatBasemapServiceDetail("   ", "加载失败 / 最近 2 次")).toBe(
      "加载失败 / 最近 2 次",
    );
  });

  it("shows only sanitized Tianditu failure-window diagnostics", () => {
    expect(
      formatTiandituFailureDiagnostic({
        observedAt: 1_000,
        details: {
          attempts: 2,
          businessCode: "TEMPORARY",
          failureKind: "transient",
          failureWindow: {
            consecutiveFailures: 1,
            failureCount: 1,
            failureRate: 0.125,
            sampleCount: 8,
            tripped: false,
            windowMs: 15_000,
          },
          layer: "cva",
          node: "t3",
          retryAfterMs: null,
          status: 403,
        },
      }),
    ).toBe("瞬时错误 / 瓦片失败 1/8（13%） / 业务码 TEMPORARY / 注记层 / t3");
  });
});

describe("basemapDetail", () => {
  it("keeps a confirmed hard failure ahead of a stale soft fluctuation", () => {
    const diagnostics = {
      ...initialBasemapDiagnostics({
        online: true,
        effectiveType: "4g",
        rttMs: 100,
        downlinkMbps: 10,
      }),
      basemap: "failed" as const,
      basemapLatencyMs: 7_103,
      recentBasemapFailures: 1,
      recentTiandituFailure: {
        observedAt: 1_000,
        details: {
          attempts: 2,
          businessCode: "TEMPORARY",
          failureKind: "transient" as const,
          failureWindow: {
            consecutiveFailures: 1,
            failureCount: 1,
            failureRate: 1 / 12,
            sampleCount: 12,
            tripped: false,
            windowMs: 15_000,
          },
          layer: "vec" as const,
          node: "t7",
          retryAfterMs: null,
          status: 403,
        },
      },
    };
    const presentation = classifyBasemapStatus(diagnostics, 2_000);

    expect(basemapDetail(diagnostics, 2_000, "tianditu")).toContain("加载失败");
    expect(basemapDetail(diagnostics, 2_000, "tianditu")).not.toContain(
      "局部波动",
    );
    expect(primaryLatency(presentation, diagnostics)).toBeNull();
  });

  it("labels a Tianditu timing as tile readiness including client queueing", () => {
    const diagnostics = {
      ...initialBasemapDiagnostics({
        online: true,
        effectiveType: "4g",
        rttMs: 100,
        downlinkMbps: 10,
      }),
      basemap: "ready" as const,
      basemapLatencyMs: 183,
      platform: "reachable" as const,
      platformChecking: false,
      platformLatencyMs: 120,
    };

    expect(basemapDetail(diagnostics, 2_000, "tianditu")).toBe(
      "可访问 / 近期瓦片就绪（含客户端排队）183 ms",
    );
    expect(
      primaryLatency(classifyBasemapStatus(diagnostics, 2_000), diagnostics),
    ).toBeNull();
  });

  it("shows only the label while any basemap is healthy and keeps slow timings", () => {
    const healthy = {
      ...initialBasemapDiagnostics({
        online: true,
        effectiveType: "4g",
        rttMs: 100,
        downlinkMbps: 10,
      }),
      basemap: "ready" as const,
      basemapLatencyMs: 913,
      platform: "reachable" as const,
      platformChecking: false,
      platformLatencyMs: 120,
    };
    const presentation = classifyBasemapStatus(healthy, 2_000);
    expect(presentation.kind).toBe("healthy");
    expect(primaryLatency(presentation, healthy)).toBeNull();
    const slow = { ...healthy, platformLatencyMs: 9_000 };
    const slowPresentation = classifyBasemapStatus(slow, 2_000);
    expect(slowPresentation.kind).not.toBe("healthy");
    expect(primaryLatency(slowPresentation, slow)).not.toBeNull();
  });
});
