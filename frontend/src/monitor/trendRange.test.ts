import { expect, it } from "vitest";
import { trendRange } from "./trendRange";
import type { MonitoringWorkspace } from "./useMonitoringWorkspace";

it("derives the observation count from actual dates instead of an arbitrary number", () => {
  const points = Array.from({ length: 61 }, (_, ordinal) => {
    const date = new Date(Date.UTC(2019, 8, 1) + ordinal * 8 * 86400000)
      .toISOString()
      .slice(0, 10);
    return {
      ordinal,
      date,
      endDate: new Date(new Date(date).getTime() + 7 * 86400000)
        .toISOString()
        .slice(0, 10),
    };
  });
  const time = points[60]!;
  const w = {
    time,
    allTimes: points,
    product: "gwis_ba",
  } as MonitoringWorkspace;
  expect(trendRange(w, "current")).toEqual({
    history: 1,
    start: time.date,
    end: time.endDate,
  });
  const month = trendRange(w, "month"),
    quarter = trendRange(w, "quarter"),
    year = trendRange(w, "year");
  expect(month.history).toBe(4);
  expect(month.start).toBe("2020-11-30");
  expect(quarter.history).toBeGreaterThan(month.history);
  expect(year.history).toBeGreaterThan(quarter.history);
  expect(year.history).toBeLessThanOrEqual(52);
  expect(points[points.length - year.history]!.date).toBe(year.start);
});
it("uses calendar months once for FCCI and aligns the available period at the start of the record", () => {
  const points = [1, 2, 3].map((month, index) => ({
    ordinal: index * 4,
    date: `2020-0${month}-01`,
    endDate: `2020-0${month}-08`,
  }));
  const w = {
    time: points[2],
    allTimes: points,
    product: "fcci_ba",
  } as MonitoringWorkspace;
  expect(trendRange(w, "current")).toEqual({
    history: 1,
    start: "2020-03-01",
    end: "2020-03-31",
  });
  expect(trendRange(w, "quarter")).toEqual({
    history: 3,
    start: "2020-01-01",
    end: "2020-03-31",
  });
});
