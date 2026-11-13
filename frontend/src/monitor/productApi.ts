import { requestJson } from "../api/client";
import type { MonitoringProductList } from "../api/generated/types.gen";

export function getMonitoringProducts(
  scene: MonitoringProductList["scene"],
  signal: AbortSignal,
  beforeId?: number,
) {
  const query = new URLSearchParams({ scene });
  if (beforeId !== undefined) query.set("beforeId", String(beforeId));
  return requestJson<MonitoringProductList>(
    `/api/ecology/monitoring/?${query}`,
    {
      signal,
    },
  );
}
