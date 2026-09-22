import {
  CheckCircleFilled,
  CloudServerOutlined,
  DisconnectOutlined,
  LoadingOutlined,
  ReloadOutlined,
  WarningFilled,
  WifiOutlined,
} from "@ant-design/icons";
import { Button, Popover } from "antd";
import type { Map as MapboxMap } from "mapbox-gl";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { currentLocale } from "../i18n";
import {
  useBasemapStatus,
  type BasemapRetryProbe,
} from "../hooks/useBasemapStatus";
import {
  basemapSlowThresholdMsFor,
  classifyBasemapStatus,
  isBrowserConnectionSlow,
  localizeBasemapPresentation,
  visibleTiandituFailure,
  type ActiveBasemapDescriptor,
  type RecentTiandituFailureDiagnostics,
  type BasemapStatusPresentation,
} from "../map/basemapStatus";

export interface BasemapStatusIndicatorProps {
  map: MapboxMap | null;
  activeBasemap?: ActiveBasemapDescriptor | null;
  activeBasemapName?: string;
  retryBasemap?: BasemapRetryProbe;
}

export default function BasemapStatusIndicator({
  map,
  activeBasemap,
  activeBasemapName,
  retryBasemap,
}: BasemapStatusIndicatorProps) {
  useTranslation();
  const english = currentLocale() === "en-US";
  const { diagnostics, refresh } = useBasemapStatus(map, {
    activeBasemap,
    retryBasemap,
  });
  const [, setClock] = useState(0);
  const now = Date.now();
  const recentTiandituFailure = visibleTiandituFailure(diagnostics, now);
  const hasExpiringTiandituFailure =
    recentTiandituFailure?.details.failureWindow?.tripped === false;

  useEffect(() => {
    if (diagnostics.basemap !== "loading" && !hasExpiringTiandituFailure)
      return;
    const intervalId = window.setInterval(
      () => setClock((current) => current + 1),
      1_000,
    );
    return () => window.clearInterval(intervalId);
  }, [diagnostics.basemap, hasExpiringTiandituFailure]);

  const presentation = localizeBasemapPresentation(
    classifyBasemapStatus(
      diagnostics,
      now,
      basemapSlowThresholdMsFor(activeBasemap),
    ),
    english,
  );
  const latency = primaryLatency(
    presentation,
    diagnostics,
    activeBasemap?.provider,
  );
  const content = (
    <div className="basemap-status-details">
      <div className="basemap-status-details-heading">
        <strong>
          {english ? "Network and basemap status" : "网络与底图状态"}
        </strong>
        <span
          className={`basemap-status-badge basemap-status-${presentation.tone}`}
        >
          {presentation.label}
        </span>
      </div>
      <p className="basemap-status-summary">{presentation.summary}</p>
      <dl className="basemap-status-list">
        <StatusRow
          icon={<WifiOutlined />}
          label={english ? "Browser network" : "浏览器网络"}
          value={networkDetail(diagnostics.network, english)}
        />
        <StatusRow
          icon={<CloudServerOutlined />}
          label={english ? "Platform API" : "平台接口"}
          value={platformDetail(diagnostics, english)}
        />
        <StatusRow
          icon={<StatusIcon presentation={presentation} />}
          label={english ? "Basemap service" : "底图服务"}
          value={formatBasemapServiceDetail(
            activeBasemapName,
            basemapDetail(diagnostics, now, activeBasemap?.provider, english),
          )}
        />
      </dl>
      <div className="basemap-status-actions">
        <Button
          size="small"
          icon={<ReloadOutlined />}
          loading={diagnostics.platformChecking}
          onClick={refresh}
        >
          {english ? "Check again" : "重新检测"}
        </Button>
        <span>
          {english
            ? "Live browser-side diagnostics for quick troubleshooting only"
            : "浏览器端实时判断，仅用于快速排查"}
        </span>
      </div>
    </div>
  );

  return (
    <Popover content={content} placement="topLeft" trigger="click">
      <button
        type="button"
        className={`basemap-status-trigger basemap-status-${presentation.tone}`}
        aria-label={
          english
            ? `Basemap service status: ${presentation.label}`
            : `底图服务状态：${presentation.label}`
        }
        aria-live="polite"
      >
        <StatusIcon presentation={presentation} />
        <span className="basemap-status-label">{presentation.label}</span>
        {latency !== null ? (
          <span className="basemap-status-latency">{latency} ms</span>
        ) : null}
      </button>
    </Popover>
  );
}

export function formatBasemapServiceDetail(
  activeBasemapName: string | null | undefined,
  detail: string,
) {
  const normalizedName = activeBasemapName?.trim();
  return normalizedName ? `${normalizedName} · ${detail}` : detail;
}

function StatusRow({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="basemap-status-row">
      <dt>
        {icon}
        <span>{label}</span>
      </dt>
      <dd>{value}</dd>
    </div>
  );
}

function StatusIcon({
  presentation,
}: {
  presentation: BasemapStatusPresentation;
}) {
  if (presentation.kind === "checking") return <LoadingOutlined spin />;
  if (presentation.kind === "healthy") return <CheckCircleFilled />;
  if (presentation.kind === "network" && presentation.tone === "error") {
    return <DisconnectOutlined />;
  }
  return <WarningFilled />;
}

function networkDetail(
  network: ReturnType<typeof useBasemapStatus>["diagnostics"]["network"],
  english = false,
) {
  if (!network.online) return english ? "Disconnected" : "已断开";
  const parts = [
    isBrowserConnectionSlow(network)
      ? english
        ? "Slow connection"
        : "连接较慢"
      : english
        ? "Connected"
        : "已连接",
  ];
  if (network.effectiveType) parts.push(network.effectiveType.toUpperCase());
  if (network.rttMs !== null) parts.push(`RTT ${network.rttMs} ms`);
  return parts.join(" · ");
}

function platformDetail(
  diagnostics: ReturnType<typeof useBasemapStatus>["diagnostics"],
  english = false,
) {
  if (diagnostics.platform === "checking")
    return english ? "Checking" : "检测中";
  if (diagnostics.platform === "unreachable")
    return english ? "No response" : "未响应";
  return diagnostics.platformLatencyMs === null
    ? english
      ? "Reachable"
      : "可访问"
    : `${english ? "Reachable" : "可访问"} · ${diagnostics.platformLatencyMs} ms`;
}

export function basemapDetail(
  diagnostics: ReturnType<typeof useBasemapStatus>["diagnostics"],
  now = Date.now(),
  provider?: ActiveBasemapDescriptor["provider"],
  english = false,
) {
  const failure = visibleTiandituFailure(diagnostics, now);
  const failureDetail = failure
    ? formatTiandituFailureDiagnostic(failure, english)
    : null;
  if (
    diagnostics.basemap === "failed" ||
    diagnostics.recentBasemapFailures > 0
  ) {
    return failureDetail
      ? `${english ? "Load failed" : "加载失败"} · ${failureDetail}`
      : english
        ? `Load failed · ${diagnostics.recentBasemapFailures} recent failures`
        : `加载失败 · 最近 ${diagnostics.recentBasemapFailures} 次`;
  }
  if (
    failureDetail &&
    failure?.details.failureKind === "transient" &&
    failure.details.failureWindow?.tripped === false
  ) {
    return `${english ? "Partial instability" : "局部波动"} · ${failureDetail}`;
  }
  if (failureDetail)
    return `${english ? "Service issue" : "服务异常"} · ${failureDetail}`;
  if (diagnostics.basemap === "loading")
    return english ? "Loading current view" : "正在加载当前视野";
  if (diagnostics.basemap === "unknown")
    return english ? "Waiting for map initialization" : "等待地图初始化";
  return diagnostics.basemapLatencyMs === null
    ? english
      ? "Reachable"
      : "可访问"
    : provider === "tianditu"
      ? english
        ? `Reachable · recent tile ready time (including client queue) ${diagnostics.basemapLatencyMs} ms`
        : `可访问 · 近期瓦片就绪（含客户端排队）${diagnostics.basemapLatencyMs} ms`
      : english
        ? `Reachable · latest response ${diagnostics.basemapLatencyMs} ms`
        : `可访问 · 最近响应 ${diagnostics.basemapLatencyMs} ms`;
}

export function formatTiandituFailureDiagnostic(
  failure: RecentTiandituFailureDiagnostics,
  english = false,
) {
  const { details } = failure;
  const parts = [tiandituFailureKindLabel(details.failureKind, english)];
  const window = details.failureWindow;
  if (window && window.sampleCount > 0) {
    const percentage = Math.round(
      Math.max(0, Math.min(1, window.failureRate)) * 100,
    );
    parts.push(
      english
        ? `Tile failures ${window.failureCount}/${window.sampleCount} (${percentage}%)`
        : `瓦片失败 ${window.failureCount}/${window.sampleCount}（${percentage}%）`,
    );
  }
  if (details.businessCode)
    parts.push(
      `${english ? "Business code" : "业务码"} ${details.businessCode}`,
    );
  if (details.layer) {
    parts.push(
      details.layer === "vec"
        ? english
          ? "Vector layer"
          : "矢量层"
        : english
          ? "Label layer"
          : "注记层",
    );
  }
  if (details.node) parts.push(details.node);
  return parts.join(" · ");
}

function tiandituFailureKindLabel(
  kind: RecentTiandituFailureDiagnostics["details"]["failureKind"],
  english = false,
) {
  if (kind === "credentials") return english ? "Credential issue" : "凭证异常";
  if (kind === "rate-limit") return english ? "Rate limited" : "请求限流";
  if (kind === "permanent") return english ? "Permanent error" : "永久错误";
  return english ? "Transient error" : "瞬时错误";
}

export function primaryLatency(
  presentation: BasemapStatusPresentation,
  diagnostics: ReturnType<typeof useBasemapStatus>["diagnostics"],
  provider?: ActiveBasemapDescriptor["provider"],
) {
  if (
    presentation.tone === "error" ||
    presentation.label === "底图局部波动" ||
    presentation.label === "Partial basemap instability"
  ) {
    return null;
  }
  if (presentation.kind === "platform") {
    return diagnostics.platformLatencyMs;
  }
  if (presentation.kind === "network" && diagnostics.network.rttMs !== null) {
    return diagnostics.network.rttMs;
  }
  if (provider === "tianditu" && presentation.kind === "healthy") return null;
  return diagnostics.basemapLatencyMs;
}
