import { Alert, Select, Spin } from "antd";
import { useEffect, useState } from "react";
import { getActiveProject } from "../projects/session";
import {
  observationProducts,
  useMonitoringWorkspace,
} from "../monitor/useMonitoringWorkspace";
import {
  trendOptions,
  trendRange,
  type TrendSpan,
} from "../monitor/trendRange";

export type WildfireLaunchSelection = {
  resourceId: number;
  parameters: Record<string, number | string>;
  summary: string;
};

export default function WildfireLaunchOptions({
  resourceId,
  onChange,
}: {
  resourceId?: number;
  onChange: (value: WildfireLaunchSelection | undefined) => void;
}) {
  const w = useMonitoringWorkspace("wildfire", Number(getActiveProject()));
  const [span, setSpan] = useState<TrendSpan>("current");
  const range = trendRange(w, span);
  useEffect(() => {
    w.setSourceId(resourceId);
  }, [resourceId, w.setSourceId]);
  const ready = Boolean(
    resourceId &&
    resourceId === w.source?.resource.id &&
    !w.error &&
    w.ready &&
    w.time,
  );
  const productLabel = observationProducts.find(
    (row) => row.value === w.product,
  )?.label;
  useEffect(() => {
    onChange(
      ready && w.time
        ? {
            resourceId: resourceId!,
            parameters: {
              product: w.product,
              time_index: w.time.ordinal,
              history: range.history,
            },
            summary: `${productLabel}；观测期${w.time.date}至${w.time.endDate}；趋势统计${range.start}至${range.end}；未指定范围时使用所选资料全域。`,
          }
        : undefined,
    );
  }, [
    ready,
    resourceId,
    w.product,
    w.time?.ordinal,
    w.time?.date,
    w.time?.endDate,
    range.history,
    range.start,
    range.end,
    productLabel,
    onChange,
  ]);
  return (
    <section
      className="business-flow-wildfire-options"
      aria-label="野火观测选择"
    >
      <strong>观测产品与日期</strong>
      <p>
        选择实际观测期。GWIS、GFED、FCCI 输出火烧面积（ha）；CAMS
        输出有效格网火辐射功率密度（W/m²）。FCCI
        按月汇总。结果为观测，不是火灾预测。
      </p>
      {!resourceId && <p>请先绑定原始立方体资料。</p>}
      {w.loading && <Spin size="small" />}
      {w.error && <Alert type="error" title={w.error} />}
      {resourceId && !w.loading && resourceId !== w.source?.resource.id && (
        <Alert
          type="warning"
          title="所选资料尚未登记可用野火时相，请核对原始资料与监测用途。"
        />
      )}
      <label>
        监测内容
        <Select
          aria-label="任务监测内容"
          value={w.product}
          options={observationProducts}
          onChange={w.setProduct}
        />
      </label>
      <label>
        年份
        <Select
          aria-label="任务观测年份"
          value={w.selectedYear}
          options={w.years.map((row) => ({
            value: row.year,
            label: `${row.year}年`,
          }))}
          onChange={w.setYear}
        />
      </label>
      <label>
        观测时期
        <Select
          aria-label="任务观测时期"
          showSearch
          optionFilterProp="label"
          value={w.time?.ordinal}
          options={w.times.map((row) => ({
            value: row.ordinal,
            label:
              w.product === "fcci_ba"
                ? row.date.slice(0, 7)
                : `${row.date} — ${row.endDate}`,
          }))}
          onChange={w.setOrdinal}
        />
      </label>
      <label>
        趋势统计
        <Select
          aria-label="任务趋势统计范围"
          value={span}
          options={trendOptions}
          onChange={setSpan}
        />
      </label>
      {ready && (
        <p>
          统计时段：{range.start} — {range.end}；共{range.history}个观测期。
        </p>
      )}
    </section>
  );
}
