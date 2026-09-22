import type { BasemapId } from "./basemapCatalog";
import type { ActiveBasemapDescriptor } from "./basemapStatus";

export const rateLimitRecoveryCooldownMs = 30_000;
export const maxRateLimitRecoveryCooldownMs = 120_000;

export const rateLimitRecoverySwitchOptions = {
  persist: false,
  announce: false,
  rollbackOnFailure: false,
} as const;

export type BasemapRecoveryReason =
  | "rate-limit"
  | "sustained-failure"
  | "service-error";

export interface BasemapRateLimitRecoveryState {
  attemptId: number;
  cooldownMs: number;
  descriptor: ActiveBasemapDescriptor | null;
  phase: "idle" | "pending" | "running";
  reason: BasemapRecoveryReason;
  suppressUntil: number;
}

export type BasemapRecoveryAction = "run" | "defer" | "discard" | "ignore";

export function shouldSuppressRecoveredBasemapRateLimitError({
  recovery,
  now,
  isRateLimitError,
  isSustainedFailure = false,
  isServiceError = false,
  matchesRecoveryDescriptor,
}: {
  recovery: BasemapRateLimitRecoveryState;
  now: number;
  isRateLimitError: boolean;
  isSustainedFailure?: boolean;
  isServiceError?: boolean;
  matchesRecoveryDescriptor: boolean;
}) {
  return Boolean(
    recovery.descriptor &&
    matchesRecoveryDescriptor &&
    (recovery.phase !== "idle" || now < recovery.suppressUntil) &&
    (isRateLimitError || isSustainedFailure || isServiceError),
  );
}

export function shouldBlockRateLimitedBasemapSelection(
  recovery: BasemapRateLimitRecoveryState,
  targetId: BasemapId,
  now: number,
) {
  return Boolean(
    recovery.descriptor?.id === targetId &&
    (recovery.phase !== "idle" || now < recovery.suppressUntil),
  );
}

export function basemapRecoveryCooldownMs(
  reason: BasemapRecoveryReason,
  retryAfterMs: number | null | undefined,
) {
  if (
    reason !== "rate-limit" ||
    typeof retryAfterMs !== "number" ||
    !Number.isFinite(retryAfterMs) ||
    retryAfterMs < 0
  ) {
    return rateLimitRecoveryCooldownMs;
  }
  return Math.max(
    rateLimitRecoveryCooldownMs,
    Math.min(retryAfterMs, maxRateLimitRecoveryCooldownMs),
  );
}

export function canRunRateLimitRecovery({
  recovery,
  failedDescriptor,
  failedBasemapId,
  activeBasemapId,
  activeGeneration,
  basemapSwitching,
  drawModeActive,
  basemapSwitchDisabled,
}: {
  recovery: BasemapRateLimitRecoveryState;
  failedDescriptor: ActiveBasemapDescriptor;
  failedBasemapId: BasemapId;
  activeBasemapId: BasemapId;
  activeGeneration: number;
  basemapSwitching: boolean;
  drawModeActive: boolean;
  basemapSwitchDisabled: boolean;
}) {
  return (
    basemapRecoveryAction({
      recovery,
      failedDescriptor,
      failedBasemapId,
      activeBasemapId,
      activeGeneration,
      basemapSwitching,
      drawModeActive,
      basemapSwitchDisabled,
    }) === "run"
  );
}

export function basemapRecoveryAction({
  recovery,
  failedDescriptor,
  failedBasemapId,
  activeBasemapId,
  activeGeneration,
  basemapSwitching,
  drawModeActive,
  basemapSwitchDisabled,
}: {
  recovery: BasemapRateLimitRecoveryState;
  failedDescriptor: ActiveBasemapDescriptor;
  failedBasemapId: BasemapId;
  activeBasemapId: BasemapId;
  activeGeneration: number;
  basemapSwitching: boolean;
  drawModeActive: boolean;
  basemapSwitchDisabled: boolean;
}): BasemapRecoveryAction {
  const matchesActiveFailure = Boolean(
    recovery.descriptor?.id === failedDescriptor.id &&
    recovery.descriptor.generation === failedDescriptor.generation &&
    activeBasemapId === failedBasemapId &&
    activeGeneration === failedDescriptor.generation,
  );
  if (!matchesActiveFailure) return "discard";
  if (recovery.phase === "running") return "ignore";
  if (recovery.phase !== "pending") return "discard";
  if (basemapSwitching || drawModeActive || basemapSwitchDisabled) {
    return "defer";
  }
  return "run";
}
