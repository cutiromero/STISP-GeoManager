import { describe, expect, it } from "vitest";
import { createBasemapCatalog } from "./basemapCatalog";
import {
  basemapRecoveryAction,
  basemapRecoveryCooldownMs,
  canRunRateLimitRecovery,
  rateLimitRecoverySwitchOptions,
  shouldBlockRateLimitedBasemapSelection,
  shouldSuppressRecoveredBasemapRateLimitError,
  type BasemapRateLimitRecoveryState,
} from "./basemapRateLimitRecovery";
import {
  resolveBasemapRateLimitFallback,
  resolveBasemapTechnicalFallback,
} from "./basemapSwitch";
import type { ActiveBasemapDescriptor } from "./basemapStatus";

const descriptor: ActiveBasemapDescriptor = {
  id: "tianditu-vector",
  generation: 7,
  sourceIds: ["basemap-tianditu-vector", "basemap-tianditu-labels"],
  requireAllSourceIds: true,
  resourceMarkers: ["tianditu.gov.cn"],
};

function recovery(
  overrides: Partial<BasemapRateLimitRecoveryState> = {},
): BasemapRateLimitRecoveryState {
  return {
    attemptId: 1,
    cooldownMs: 30_000,
    descriptor,
    phase: "pending",
    reason: "rate-limit",
    suppressUntil: 31_000,
    ...overrides,
  };
}

describe("Tianditu rate-limit recovery invariants", () => {
  it("suppresses a late 429 while the recovery transaction is still in flight after 30 seconds", () => {
    expect(
      shouldSuppressRecoveredBasemapRateLimitError({
        recovery: recovery(),
        now: 31_001,
        isRateLimitError: true,
        matchesRecoveryDescriptor: true,
      }),
    ).toBe(true);
    expect(
      shouldSuppressRecoveredBasemapRateLimitError({
        recovery: recovery({ phase: "idle" }),
        now: 31_001,
        isRateLimitError: true,
        matchesRecoveryDescriptor: true,
      }),
    ).toBe(false);
  });

  it.each([
    { drawModeActive: true, basemapSwitchDisabled: false },
    { drawModeActive: false, basemapSwitchDisabled: true },
  ])("does not switch while drawing or exporting: %o", (locks) => {
    const context = {
      recovery: recovery(),
      failedDescriptor: descriptor,
      failedBasemapId: "tianditu-vector" as const,
      activeBasemapId: "tianditu-vector" as const,
      activeGeneration: 7,
      basemapSwitching: false,
      ...locks,
    };

    expect(canRunRateLimitRecovery(context)).toBe(false);
    expect(basemapRecoveryAction(context)).toBe("defer");
  });

  it("runs a deferred recovery after the interaction lock clears", () => {
    const context = {
      recovery: recovery(),
      failedDescriptor: descriptor,
      failedBasemapId: "tianditu-vector" as const,
      activeBasemapId: "tianditu-vector" as const,
      activeGeneration: 7,
      basemapSwitching: false,
      drawModeActive: false,
      basemapSwitchDisabled: false,
    };

    expect(basemapRecoveryAction(context)).toBe("run");
    expect(canRunRateLimitRecovery(context)).toBe(true);
  });

  it("ignores a duplicate recovery entry while the same attempt is running", () => {
    expect(
      basemapRecoveryAction({
        recovery: recovery({ phase: "running" }),
        failedDescriptor: descriptor,
        failedBasemapId: "tianditu-vector",
        activeBasemapId: "tianditu-vector",
        activeGeneration: 7,
        basemapSwitching: false,
        drawModeActive: false,
        basemapSwitchDisabled: false,
      }),
    ).toBe("ignore");
  });

  it("discards a deferred recovery after the active generation changes", () => {
    expect(
      basemapRecoveryAction({
        recovery: recovery(),
        failedDescriptor: descriptor,
        failedBasemapId: "tianditu-vector",
        activeBasemapId: "tianditu-vector",
        activeGeneration: 8,
        basemapSwitching: false,
        drawModeActive: false,
        basemapSwitchDisabled: false,
      }),
    ).toBe("discard");
  });

  it("suppresses repeated sustained failures with the same single-flight cooldown", () => {
    const sustainedRecovery = recovery({
      phase: "idle",
      reason: "sustained-failure",
    });
    expect(
      shouldSuppressRecoveredBasemapRateLimitError({
        recovery: sustainedRecovery,
        now: 30_999,
        isRateLimitError: false,
        isSustainedFailure: true,
        matchesRecoveryDescriptor: true,
      }),
    ).toBe(true);
    expect(
      shouldSuppressRecoveredBasemapRateLimitError({
        recovery: sustainedRecovery,
        now: 30_999,
        isRateLimitError: true,
        isSustainedFailure: false,
        matchesRecoveryDescriptor: true,
      }),
    ).toBe(true);
  });

  it("suppresses repeated confirmed service errors during automatic recovery", () => {
    const serviceRecovery = recovery({
      reason: "service-error",
    });
    expect(
      shouldSuppressRecoveredBasemapRateLimitError({
        recovery: serviceRecovery,
        now: 31_001,
        isRateLimitError: false,
        isServiceError: true,
        matchesRecoveryDescriptor: true,
      }),
    ).toBe(true);
  });

  it("uses only Tianditu -> Mapbox -> OSM when Mapbox recovery fails", () => {
    const catalog = createBasemapCatalog({
      mapboxAccessToken: "test-public-token",
      tiandituKey: "test-public-key",
    });
    const primary = resolveBasemapRateLimitFallback(catalog, "tianditu-vector");
    const technical = resolveBasemapTechnicalFallback(catalog, primary!.id);

    expect([primary?.id, technical?.id]).toEqual(["mapbox-satellite", "osm"]);
    expect(technical?.id).not.toBe("tianditu-vector");
  });

  it("never persists the automatic recovery choice", () => {
    expect(rateLimitRecoverySwitchOptions).toEqual({
      persist: false,
      announce: false,
      rollbackOnFailure: false,
    });
  });

  it("blocks reselecting Tianditu throughout its cooldown", () => {
    expect(
      shouldBlockRateLimitedBasemapSelection(
        recovery({ phase: "idle" }),
        "tianditu-vector",
        30_999,
      ),
    ).toBe(true);
    expect(
      shouldBlockRateLimitedBasemapSelection(
        recovery({ phase: "idle" }),
        "tianditu-vector",
        31_000,
      ),
    ).toBe(false);
  });

  it("aligns the UI cooldown with a bounded Retry-After", () => {
    expect(basemapRecoveryCooldownMs("rate-limit", 120_000)).toBe(120_000);
    expect(basemapRecoveryCooldownMs("rate-limit", 600_000)).toBe(120_000);
    expect(basemapRecoveryCooldownMs("rate-limit", 2_000)).toBe(30_000);
    expect(basemapRecoveryCooldownMs("service-error", 120_000)).toBe(30_000);
  });
});
