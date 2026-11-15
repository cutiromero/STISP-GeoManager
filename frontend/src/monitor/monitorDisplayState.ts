import { createContext, useContext } from "react";
import type { MonitorLayerState } from "./MonitorLayerStatus";

export const MonitorLayerStates = createContext<
  Record<string, MonitorLayerState>
>({});

export function useMonitorDisplayState() {
  const values = Object.values(useContext(MonitorLayerStates));
  return {
    busy: values.some((value) => value.loading || value.updating),
    failed: values.some((value) => Boolean(value.error)),
  };
}
