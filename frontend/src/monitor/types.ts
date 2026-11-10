export const metricIds = ["groundwater", "moisture", "ndvi", "vigor"] as const;
export type MetricId = (typeof metricIds)[number];
export type Readings = Record<MetricId, number>;
export type RiskLevel = "normal" | "attention" | "warning" | "critical";
export type StationType = "hydrology" | "soil" | "forest";

export interface MonitorStation {
  id: string;
  name: string;
  section: string;
  coordinates: [longitude: number, latitude: number];
  type: StationType;
  readings: Readings;
  risk: number;
  level: RiskLevel;
  updatedAt: string;
  recentEvent: string;
}

export interface MonitorConnection {
  id: string;
  from: string;
  to: string;
  kind: "upstream" | "reserve";
}

export interface MonitorAlert {
  id: string;
  stationId: string;
  occurredAt: string;
  resolvedAt?: string;
  metric: MetricId;
  level: Exclude<RiskLevel, "normal">;
  message: string;
}

export interface MonitorAssessment {
  updatedAt: string;
  summary: string;
  recommendation: string;
  simulated: boolean;
}

export interface MonitorSample {
  id: string;
  observedAt: string;
  readings: Readings;
}

export interface MonitorSnapshot {
  sequence: number;
  updatedAt: string;
  stations: MonitorStation[];
  connections: MonitorConnection[];
  alerts: MonitorAlert[];
  history: MonitorSample[];
  assessment: MonitorAssessment;
}

export interface MonitorEvent {
  sequence: number;
  occurredAt: string;
  station: MonitorStation;
  sample: MonitorSample;
  alertChange?:
    | { kind: "raised"; alert: MonitorAlert }
    | { kind: "resolved"; alertId: string };
  assessment: MonitorAssessment;
}

export interface MonitorDataSource {
  getSnapshot(): Promise<MonitorSnapshot>;
  subscribe(listener: (event: MonitorEvent) => void): () => void;
}
