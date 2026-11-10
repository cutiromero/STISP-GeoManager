import type { TFunction } from "i18next";
import { averageReadings, levelForRisk } from "./state";
import type {
  MonitorAssessment,
  MonitorSnapshot,
  MonitorStation,
  StationType,
} from "./types";

const sites: Array<[string, number, number, StationType, number]> = [
  ["aksu", 80.25, 40.65, "hydrology", 29],
  ["yarkand", 78.25, 38.55, "hydrology", 38],
  ["hotan", 80.65, 39.1, "soil", 43],
  ["alar", 81.2, 40.55, "forest", 26],
  ["shaya", 82.8, 40.65, "forest", 46],
  ["luntai", 84.25, 41.05, "soil", 32],
  ["yingbaza", 85.35, 41.05, "forest", 53],
  ["qiala", 86.3, 40.9, "hydrology", 64],
  ["daxihaizi", 87.55, 40.58, "hydrology", 58],
  ["yingsu", 87.95, 40.05, "soil", 78],
  ["alagan", 88.25, 39.45, "forest", 72],
  ["taitema", 88.35, 39.15, "hydrology", 39],
];

export function mockAssessment(
  t: TFunction,
  station: MonitorStation,
  at: string,
): MonitorAssessment {
  return {
    updatedAt: at,
    summary: t("monitor.analysisSummary", {
      name: station.name,
      level: t(`monitor.level.${station.level}`),
    }),
    recommendation: t("monitor.analysisAdvice"),
    simulated: true,
  };
}

export function createMockSnapshot(
  t: TFunction,
  now: number,
  intervalMs: number,
): MonitorSnapshot {
  const updatedAt = new Date(now).toISOString();
  const stations: MonitorStation[] = sites.map(
    ([id, longitude, latitude, type, risk]) => ({
      id,
      name: t(`monitor.sites.${id}`),
      section: t(
        `monitor.sections.${["aksu", "yarkand", "hotan"].includes(id) ? "tributary" : "mainstream"}`,
      ),
      coordinates: [longitude, latitude],
      type,
      readings: {
        groundwater: Number((2.8 + risk * 0.055).toFixed(2)),
        moisture: Number((29 - risk * 0.18).toFixed(1)),
        ndvi: Number((0.69 - risk * 0.004).toFixed(3)),
        vigor: Number((96 - risk * 0.48).toFixed(1)),
      },
      risk,
      level: levelForRisk(risk),
      updatedAt,
      recentEvent: t("monitor.baselineEvent"),
    }),
  );
  const links: Array<[string, string]> = [
    ["aksu", "alar"],
    ["yarkand", "alar"],
    ["hotan", "alar"],
    ["alar", "shaya"],
    ["shaya", "luntai"],
    ["luntai", "yingbaza"],
    ["yingbaza", "qiala"],
    ["qiala", "daxihaizi"],
    ["daxihaizi", "yingsu"],
    ["yingsu", "alagan"],
    ["alagan", "taitema"],
  ];
  const readings = averageReadings(stations);
  return {
    sequence: 0,
    updatedAt,
    stations,
    connections: links.map(([from, to]) => ({
      id: `${from}-${to}`,
      from,
      to,
      kind: "upstream",
    })),
    alerts: [stations[9]!, stations[10]!, stations[7]!, stations[4]!].map(
      (station, order) => ({
        id: `baseline-${station.id}`,
        stationId: station.id,
        occurredAt: new Date(now - order * intervalMs).toISOString(),
        metric: "groundwater",
        level: station.level === "normal" ? "attention" : station.level,
        message: t("monitor.waterAlert"),
      }),
    ),
    history: Array.from({ length: 24 }, (_, order) => {
      const offset = Math.sin((order - 23) / 4) * 0.08;
      return {
        id: `baseline-${order}`,
        observedAt: new Date(now - (23 - order) * intervalMs).toISOString(),
        readings: {
          groundwater: readings.groundwater + offset,
          moisture: readings.moisture - offset * 3,
          ndvi: readings.ndvi + offset * 0.04,
          vigor: readings.vigor + offset * 4,
        },
      };
    }),
    assessment: mockAssessment(t, stations[9]!, updatedAt),
  };
}
