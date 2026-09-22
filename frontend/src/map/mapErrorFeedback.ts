import type { BasemapProvider } from "./basemapCatalog";

export const mapErrorNotificationCooldownMs = 60_000;
export const mapErrorNotificationKey = "map-load-error";
export const basemapRecoveryNotificationKey = "basemap-recovery";

const externalUrlPattern = /(?:https?:\/\/|mapbox:\/\/)[^\s"'<>]+/gi;

export function shouldForwardMapErrorToGlobalMessage({
  activeBasemapError,
  errorProvider = null,
  provider,
}: {
  activeBasemapError: boolean;
  errorProvider?: BasemapProvider | null;
  provider: BasemapProvider;
}) {
  if (errorProvider === "tianditu") return false;
  return !(activeBasemapError && provider === "tianditu");
}

export function claimMapErrorNotification(
  history: Map<string, number>,
  message: string,
  now = Date.now(),
  cooldownMs = mapErrorNotificationCooldownMs,
) {
  for (const [fingerprint, shownAt] of history) {
    if (now - shownAt >= cooldownMs) history.delete(fingerprint);
  }

  const fingerprint = mapErrorFingerprint(message);
  const previous = history.get(fingerprint);
  if (previous !== undefined && now - previous < cooldownMs) return false;
  history.set(fingerprint, now);
  return true;
}

export function mapErrorFingerprint(message: string) {
  return message
    .trim()
    .replace(externalUrlPattern, resourceFingerprintForUrl)
    .toLowerCase()
    .replace(/\bt[0-7]\b/g, "t#")
    .replace(/\s+/g, " ");
}

function resourceFingerprintForUrl(rawUrl: string) {
  try {
    const url = new URL(rawUrl);
    if (url.protocol === "mapbox:") return "[mapbox-resource]";
    const hostname = url.hostname.toLowerCase();
    if (
      hostname === "tianditu.gov.cn" ||
      hostname.endsWith(".tianditu.gov.cn")
    ) {
      return "[tianditu-resource]";
    }
    if (hostname === "mapbox.com" || hostname.endsWith(".mapbox.com")) {
      return "[mapbox-resource]";
    }
    if (
      hostname === "openstreetmap.org" ||
      hostname.endsWith(".openstreetmap.org")
    ) {
      return "[openstreetmap-resource]";
    }
    if (
      hostname === "openfreemap.org" ||
      hostname.endsWith(".openfreemap.org")
    ) {
      return "[openfreemap-resource]";
    }
  } catch {
    // Keep malformed URLs out of the fingerprint without exposing their text.
  }
  return "[external-resource]";
}

export function summarizeMapErrorForUser(
  message: string,
  maxLength = 160,
  english = false,
) {
  const summary = message
    .trim()
    .replace(/^error:\s*/i, "")
    .replace(
      externalUrlPattern,
      english ? "external map resource" : "外部地图资源",
    )
    .replace(
      /failed to fetch/gi,
      english ? "map resource request failed" : "地图资源请求失败",
    )
    .replace(
      /network error/gi,
      english ? "network request failed" : "网络请求失败",
    )
    .replace(/\s+/g, " ")
    .trim();
  const fallback =
    summary ||
    (english
      ? "The map resource is temporarily unavailable. Try again later."
      : "地图资源暂时无法访问，请稍后重试");
  return fallback.length <= maxLength
    ? fallback
    : `${fallback.slice(0, Math.max(1, maxLength - 1))}…`;
}
