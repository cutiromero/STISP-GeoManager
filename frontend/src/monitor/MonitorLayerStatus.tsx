import { Button, Drawer, Spin } from "antd";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { LiveLayerLegend } from "../map/liveLegendData";

export type MonitorLayerState = {
  title: string;
  loading?: boolean;
  updating?: boolean;
  error?: string;
  legend?: LiveLayerLegend;
};
const Dispatch = createContext<{
  update: (id: string, value: MonitorLayerState) => void;
  remove: (id: string) => void;
} | null>(null);
const States = createContext<Record<string, MonitorLayerState>>({});

export function MonitorLayerStatusProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [states, setStates] = useState<Record<string, MonitorLayerState>>({});
  const dispatch = useMemo(
    () => ({
      update: (id: string, value: MonitorLayerState) =>
        setStates((previous) =>
          JSON.stringify(previous[id]) === JSON.stringify(value)
            ? previous
            : { ...previous, [id]: value },
        ),
      remove: (id: string) =>
        setStates((previous) => {
          if (!(id in previous)) return previous;
          const next = { ...previous };
          delete next[id];
          return next;
        }),
    }),
    [],
  );
  return (
    <Dispatch.Provider value={dispatch}>
      <States.Provider value={states}>{children}</States.Provider>
    </Dispatch.Provider>
  );
}

export function useMonitorLayerStatus() {
  const id = useId();
  const dispatch = useContext(Dispatch);
  const update = useCallback(
    (value: MonitorLayerState) => dispatch?.update(id, value),
    [dispatch, id],
  );
  useEffect(() => () => dispatch?.remove(id), [dispatch, id]);
  return update;
}

export function MonitorDataStatus({
  title,
  loading,
  error,
}: MonitorLayerState) {
  const update = useMonitorLayerStatus();
  useEffect(
    () => update({ title, loading, error }),
    [update, title, loading, error],
  );
  return null;
}

export function MonitorLayerStatusBar() {
  const values = Object.values(useContext(States));
  const [legend, setLegend] = useState<LiveLayerLegend>();
  const pending = values.filter((value) => value.loading || value.updating);
  const errors = values.filter((value) => value.error);
  const legends = values
    .filter((value) => value.legend)
    .map((value) => value.legend!);
  return (
    <>
      <div
        className="monitor-status-bar"
        role="status"
        aria-live="polite"
        aria-label="地图与数据状态"
      >
        <div
          className={
            errors.length ? "monitor-status-error" : "monitor-status-message"
          }
        >
          {errors.length ? (
            errors.map((value) => (
              <span key={`${value.title}:${value.error}`}>
                <span>{value.title}：</span>
                <span>{value.error}</span>
              </span>
            ))
          ) : pending.length ? (
            <>
              <Spin size="small" />
              <span>
                {pending
                  .map(
                    (value) =>
                      `${value.title} · ${value.updating ? "更新显示" : "加载中"}`,
                  )
                  .join("；")}
              </span>
            </>
          ) : (
            <span>地图与数据已就绪</span>
          )}
        </div>
        {legends.map((value) => (
          <Button
            key={value.id}
            size="small"
            type="link"
            onClick={() => setLegend(value)}
          >
            图例 · {value.title}
          </Button>
        ))}
      </div>
      <Drawer
        open={Boolean(legend)}
        onClose={() => setLegend(undefined)}
        title={legend?.title ?? "图例"}
        size={360}
      >
        {legend && (
          <div className="monitor-layer-legend">
            {legend.note && <p>{legend.note}</p>}
            {legend.gradient && (
              <div className="remote-legend-gradient">
                <div
                  style={{
                    background: `linear-gradient(90deg, ${legend.gradient.colors.join(",")})`,
                    opacity: legend.opacity,
                  }}
                />
                <span>{legend.gradient.low}</span>
                <span>{legend.gradient.high}</span>
              </div>
            )}
            {legend.entries.map((entry) => (
              <div className="remote-legend-entry" key={entry.id}>
                <span
                  style={{ background: entry.color, opacity: legend.opacity }}
                />
                <span>{entry.label}</span>
              </div>
            ))}
          </div>
        )}
      </Drawer>
    </>
  );
}
