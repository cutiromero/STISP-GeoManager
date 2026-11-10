import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyMonitorEvent, averageReadings } from "./state";
import { createMockMonitorSource, type VisibilitySource } from "./mockSource";
import type { MonitorEvent } from "./types";

class Visibility extends EventTarget implements VisibilitySource {
  hidden = false;
  setHidden(hidden: boolean) {
    this.hidden = hidden;
    this.dispatchEvent(new Event("visibilitychange"));
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-10T08:00:00Z"));
});
afterEach(() => vi.useRealTimers());

describe("生态监测模拟数据源", () => {
  it("相同种子、时钟与配置生成相同事件序列，不同种子产生不同读数", async () => {
    const events: MonitorEvent[][] = [[], [], []];
    const sources = [17, 17, 18].map((seed) =>
      createMockMonitorSource({
        seed,
        intervalMs: 1000,
        visibility: new Visibility(),
      }),
    );
    const unsubscribe = sources.map((source, order) =>
      source.subscribe((event) => events[order]!.push(event)),
    );
    vi.advanceTimersByTime(15000);
    expect(events[0]).toHaveLength(15);
    expect(events[0]).toEqual(events[1]);
    expect(events[0]).not.toEqual(events[2]);
    expect(events[0]!.map((event) => event.alertChange?.kind)).toContain(
      "resolved",
    );
    expect(events[0]!.map((event) => event.alertChange?.kind)).toContain(
      "raised",
    );
    const snapshot = await sources[0]!.getSnapshot();
    expect(snapshot.sequence).toBe(15);
    expect(snapshot.history).toHaveLength(24);
    expect(snapshot.history[23]!.readings).toEqual(
      averageReadings(snapshot.stations),
    );
    expect(
      snapshot.stations.every(
        (station) =>
          station.coordinates[0] >= 78 &&
          station.coordinates[0] <= 89 &&
          station.coordinates[1] >= 38 &&
          station.coordinates[1] <= 42,
      ),
    ).toBe(true);
    unsubscribe.forEach((stop) => stop());
    expect(vi.getTimerCount()).toBe(0);
  });

  it("只在有订阅时产出，共享一个定时器，重复取消不会泄漏", async () => {
    const visibility = new Visibility();
    const add = vi.spyOn(visibility, "addEventListener");
    const remove = vi.spyOn(visibility, "removeEventListener");
    const source = createMockMonitorSource({ intervalMs: 1000, visibility });
    const first = vi.fn();
    const second = vi.fn();
    expect(vi.getTimerCount()).toBe(0);
    const stopFirst = source.subscribe(first);
    const stopSecond = source.subscribe(second);
    expect(vi.getTimerCount()).toBe(1);
    expect(add).toHaveBeenCalledOnce();
    vi.advanceTimersByTime(2000);
    expect(first).toHaveBeenCalledTimes(2);
    expect(second).toHaveBeenCalledTimes(2);
    stopFirst();
    stopFirst();
    vi.advanceTimersByTime(1000);
    expect(first).toHaveBeenCalledTimes(2);
    expect(second).toHaveBeenCalledTimes(3);
    stopSecond();
    expect(remove).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10000);
    expect((await source.getSnapshot()).sequence).toBe(3);
  });

  it("回调内重新订阅时不重复派发当前事件", () => {
    const source = createMockMonitorSource({ intervalMs: 1000 });
    let reconnect = true;
    let stop: () => void;
    const listener = vi.fn(() => {
      if (!reconnect) return;
      reconnect = false;
      stop();
      stop = source.subscribe(listener);
    });
    stop = source.subscribe(listener);
    vi.advanceTimersByTime(1000);
    expect(listener).toHaveBeenCalledOnce();
    vi.advanceTimersByTime(1000);
    expect(listener).toHaveBeenCalledTimes(2);
    stop();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("隐藏时停止定时器，恢复前台后继续且不补发隐藏期间事件", async () => {
    const visibility = new Visibility();
    const source = createMockMonitorSource({ intervalMs: 1000, visibility });
    const listener = vi.fn();
    const stop = source.subscribe(listener);
    vi.advanceTimersByTime(1000);
    visibility.setHidden(true);
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(120000);
    expect(listener).toHaveBeenCalledTimes(1);
    expect((await source.getSnapshot()).sequence).toBe(1);
    visibility.setHidden(false);
    vi.advanceTimersByTime(999);
    expect(listener).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(listener).toHaveBeenCalledTimes(2);
    stop();
  });

  it("初始隐藏时不启动，快照与每个订阅收到独立副本", async () => {
    const visibility = new Visibility();
    visibility.setHidden(true);
    const source = createMockMonitorSource({ intervalMs: 1000, visibility });
    const first = vi.fn((event: MonitorEvent) => {
      event.station.name = "modified";
    });
    const second = vi.fn();
    const stopFirst = source.subscribe(first);
    const stopSecond = source.subscribe(second);
    const initial = await source.getSnapshot();
    initial.stations[0]!.name = "modified";
    expect((await source.getSnapshot()).stations[0]!.name).not.toBe("modified");
    expect(vi.getTimerCount()).toBe(0);
    visibility.setHidden(false);
    vi.advanceTimersByTime(1000);
    expect(second.mock.calls[0]![0].station.name).not.toBe("modified");
    stopFirst();
    stopSecond();
  });

  it("增量应用忽略重放，并将解除事件标注到原预警", async () => {
    const source = createMockMonitorSource({ intervalMs: 1000 });
    const initial = await source.getSnapshot();
    const events: MonitorEvent[] = [];
    const stop = source.subscribe((event) => events.push(event));
    vi.advanceTimersByTime(3000);
    const updated = events.reduce(applyMonitorEvent, initial);
    expect(updated).toEqual(await source.getSnapshot());
    expect(applyMonitorEvent(updated, events[0]!)).toBe(updated);
    expect(updated.alerts.some((alert) => alert.resolvedAt)).toBe(true);
    expect(initial.sequence).toBe(0);
    expect(initial.alerts.every((alert) => !alert.resolvedAt)).toBe(true);
    stop();
  });
});
