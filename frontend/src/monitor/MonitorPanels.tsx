import { FileTextOutlined, RobotOutlined } from "@ant-design/icons";
import { App, Button } from "antd";
import {
  type CSSProperties,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import {
  averageReadings,
  metricPrecision,
  metricUnits,
  riskColors,
  riskLevels,
} from "./state";
import { metricIds, type MetricId, type MonitorSnapshot } from "./types";

export function MonitorPanel({
  title,
  extra,
  children,
  className = "",
}: {
  title: string;
  extra?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`monitor-panel ${className}`} aria-label={title}>
      <header className="monitor-panel-heading">
        <h2>{title}</h2>
        {extra}
      </header>
      {children}
    </section>
  );
}

export function MonitorNumber({
  value,
  precision = 0,
}: {
  value: number;
  precision?: number;
}) {
  const formatted = value.toFixed(precision);
  return (
    <span className="monitor-number" data-value={formatted}>
      <span key={formatted}>{formatted}</span>
    </span>
  );
}

export function RiskPanel({ snapshot }: { snapshot: MonitorSnapshot }) {
  const { t } = useTranslation();
  const risk =
    snapshot.stations.reduce((sum, station) => sum + station.risk, 0) /
    Math.max(1, snapshot.stations.length);
  const counts = riskLevels.map((level) => ({
    level,
    count: snapshot.stations.filter((station) => station.level === level)
      .length,
  }));
  let offset = 0;
  return (
    <MonitorPanel
      title={t("monitor.riskTitle")}
      extra={
        <span className="monitor-panel-caption">{t("monitor.riskUnit")}</span>
      }
    >
      <div className="monitor-risk-content">
        <div
          className="monitor-gauge"
          role="img"
          aria-label={t("monitor.riskValue", { value: Math.round(risk) })}
        >
          <svg viewBox="0 0 120 120" aria-hidden="true">
            <circle
              cx="60"
              cy="60"
              r="47"
              fill="none"
              stroke="#183344"
              strokeWidth="7"
            />
            {counts.map(({ level, count }) => {
              const percentage =
                (count / Math.max(1, snapshot.stations.length)) * 100;
              const start = offset;
              offset += percentage;
              return (
                <circle
                  key={level}
                  cx="60"
                  cy="60"
                  r="47"
                  pathLength="100"
                  fill="none"
                  stroke={riskColors[level]}
                  strokeWidth="7"
                  strokeDasharray={`${Math.max(0, percentage - 1)} ${100 - Math.max(0, percentage - 1)}`}
                  strokeDashoffset={-start}
                  transform="rotate(-90 60 60)"
                />
              );
            })}
          </svg>
          <div className="monitor-gauge-value">
            <MonitorNumber value={risk} />
            <small>{t("monitor.compositeRisk")}</small>
          </div>
        </div>
        <ul className="monitor-risk-legend">
          {counts.map(({ level, count }) => (
            <li key={level}>
              <i style={{ background: riskColors[level] }} />
              <span>{t(`monitor.level.${level}`)}</span>
              <strong>
                {Math.round(
                  (count / Math.max(1, snapshot.stations.length)) * 100,
                )}
                <small>%</small>
              </strong>
            </li>
          ))}
        </ul>
      </div>
    </MonitorPanel>
  );
}

export function MetricsPanel({ snapshot }: { snapshot: MonitorSnapshot }) {
  const { t } = useTranslation();
  const current = averageReadings(snapshot.stations);
  const previous =
    snapshot.history[snapshot.history.length - 2]?.readings ?? current;
  return (
    <MonitorPanel
      title={t("monitor.metricsTitle")}
      extra={
        <span className="monitor-panel-caption">
          {t("monitor.regionalMean")}
        </span>
      }
    >
      <div className="monitor-metrics">
        {metricIds.map((metric) => {
          const delta = current[metric] - previous[metric];
          const improved = metric === "groundwater" ? delta < 0 : delta > 0;
          return (
            <div
              className="monitor-metric"
              key={metric}
              data-testid={`metric-${metric}`}
            >
              <span>{t(`monitor.metric.${metric}`)}</span>
              <strong>
                <MonitorNumber
                  value={current[metric]}
                  precision={metricPrecision[metric]}
                />
                <small>{metricUnits[metric]}</small>
              </strong>
              <em
                className={
                  Math.abs(delta) < 0.0001
                    ? ""
                    : improved
                      ? "is-improving"
                      : "is-declining"
                }
              >
                {delta > 0 ? "↑" : delta < 0 ? "↓" : "—"}{" "}
                {Math.abs(delta).toFixed(metricPrecision[metric])}{" "}
                <small>{t("monitor.sinceLast")}</small>
              </em>
            </div>
          );
        })}
      </div>
    </MonitorPanel>
  );
}

export function TrendPanel({
  snapshot,
  locale,
}: {
  snapshot: MonitorSnapshot;
  locale: string;
}) {
  const { t } = useTranslation();
  const [metric, setMetric] = useState<MetricId>("groundwater");
  const samples = snapshot.history;
  const values = samples.map((sample) => sample.readings[metric]);
  const lower = Math.min(...values) - (metric === "ndvi" ? 0.002 : 0.05);
  const upper = Math.max(...values) + (metric === "ndvi" ? 0.002 : 0.05);
  const points = values
    .map(
      (value, order) =>
        `${36 + (order / Math.max(1, values.length - 1)) * 524},${94 - ((value - lower) / (upper - lower)) * 72}`,
    )
    .join(" ");
  const first = samples[0];
  const last = samples[samples.length - 1];
  const time = (value: string) =>
    new Date(value).toLocaleTimeString(locale, {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  return (
    <MonitorPanel
      className="monitor-trend-panel"
      title={t("monitor.trendTitle")}
      extra={
        <span className="monitor-panel-caption">
          {t("monitor.sampleCount", { count: samples.length })}
        </span>
      }
    >
      <div className="monitor-trend-tabs">
        {metricIds.map((id) => (
          <Button
            key={id}
            size="small"
            type={metric === id ? "primary" : "text"}
            onClick={() => setMetric(id)}
          >
            {t(`monitor.metric.${id}`)}
          </Button>
        ))}
      </div>
      <svg
        className="monitor-trend-chart"
        viewBox="0 0 580 126"
        role="img"
        aria-label={t("monitor.chartLabel", {
          metric: t(`monitor.metric.${metric}`),
        })}
      >
        {[22, 58, 94].map((height) => (
          <line
            key={height}
            x1="36"
            x2="560"
            y1={height}
            y2={height}
            stroke="#244050"
            strokeDasharray="3 5"
          />
        ))}
        <text x="0" y="25">
          {upper.toFixed(metricPrecision[metric])}
        </text>
        <text x="0" y="96">
          {lower.toFixed(metricPrecision[metric])}
        </text>
        <polygon
          points={`36,100 ${points} 560,100`}
          fill="#46d6bf"
          fillOpacity="0.07"
        />
        <polyline
          points={points}
          fill="none"
          stroke="#65e1c8"
          strokeWidth="2.5"
          strokeLinejoin="round"
        />
        {first && (
          <text x="36" y="119">
            {time(first.observedAt)}
          </text>
        )}
        {last && (
          <text x="560" y="119" textAnchor="end">
            {time(last.observedAt)} · {metricUnits[metric]}
          </text>
        )}
      </svg>
    </MonitorPanel>
  );
}

export function AlertsPanel({
  snapshot,
  animated,
  locale,
  onSelect,
}: {
  snapshot: MonitorSnapshot;
  animated: boolean;
  locale: string;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const list = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const active = snapshot.alerts.filter((alert) => !alert.resolvedAt).length;
  const scrolling = animated && !hovered && !focused;
  useEffect(() => {
    if (!scrolling) return;
    const timer = setInterval(() => {
      const element = list.current;
      if (!element) return;
      const max = element.scrollHeight - element.clientHeight;
      if (max > 0) {
        element.scrollTo({
          top:
            element.scrollTop >= max - 1
              ? 0
              : Math.min(element.scrollTop + 48, max),
          behavior: "smooth",
        });
      }
    }, 3000);
    return () => {
      clearInterval(timer);
      const element = list.current;
      if (element)
        element.scrollTo({ top: element.scrollTop, behavior: "instant" });
    };
  }, [scrolling]);
  return (
    <MonitorPanel
      className="monitor-alerts-panel"
      title={t("monitor.alertsTitle")}
      extra={
        <span className="monitor-live-count">
          {t("monitor.activeCount", { count: active })}
        </span>
      }
    >
      <div
        ref={list}
        className="monitor-alert-list"
        data-testid="monitor-alert-list"
        data-auto-scroll={scrolling}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocus={() => setFocused(true)}
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget))
            setFocused(false);
        }}
      >
        {snapshot.alerts.map((alert) => {
          const station = snapshot.stations.find(
            (entry) => entry.id === alert.stationId,
          );
          return (
            <button
              type="button"
              className={`monitor-alert-row ${alert.resolvedAt ? "is-resolved" : ""}`}
              key={alert.id}
              onClick={() => onSelect(alert.stationId)}
            >
              <time>
                {new Date(alert.occurredAt).toLocaleTimeString(locale, {
                  hour12: false,
                })}
              </time>
              <span className="monitor-alert-description">
                <strong>{station?.name}</strong>
                <small>
                  {t(`monitor.metric.${alert.metric}`)} · {alert.message}
                </small>
              </span>
              <span
                className="monitor-status"
                style={
                  {
                    "--status-color": alert.resolvedAt
                      ? riskColors.normal
                      : riskColors[alert.level],
                  } as CSSProperties
                }
              >
                {alert.resolvedAt
                  ? t("monitor.resolved")
                  : t(`monitor.level.${alert.level}`)}
              </span>
            </button>
          );
        })}
        {!snapshot.alerts.length && <p>{t("monitor.noAlerts")}</p>}
      </div>
    </MonitorPanel>
  );
}

export function RankingPanel({
  snapshot,
  onSelect,
}: {
  snapshot: MonitorSnapshot;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const ranking = [...snapshot.stations]
    .sort((left, right) => right.risk - left.risk)
    .slice(0, 5);
  return (
    <MonitorPanel
      title={t("monitor.rankingTitle")}
      extra={
        <span className="monitor-panel-caption">
          {t("monitor.rankingUnit")}
        </span>
      }
    >
      <ol className="monitor-ranking">
        {ranking.map((station, order) => (
          <li key={station.id}>
            <button type="button" onClick={() => onSelect(station.id)}>
              <span className="monitor-rank-index">
                {String(order + 1).padStart(2, "0")}
              </span>
              <span className="monitor-rank-label">
                {station.name}
                <i
                  style={{
                    width: `${station.risk}%`,
                    background: riskColors[station.level],
                  }}
                />
              </span>
              <strong>{Math.round(station.risk)}</strong>
            </button>
          </li>
        ))}
      </ol>
    </MonitorPanel>
  );
}

export function AssessmentPanel({ snapshot }: { snapshot: MonitorSnapshot }) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  return (
    <MonitorPanel
      className="monitor-assessment"
      title={t("monitor.assessmentTitle")}
      extra={
        <span className="monitor-simulated">
          {snapshot.assessment.simulated
            ? t("monitor.simulatedAnalysis")
            : t("monitor.analysis")}
        </span>
      }
    >
      <div className="monitor-assessment-copy">
        <RobotOutlined />
        <div>
          <p>{snapshot.assessment.summary}</p>
          <p className="monitor-advice">{snapshot.assessment.recommendation}</p>
        </div>
      </div>
      <div className="monitor-assessment-footer">
        <span>{t("monitor.analysisDisclaimer")}</span>
        <Button
          size="small"
          icon={<FileTextOutlined />}
          onClick={() => message.info(t("monitor.reportPending"))}
        >
          {t("monitor.generateReport")}
        </Button>
      </div>
    </MonitorPanel>
  );
}
