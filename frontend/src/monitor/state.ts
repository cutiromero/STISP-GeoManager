import type {
  MonitorEvent,
  MonitorSnapshot,
  MonitorStation,
  Readings,
  RiskLevel,
} from "./types";
import { metricIds } from "./types";

export const riskLevels: RiskLevel[] = [
  "normal",
  "attention",
  "warning",
  "critical",
];
export const riskColors: Record<RiskLevel, string> = {
  normal: "#50dfb0",
  attention: "#efce76",
  warning: "#ff975d",
  critical: "#ff667e",
};
export const typeColors = {
  hydrology: "#5ccfff",
  soil: "#e7bf72",
  forest: "#50dfb0",
};
export const metricUnits = {
  groundwater: "m",
  moisture: "%",
  ndvi: "",
  vigor: "/100",
};
export const metricPrecision = {
  groundwater: 2,
  moisture: 1,
  ndvi: 3,
  vigor: 1,
};

export function levelForRisk(risk: number): RiskLevel {
  return risk >= 75
    ? "critical"
    : risk >= 55
      ? "warning"
      : risk >= 35
        ? "attention"
        : "normal";
}

export function averageReadings(stations: MonitorStation[]): Readings {
  return Object.fromEntries(
    metricIds.map((metric) => [
      metric,
      stations.reduce((sum, station) => sum + station.readings[metric], 0) /
        Math.max(1, stations.length),
    ]),
  ) as Readings;
}

export function applyMonitorEvent(
  snapshot: MonitorSnapshot,
  event: MonitorEvent,
): MonitorSnapshot {
  if (event.sequence <= snapshot.sequence) return snapshot;
  let alerts = snapshot.alerts;
  if (event.alertChange?.kind === "raised") {
    const alert = event.alertChange.alert;
    alerts = [alert, ...alerts.filter((entry) => entry.id !== alert.id)].slice(
      0,
      40,
    );
  } else if (event.alertChange?.kind === "resolved") {
    const alertId = event.alertChange.alertId;
    alerts = alerts.map((entry) =>
      entry.id === alertId ? { ...entry, resolvedAt: event.occurredAt } : entry,
    );
  }
  return {
    ...snapshot,
    sequence: event.sequence,
    updatedAt: event.occurredAt,
    stations: snapshot.stations.map((station) =>
      station.id === event.station.id ? event.station : station,
    ),
    alerts,
    history: [...snapshot.history, event.sample].slice(-24),
    assessment: event.assessment,
  };
}
