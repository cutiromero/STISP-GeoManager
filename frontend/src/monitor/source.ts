import type { AppLocale } from "../i18n";
import type { ProjectMonitorConfig } from "../api/generated/types.gen";
import { createMockMonitorSource } from "./mockSource";
import type { MonitorDataSource } from "./types";

export function createMonitorSource(context: {
  projectId: number;
  locale: AppLocale;
  config: ProjectMonitorConfig;
}): MonitorDataSource | undefined {
  if (context.config.source === "tarim_poplar_mock")
    return createMockMonitorSource({ locale: context.locale });
  return undefined;
}
