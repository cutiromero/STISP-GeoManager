import {
  CaretRightOutlined,
  PauseOutlined,
  LeftOutlined,
  RightOutlined,
  MoreOutlined,
} from "@ant-design/icons";
import { Button, Select, Tooltip } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import type { MonitoringProduct } from "../api/generated/types.gen";
import type { MonitoringWorkspace } from "./useMonitoringWorkspace";
import { useMonitorDisplayState } from "./monitorDisplayState";

type Entry = {
  key: string;
  label: string;
  title: string;
  activate: () => void;
};
const periodKey = (item: MonitoringProduct) =>
  `${item.observedStart}/${item.observedEnd ?? item.observedStart}`;
function periodLabel(item: MonitoringProduct) {
  const start = item.observedStart!;
  if (item.observation?.periodMode === "monthly")
    return start.slice(0, 7).replace("-", ".");
  if (
    item.extraction?.inputPeriods.length &&
    item.extraction.inputPeriods.every((value) => /^\d{4}-\d{2}$/.test(value))
  ) {
    const first = item.extraction.inputPeriods[0]!,
      last =
        item.extraction.inputPeriods[item.extraction.inputPeriods.length - 1]!;
    return first === last
      ? first.replace("-", ".")
      : `${first.replace("-", ".")}–${first.slice(0, 4) === last.slice(0, 4) ? last.slice(5) : last.replace("-", ".")}`;
  }
  return start.replace(/-/g, ".");
}
export default function MonitorTimeline({
  items,
  selected,
  onSelect,
  onMore,
  workspace: w,
}: {
  items: MonitoringProduct[];
  selected?: MonitoringProduct;
  onSelect: (id: number) => void;
  onMore?: () => void;
  workspace?: MonitoringWorkspace;
}) {
  const [playing, setPlaying] = useState(false);
  const display = useMonitorDisplayState();
  const sourceMode = w?.timeTarget === "source";
  const resultEntries = useMemo(() => {
    const grouped = new Map<string, MonitoringProduct>();
    for (const item of [...items].sort((a, b) => b.id - a.id)) {
      if (
        !item.observedStart ||
        (selected?.observation &&
          item.observation?.product !== selected.observation.product)
      )
        continue;
      const key = periodKey(item);
      if (!grouped.has(key) || item.id === selected?.id) grouped.set(key, item);
    }
    return [...grouped.values()]
      .sort((a, b) => a.observedStart!.localeCompare(b.observedStart!))
      .map((item) => ({
        key: periodKey(item),
        label: periodLabel(item),
        title: `${item.observedStart} — ${item.observedEnd ?? item.observedStart}`,
        activate: () => onSelect(item.id),
      }));
  }, [items, selected?.id, selected?.observation?.product, onSelect]);
  const rawEntries: Entry[] =
    w?.scene === "wildfire"
      ? w.allTimes.map((point) => ({
          key: `raw:${point.ordinal}`,
          label:
            w.product === "fcci_ba"
              ? point.date.slice(0, 7).replace("-", ".")
              : point.date.replace(/-/g, "."),
          title: `${point.date} — ${point.endDate}`,
          activate: () => w.selectTime(point.ordinal),
        }))
      : (w?.catalog?.assets ?? [])
          .filter((asset) => asset.metadata.period?.startsAt)
          .sort((a, b) =>
            a.metadata.period!.startsAt!.localeCompare(
              b.metadata.period!.startsAt!,
            ),
          )
          .map((asset) => ({
            key: `raw:${asset.resource.id}`,
            label: asset.metadata
              .period!.startsAt!.slice(
                0,
                asset.metadata.period!.precision === "month" ? 7 : 10,
              )
              .replace(/-/g, "."),
            title: asset.resource.name,
            activate: () => w?.setSourceId(asset.resource.id),
          }));
  const entries = sourceMode ? rawEntries : resultEntries;
  const currentKey = sourceMode
    ? w?.scene === "wildfire"
      ? w.time
        ? `raw:${w.time.ordinal}`
        : undefined
      : w?.source
        ? `raw:${w.source.resource.id}`
        : undefined
    : selected?.observedStart
      ? periodKey(selected)
      : undefined;
  const index = entries.findIndex((item) => item.key === currentKey);
  const busy = Boolean(sourceMode ? w?.rawPreviewBusy : display.busy);
  const next = useRef(() => {});
  const move = (direction: number) => {
    const base = index < 0 ? (direction > 0 ? -1 : 0) : index;
    entries[(base + direction + entries.length) % entries.length]?.activate();
  };
  next.current = () => {
    if (!busy) move(1);
  };
  useEffect(() => {
    if (!playing || entries.length < 2) return;
    const timer = setInterval(() => {
      if (document.visibilityState !== "hidden") next.current();
    }, 2500);
    return () => clearInterval(timer);
  }, [playing, entries.length]);
  useEffect(() => setPlaying(false), [sourceMode]);
  useEffect(() => {
    if (display.failed) setPlaying(false);
  }, [display.failed]);
  const single = entries.length < 2;
  if (!w && (!selected?.observedStart || !entries.length)) return null;
  return (
    <div
      className="monitor-timeline"
      data-single={single}
      data-target={sourceMode ? "source" : "result"}
      aria-label={
        sourceMode ? "原图时间轴" : single ? "成果观测时段" : "成果时间轴"
      }
    >
      {w && (
        <Select
          className="monitor-time-target"
          size="small"
          aria-label="时间对象"
          value={w.timeTarget}
          options={[
            { value: "source", label: "原图" },
            { value: "result", label: "成果" },
          ]}
          onChange={(value) => {
            setPlaying(false);
            w.selectTimeTarget(value);
          }}
        />
      )}
      {single ? (
        <span title={entries[0]?.title}>
          {!sourceMode && selected?.extraction
            ? "联合解译"
            : sourceMode
              ? "影像期"
              : "观测期"}{" "}
          <strong>{entries[0]?.label ?? "未标注时间"}</strong>
        </span>
      ) : (
        <>
          <Tooltip title="上一期">
            <Button
              size="small"
              type="text"
              aria-label="上一期"
              disabled={busy}
              icon={<LeftOutlined />}
              onClick={() => {
                setPlaying(false);
                move(-1);
              }}
            />
          </Tooltip>
          <Select
            className="monitor-time-date"
            size="small"
            aria-label="切换观测日期"
            showSearch
            optionFilterProp="label"
            placeholder="选择影像日期"
            value={index < 0 ? undefined : currentKey}
            loading={busy}
            disabled={busy}
            options={entries.map((entry) => ({
              value: entry.key,
              label: entry.label,
              title: entry.title,
            }))}
            filterOption={(input, option) =>
              String(option?.label ?? "")
                .replace(/\D/g, "")
                .includes(input.replace(/\D/g, ""))
            }
            onChange={(key) => {
              setPlaying(false);
              entries.find((entry) => entry.key === key)?.activate();
            }}
          />
          <Tooltip title="下一期">
            <Button
              size="small"
              type="text"
              aria-label="下一期"
              disabled={busy}
              icon={<RightOutlined />}
              onClick={() => {
                setPlaying(false);
                move(1);
              }}
            />
          </Tooltip>
          <Tooltip title={playing ? "停止循环" : "循环播放"}>
            <Button
              size="small"
              type="text"
              aria-label={playing ? "停止循环" : "循环播放"}
              icon={playing ? <PauseOutlined /> : <CaretRightOutlined />}
              onClick={() => setPlaying((value) => !value)}
            >
              <span className="monitor-loop-label">
                {playing ? (busy ? "缓冲" : "停止") : "循环"}
              </span>
            </Button>
          </Tooltip>
        </>
      )}
      {!sourceMode && onMore && (
        <Tooltip title="载入更早成果">
          <Button
            size="small"
            type="text"
            aria-label="载入更早成果"
            icon={<MoreOutlined />}
            onClick={onMore}
          />
        </Tooltip>
      )}
    </div>
  );
}
