import { describe, expect, it } from "vitest";
import {
  claimMapErrorNotification,
  mapErrorFingerprint,
  shouldForwardMapErrorToGlobalMessage,
  summarizeMapErrorForUser,
} from "./mapErrorFeedback";

describe("map error feedback", () => {
  it("keeps active Tianditu background failures in the status indicator", () => {
    expect(
      shouldForwardMapErrorToGlobalMessage({
        activeBasemapError: true,
        provider: "tianditu",
      }),
    ).toBe(false);
    expect(
      shouldForwardMapErrorToGlobalMessage({
        activeBasemapError: true,
        provider: "mapbox",
      }),
    ).toBe(true);
    expect(
      shouldForwardMapErrorToGlobalMessage({
        activeBasemapError: false,
        provider: "tianditu",
      }),
    ).toBe(true);
    expect(
      shouldForwardMapErrorToGlobalMessage({
        activeBasemapError: false,
        errorProvider: "tianditu",
        provider: "mapbox",
      }),
    ).toBe(false);
  });

  it("deduplicates the same resource failure when tile URLs and nodes change", () => {
    const history = new Map<string, number>();
    const first =
      "Failed to fetch https://t1.tianditu.gov.cn/vec_w/wmts?TILECOL=12&tk=secret";
    const second =
      "Failed to fetch https://t7.tianditu.gov.cn/vec_w/wmts?TILECOL=99&tk=secret";

    expect(mapErrorFingerprint(first)).toBe(mapErrorFingerprint(second));
    expect(claimMapErrorNotification(history, first, 1_000)).toBe(true);
    expect(claimMapErrorNotification(history, second, 2_000)).toBe(false);
    expect(claimMapErrorNotification(history, second, 61_000)).toBe(true);
  });

  it("keeps different actionable errors independently visible", () => {
    const history = new Map<string, number>();
    expect(claimMapErrorNotification(history, "HTTP 401", 1_000)).toBe(true);
    expect(
      claimMapErrorNotification(history, "WebGL context lost", 2_000),
    ).toBe(true);
  });

  it("keeps different external providers in separate cooldown buckets", () => {
    const tianditu =
      "Failed to fetch https://t1.tianditu.gov.cn/vec_w/wmts?tk=secret";
    const mapbox =
      "Failed to fetch https://api.mapbox.com/styles/v1/example?access_token=secret";

    expect(mapErrorFingerprint(tianditu)).not.toBe(mapErrorFingerprint(mapbox));
  });

  it("groups mapbox scheme and HTTPS resources into the same cooldown bucket", () => {
    const style = "Failed to load mapbox://styles/example/style-v1";
    const api =
      "Failed to load https://api.mapbox.com/styles/v1/example?access_token=secret";

    expect(mapErrorFingerprint(style)).toBe(mapErrorFingerprint(api));
    expect(summarizeMapErrorForUser(style)).not.toContain("mapbox://");
  });

  it("removes raw resource URLs and bounds the visible message", () => {
    const summary = summarizeMapErrorForUser(
      `Error: Failed to fetch https://t0.tianditu.gov.cn/vec_w/wmts?tk=secret ${"x".repeat(200)}`,
      80,
    );
    expect(summary).toContain("地图资源请求失败");
    expect(summary).not.toContain("tianditu.gov.cn");
    expect(summary).not.toContain("secret");
    expect(summary.length).toBeLessThanOrEqual(80);
  });
});
