import type { TiandituTileFailureInfo } from "./basemapSwitch";

export type PlatformReachability = "checking" | "reachable" | "unreachable";
export type BasemapLoadState = "unknown" | "loading" | "ready" | "failed";
export type BasemapGeneration = string | number;

export interface ActiveBasemapDescriptor {
  id: string;
  generation: BasemapGeneration;
  provider?: string;
  sourceIds: readonly string[];
  requireAllSourceIds?: boolean;
  readinessTimeoutMs?: number;
  resourceMarkers: readonly string[];
}

export interface BrowserNetworkSnapshot {
  online: boolean;
  effectiveType: string | null;
  rttMs: number | null;
  downlinkMbps: number | null;
}

export interface BasemapDiagnostics {
  network: BrowserNetworkSnapshot;
  platform: PlatformReachability;
  platformChecking: boolean;
  platformLatencyMs: number | null;
  basemap: BasemapLoadState;
  basemapLatencyMs: number | null;
  basemapLoadingSince: number | null;
  recentBasemapFailures: number;
  recentTiandituFailure: RecentTiandituFailureDiagnostics | null;
  checkedAt: number | null;
}

export interface RecentTiandituFailureDiagnostics {
  details: TiandituTileFailureInfo;
  observedAt: number;
}

export type BasemapStatusKind =
  | "checking"
  | "healthy"
  | "network"
  | "platform"
  | "service";

export type BasemapStatusTone = "neutral" | "success" | "warning" | "error";

export interface BasemapStatusPresentation {
  kind: BasemapStatusKind;
  tone: BasemapStatusTone;
  label: string;
  summary: string;
}

const englishBasemapPresentation: Record<string, [string, string]> = {
  网络已断开: [
    "Network disconnected",
    "The browser is offline. Check the local network, proxy, or VPN.",
  ],
  平台连接异常: [
    "Platform connection issue",
    "The platform health endpoint did not respond. The issue is between the browser and platform, and does not necessarily indicate a map UI defect.",
  ],
  网络可能不稳定: [
    "Network may be unstable",
    "The browser reports poor network quality and basemap resources failed to load. Retry on a stable network.",
  ],
  底图服务异常: [
    "Basemap service issue",
    "The platform is reachable, but the basemap style or tiles failed to load. The external basemap service is the likely source.",
  ],
  底图局部波动: [
    "Partial basemap instability",
    "A small number of Tianditu tiles still failed after retrying, below the threshold for switching the entire basemap.",
  ],
  网络连接较慢: [
    "Slow network connection",
    "Both the platform and basemap are responding slowly, which suggests network latency or instability.",
  ],
  底图延迟较高: [
    "High basemap latency",
    "The platform is responding normally, but the external basemap service may currently be busy.",
  ],
  平台响应较慢: [
    "Slow platform response",
    "The platform health endpoint is reachable but slow. Retry later or ask an administrator to check service load.",
  ],
  底图检测中: [
    "Checking basemap",
    "Checking the platform connection and basemap resources in the current view.",
  ],
  底图正常: [
    "Basemap healthy",
    "The platform and basemap resources in the current view are reachable.",
  ],
};

export function localizeBasemapPresentation(
  presentation: BasemapStatusPresentation,
  english: boolean,
): BasemapStatusPresentation {
  if (!english) return presentation;
  const translated = englishBasemapPresentation[presentation.label];
  return translated
    ? { ...presentation, label: translated[0], summary: translated[1] }
    : presentation;
}

export const basemapSlowThresholdMs = 3_000;
export const tiandituBasemapSlowThresholdMs = 12_000;

export function basemapSlowThresholdMsFor(
  activeBasemap: ActiveBasemapDescriptor | null | undefined,
) {
  return activeBasemap?.provider === "tianditu"
    ? tiandituBasemapSlowThresholdMs
    : basemapSlowThresholdMs;
}

export const defaultBasemapResourceMarkers = [
  "mapbox://",
  "api.mapbox.com",
  "tiles.mapbox.com",
  "openfreemap.org",
  "tile.openstreetmap.org",
  "sprite",
  "glyph",
] as const;

export function initialBasemapDiagnostics(
  network: BrowserNetworkSnapshot,
): BasemapDiagnostics {
  return {
    network,
    platform: "checking",
    platformChecking: true,
    platformLatencyMs: null,
    basemap: "unknown",
    basemapLatencyMs: null,
    basemapLoadingSince: null,
    recentBasemapFailures: 0,
    recentTiandituFailure: null,
    checkedAt: null,
  };
}

export function resetBasemapDiagnosticsForSwitch(
  diagnostics: BasemapDiagnostics,
  now = Date.now(),
): BasemapDiagnostics {
  return {
    ...diagnostics,
    basemap: "loading",
    basemapLatencyMs: null,
    basemapLoadingSince: now,
    recentBasemapFailures: 0,
    recentTiandituFailure: null,
  };
}

export function diagnosticsWithTiandituFailure(
  diagnostics: BasemapDiagnostics,
  details: TiandituTileFailureInfo,
  observedAt = Date.now(),
): BasemapDiagnostics {
  return {
    ...diagnostics,
    recentTiandituFailure: { details, observedAt },
  };
}

export function visibleTiandituFailure(
  diagnostics: BasemapDiagnostics,
  now = Date.now(),
) {
  const failure = diagnostics.recentTiandituFailure;
  if (!failure) return null;
  if (
    failure.details.failureKind !== "transient" ||
    failure.details.failureWindow?.tripped
  ) {
    return failure;
  }
  if (diagnostics.basemap === "failed") return null;
  const windowMs = failure.details.failureWindow?.windowMs ?? 0;
  return windowMs > 0 && now - failure.observedAt <= windowMs ? failure : null;
}

export function activeBasemapScopeKey(
  activeBasemap: ActiveBasemapDescriptor | null | undefined,
) {
  if (activeBasemap === undefined) return "legacy";
  if (activeBasemap === null) return "none";
  return JSON.stringify([
    activeBasemap.id,
    typeof activeBasemap.generation,
    activeBasemap.generation,
    activeBasemap.provider ?? null,
    Boolean(activeBasemap.requireAllSourceIds),
    activeBasemap.readinessTimeoutMs ?? null,
  ]);
}

export function classifyBasemapStatus(
  diagnostics: BasemapDiagnostics,
  now = Date.now(),
  slowThresholdMs = basemapSlowThresholdMs,
): BasemapStatusPresentation {
  const tiandituFailure = visibleTiandituFailure(diagnostics, now);
  const networkSlow = isBrowserConnectionSlow(diagnostics.network);
  const basemapSlow =
    (diagnostics.basemapLatencyMs ?? 0) >= slowThresholdMs ||
    (diagnostics.basemap === "loading" &&
      diagnostics.basemapLoadingSince !== null &&
      now - diagnostics.basemapLoadingSince >= slowThresholdMs);
  const platformSlow = (diagnostics.platformLatencyMs ?? 0) >= 2_000;

  if (!diagnostics.network.online) {
    return {
      kind: "network",
      tone: "error",
      label: "网络已断开",
      summary: "浏览器当前处于离线状态，请检查本机网络、代理或 VPN。",
    };
  }

  if (diagnostics.platform === "unreachable") {
    return {
      kind: "platform",
      tone: "error",
      label: "平台连接异常",
      summary:
        "平台健康接口未响应，问题发生在浏览器到平台这一段，不等同于地图前端 Bug。",
    };
  }

  if (
    diagnostics.basemap === "failed" ||
    diagnostics.recentBasemapFailures > 0
  ) {
    if (networkSlow) {
      return {
        kind: "network",
        tone: "error",
        label: "网络可能不稳定",
        summary:
          "浏览器报告当前网络质量较差，且底图资源加载失败，建议切换稳定网络后重试。",
      };
    }
    return {
      kind: "service",
      tone: "error",
      label: "底图服务异常",
      summary:
        "平台接口可以访问，但底图样式或瓦片加载失败，问题更可能来自外部底图服务。",
    };
  }

  if (
    tiandituFailure?.details.failureKind === "transient" &&
    tiandituFailure.details.failureWindow?.tripped === false
  ) {
    return {
      kind: "service",
      tone: "warning",
      label: "底图局部波动",
      summary:
        "少量天地图瓦片在重试后仍未加载，当前失败比例尚未达到整套底图回退阈值。",
    };
  }

  if (basemapSlow) {
    if (networkSlow || (diagnostics.platformLatencyMs ?? 0) >= 1_500) {
      return {
        kind: "network",
        tone: "warning",
        label: "网络连接较慢",
        summary: "平台接口和底图响应都偏慢，更可能是当前网络链路延迟或波动。",
      };
    }
    return {
      kind: "service",
      tone: "warning",
      label: "底图延迟较高",
      summary:
        "平台接口响应正常，但底图加载耗时较长，外部底图服务当前可能繁忙。",
    };
  }

  if (platformSlow) {
    return {
      kind: "platform",
      tone: "warning",
      label: "平台响应较慢",
      summary:
        "平台健康接口可以访问，但响应耗时偏高，请稍候重试或联系平台管理员检查服务负载。",
    };
  }

  if (
    diagnostics.platform === "checking" ||
    diagnostics.basemap === "unknown" ||
    diagnostics.basemap === "loading"
  ) {
    return {
      kind: "checking",
      tone: "neutral",
      label: "底图检测中",
      summary: "正在检查平台连接和当前视野内的底图资源。",
    };
  }

  return {
    kind: "healthy",
    tone: "success",
    label: "底图正常",
    summary: "平台接口和当前视野内的底图资源均可访问。",
  };
}

export function isBrowserConnectionSlow(network: BrowserNetworkSnapshot) {
  const effectiveType = network.effectiveType?.toLowerCase();
  return (
    effectiveType === "slow-2g" ||
    effectiveType === "2g" ||
    (network.rttMs !== null && network.rttMs >= 1_000) ||
    (network.downlinkMbps !== null &&
      network.downlinkMbps > 0 &&
      network.downlinkMbps < 0.8)
  );
}

export function isBasemapSourceId(
  sourceId: string | undefined,
  activeBasemap?: ActiveBasemapDescriptor | null,
) {
  if (activeBasemap === null) return false;
  if (activeBasemap !== undefined) {
    return Boolean(sourceId && activeBasemap.sourceIds.includes(sourceId));
  }
  return Boolean(
    sourceId &&
    !sourceId.startsWith("loaded-") &&
    !sourceId.startsWith("query-") &&
    !sourceId.startsWith("layer-extent-"),
  );
}

export function isBasemapResourceError(
  value: unknown,
  activeBasemap?: ActiveBasemapDescriptor | null,
) {
  const record = asRecord(value);
  const sourceId =
    typeof record?.sourceId === "string" ? record.sourceId : null;
  if (sourceId) {
    return isBasemapSourceId(sourceId, activeBasemap);
  }

  const text = nestedErrorText(value).toLowerCase();
  const resourceMarkers =
    activeBasemap === undefined
      ? defaultBasemapResourceMarkers
      : (activeBasemap?.resourceMarkers ?? []);
  return resourceMarkers.some((marker) => {
    const normalizedMarker = marker.trim().toLowerCase();
    return normalizedMarker.length > 0 && text.includes(normalizedMarker);
  });
}

function nestedErrorText(value: unknown, depth = 0): string {
  if (value == null || depth > 3) return "";
  if (typeof value === "string") return value;
  if (value instanceof Error) return value.message;
  if (typeof value !== "object") return String(value);

  const record = value as Record<string, unknown>;
  return ["message", "url", "statusText", "error"]
    .map((key) => nestedErrorText(record[key], depth + 1))
    .filter(Boolean)
    .join(" ");
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : null;
}
