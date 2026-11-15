import type { MonitoringWorkspace } from "./useMonitoringWorkspace";

export type TrendSpan = "current" | "month" | "quarter" | "year";
export const trendOptions = [
  { value: "current", label: "仅当前期" },
  { value: "month", label: "近1个月" },
  { value: "quarter", label: "近3个月" },
  { value: "year", label: "近1年" },
];
export function trendRange(workspace: MonitoringWorkspace, span: TrendSpan) {
  const time = workspace.time;
  if (!time) return { history: 1, start: "", end: "" };
  const monthly = workspace.product === "fcci_ba";
  const end = monthly
    ? new Date(
        Date.UTC(
          Number(time.date.slice(0, 4)),
          Number(time.date.slice(5, 7)),
          0,
        ),
      )
        .toISOString()
        .slice(0, 10)
    : time.endDate;
  if (span === "current")
    return {
      history: 1,
      start: monthly ? time.date.slice(0, 7) + "-01" : time.date,
      end,
    };
  const months = span === "month" ? 1 : span === "quarter" ? 3 : 12;
  const day = new Date(end + "T00:00:00Z");
  const year = day.getUTCFullYear(),
    month = day.getUTCMonth() - months;
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const boundary = new Date(
    Date.UTC(year, month, Math.min(day.getUTCDate(), lastDay)),
  )
    .toISOString()
    .slice(0, 10);
  const available = workspace.allTimes.filter(
    (point) => point.date >= boundary && point.ordinal <= time.ordinal,
  );
  const first = available[0] ?? time;
  const history = monthly
    ? (Number(time.date.slice(0, 4)) - Number(first.date.slice(0, 4))) * 12 +
      Number(time.date.slice(5, 7)) -
      Number(first.date.slice(5, 7)) +
      1
    : time.ordinal - first.ordinal + 1;
  return {
    history,
    start: monthly ? first.date.slice(0, 7) + "-01" : first.date,
    end,
  };
}
