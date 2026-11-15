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

const periodKey = (item: MonitoringProduct) =>
  `${item.observedStart}/${item.observedEnd ?? item.observedStart}`;
function periodLabel(item: MonitoringProduct) {
  const start = item.observedStart!;
  if (item.observation?.periodMode === "monthly")
    return start.slice(0, 7).replace("-", ".");
  const end = item.observedEnd ?? start;
  if (
    item.extraction?.inputPeriods.length &&
    item.extraction.inputPeriods.every((value) => /^\d{4}-\d{2}$/.test(value))
  ) {
    const first = item.extraction.inputPeriods[0]!;
    const last =
      item.extraction.inputPeriods[item.extraction.inputPeriods.length - 1]!;
    return first === last
      ? first.replace("-", ".")
      : `${first.replace("-", ".")}–${first.slice(0, 4) === last.slice(0, 4) ? last.slice(5) : last.replace("-", ".")}`;
  }
  return start === end
    ? start.replace(/-/g, ".")
    : `${start.replace(/-/g, ".")}–${start.slice(0, 4) === end.slice(0, 4) ? end.slice(5).replace("-", ".") : end.replace(/-/g, ".")}`;
}

export default function MonitorTimeline({
  items,
  selected,
  onSelect,
  onMore,
}: {
  items: MonitoringProduct[];
  selected?: MonitoringProduct;
  onSelect: (id: number) => void;
  onMore?: () => void;
}) {
  const [playing, setPlaying] = useState(false);
  const callback = useRef(onSelect);
  callback.current = onSelect;
  const periods = useMemo(() => {
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
    return [...grouped.values()].sort((a, b) =>
      a.observedStart!.localeCompare(b.observedStart!),
    );
  }, [items, selected?.id, selected?.observation?.product]);
  const key = selected?.observedStart ? periodKey(selected) : undefined;
  const index = periods.findIndex((item) => periodKey(item) === key);
  const move = (direction: number) => {
    const next =
      periods[
        (Math.max(0, index) + direction + periods.length) % periods.length
      ];
    if (next) callback.current(next.id);
  };
  const moveRef = useRef(move);
  moveRef.current = move;
  useEffect(() => {
    if (!playing || periods.length < 2) return;
    const timer = setInterval(() => {
      if (document.visibilityState !== "hidden") moveRef.current(1);
    }, 2500);
    return () => clearInterval(timer);
  }, [playing, periods.length]);
  useEffect(() => {
    if (!selected?.observedStart || periods.length < 2) setPlaying(false);
  }, [selected?.observedStart, periods.length]);
  if (!selected?.observedStart || !periods.length) return null;
  const single = periods.length === 1;
  return (
    <div
      className="monitor-timeline"
      data-single={single}
      aria-label={single ? "成果观测时段" : "成果时间轴"}
    >
      {single ? (
        <span
          title={
            selected.extraction
              ? `三期影像联合解译：${selected.extraction.inputPeriods.join("、")}`
              : undefined
          }
        >
          {selected.extraction ? "联合解译" : "观测期"}{" "}
          <strong>{periodLabel(selected)}</strong>
        </span>
      ) : (
        <>
          <Tooltip title="上一期">
            <Button
              size="small"
              type="text"
              aria-label="上一期"
              icon={<LeftOutlined />}
              onClick={() => {
                setPlaying(false);
                move(-1);
              }}
            />
          </Tooltip>
          <Select
            size="small"
            aria-label="切换观测日期"
            value={key}
            options={periods.map((item) => ({
              value: periodKey(item),
              label: periodLabel(item),
            }))}
            onChange={(value) => {
              setPlaying(false);
              const item = periods.find((row) => periodKey(row) === value);
              if (item) callback.current(item.id);
            }}
          />
          <Tooltip title="下一期">
            <Button
              size="small"
              type="text"
              aria-label="下一期"
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
                {playing ? "停止" : "循环"}
              </span>
            </Button>
          </Tooltip>
        </>
      )}
      {onMore && (
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
