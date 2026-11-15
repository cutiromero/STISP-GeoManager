import { Button, Select, Space } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import type { MonitoringProduct } from "../api/generated/types.gen";

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
  const ordered = useMemo(
    () =>
      items
        .filter(
          (item) =>
            item.observedStart &&
            (!selected?.observation ||
              item.observation?.product === selected.observation.product),
        )
        .sort(
          (a, b) =>
            a.observedStart!.localeCompare(b.observedStart!) || a.id - b.id,
        ),
    [items, selected?.observation?.product],
  );
  const index = ordered.findIndex((item) => item.id === selected?.id);
  useEffect(() => {
    if (!playing || ordered.length < 2 || document.visibilityState === "hidden")
      return;
    const timer = setTimeout(() => {
      const next = ordered[index + 1];
      if (next && document.visibilityState !== "hidden")
        callback.current(next.id);
      else setPlaying(false);
    }, 2500);
    return () => clearTimeout(timer);
  }, [playing, ordered, index]);
  return (
    <div className="monitor-timeline" aria-label="成果时间轴">
      <Space>
        <strong>成果时间轴</strong>
        <Button
          size="small"
          disabled={ordered.length < 2}
          onClick={() => {
            if (!playing && index === ordered.length - 1)
              onSelect(ordered[0]!.id);
            setPlaying(!playing);
          }}
        >
          {playing ? "停止播放" : "播放时序"}
        </Button>
        {onMore && (
          <Button size="small" type="link" onClick={onMore}>
            更早成果
          </Button>
        )}
      </Space>
      <Select
        aria-label="成果观测时间"
        value={selected?.id}
        onChange={(id) => {
          setPlaying(false);
          onSelect(id);
        }}
        options={[
          ...ordered.map((item) => ({
            value: item.id,
            label: `${item.observedStart} — ${item.observedEnd ?? item.observedStart} · ${item.name}`,
          })),
          ...items
            .filter((item) => !item.observedStart)
            .map((item) => ({
              value: item.id,
              label: `时间未登记 · ${item.name}`,
            })),
        ]}
      />
      {ordered.length > 1 && (
        <input
          aria-label="切换成果时期"
          type="range"
          min={0}
          max={ordered.length - 1}
          value={Math.max(0, index)}
          onChange={(event) => {
            setPlaying(false);
            onSelect(ordered[Number(event.target.value)]!.id);
          }}
        />
      )}
      <span>
        {selected?.observedStart
          ? `${selected.observedStart} — ${selected.observedEnd ?? selected.observedStart}`
          : "时间未登记"}
      </span>
    </div>
  );
}
