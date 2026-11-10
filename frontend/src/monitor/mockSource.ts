import i18n, { type AppLocale } from "../i18n";
import { createMockSnapshot, mockAssessment } from "./mockData";
import { applyMonitorEvent, averageReadings, levelForRisk } from "./state";
import type { MetricId, MonitorDataSource, MonitorEvent } from "./types";

export interface VisibilitySource {
  readonly hidden: boolean;
  addEventListener(type: "visibilitychange", listener: () => void): void;
  removeEventListener(type: "visibilitychange", listener: () => void): void;
}

export interface MockMonitorOptions {
  intervalMs?: number;
  seed?: number;
  now?: () => number;
  locale?: AppLocale;
  visibility?: VisibilitySource;
}

export const mockMonitorDefaults = { intervalMs: 4000, seed: 20261110 };

export function createMockMonitorSource(
  options: MockMonitorOptions = {},
): MonitorDataSource {
  const intervalMs = Math.max(
    100,
    options.intervalMs ?? mockMonitorDefaults.intervalMs,
  );
  const now = options.now ?? Date.now;
  const visibility =
    options.visibility ??
    (typeof document === "undefined" ? undefined : document);
  const t = i18n.getFixedT(options.locale ?? "zh-CN");
  let randomState = (options.seed ?? mockMonitorDefaults.seed) >>> 0;
  const random = () => {
    randomState = (Math.imul(1664525, randomState) + 1013904223) >>> 0;
    return randomState / 4294967296;
  };
  let snapshot = createMockSnapshot(t, now(), intervalMs);
  let timer: ReturnType<typeof setInterval> | undefined;
  const listeners = new Set<(event: MonitorEvent) => void>();
  const tick = () => {
    if (visibility?.hidden || !listeners.size) return;
    const sequence = snapshot.sequence + 1;
    const occurredAt = new Date(now()).toISOString();
    const activeAlert = snapshot.alerts.find((alert) => !alert.resolvedAt);
    const resolving = sequence % 3 === 0 && activeAlert;
    const chosen = resolving
      ? snapshot.stations.find(
          (station) => station.id === activeAlert.stationId,
        )!
      : snapshot.stations[Math.floor(random() * snapshot.stations.length)];
    if (!chosen) return;
    const movement = resolving ? -0.18 : (random() - 0.45) * 0.16;
    const risk = Math.max(
      8,
      Math.min(94, chosen.risk + (resolving ? -10 : movement * 22)),
    );
    const readings = {
      groundwater: Number(
        Math.max(
          1,
          Math.min(9, chosen.readings.groundwater + movement),
        ).toFixed(2),
      ),
      moisture: Number(
        Math.max(
          5,
          Math.min(40, chosen.readings.moisture - movement * 3),
        ).toFixed(1),
      ),
      ndvi: Number(
        Math.max(
          0.1,
          Math.min(0.85, chosen.readings.ndvi - movement * 0.025),
        ).toFixed(3),
      ),
      vigor: Number(
        Math.max(
          20,
          Math.min(98, chosen.readings.vigor - movement * 2),
        ).toFixed(1),
      ),
    };
    const station = {
      ...chosen,
      readings,
      risk,
      level: levelForRisk(risk),
      updatedAt: occurredAt,
      recentEvent: t(
        resolving ? "monitor.resolvedEvent" : "monitor.readingEvent",
      ),
    };
    const metric: MetricId = sequence % 2 ? "groundwater" : "moisture";
    const event: MonitorEvent = {
      sequence,
      occurredAt,
      station,
      sample: {
        id: `sample-${sequence}`,
        observedAt: occurredAt,
        readings: averageReadings(
          snapshot.stations.map((entry) =>
            entry.id === station.id ? station : entry,
          ),
        ),
      },
      alertChange: resolving
        ? { kind: "resolved", alertId: activeAlert.id }
        : {
            kind: "raised",
            alert: {
              id: `alert-${sequence}`,
              stationId: station.id,
              occurredAt,
              metric,
              level: station.level === "normal" ? "attention" : station.level,
              message: t(
                metric === "groundwater"
                  ? "monitor.waterAlert"
                  : "monitor.soilAlert",
              ),
            },
          },
      assessment: mockAssessment(t, station, occurredAt),
    };
    snapshot = applyMonitorEvent(snapshot, event);
    const recipients = Array.from(listeners);
    for (const listener of recipients) {
      if (listeners.has(listener)) listener(structuredClone(event));
    }
  };
  const stop = () => {
    clearInterval(timer);
    timer = undefined;
  };
  const resume = () => {
    stop();
    if (!visibility?.hidden && listeners.size)
      timer = setInterval(tick, intervalMs);
  };
  return {
    getSnapshot: async () => structuredClone(snapshot),
    subscribe(listener) {
      const subscription = (event: MonitorEvent) => listener(event);
      listeners.add(subscription);
      if (listeners.size === 1) {
        visibility?.addEventListener("visibilitychange", resume);
        resume();
      }
      let subscribed = true;
      return () => {
        if (!subscribed) return;
        subscribed = false;
        listeners.delete(subscription);
        if (!listeners.size) {
          stop();
          visibility?.removeEventListener("visibilitychange", resume);
        }
      };
    },
  };
}
