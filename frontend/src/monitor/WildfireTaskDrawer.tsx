import { monitorTaskWritingGuidance } from "./productNarrative";
import MonitorFlowGuide from "./MonitorFlowGuide";
import { trendRange, trendOptions, type TrendSpan } from "./trendRange";
import { Select } from "antd";
import { useState, type ComponentProps } from "react";
import MonitorTaskDrawer from "./MonitorTaskDrawer";
import {
  observationProducts,
  monitoringPeriodLabel,
  type MonitoringWorkspace,
} from "./useMonitoringWorkspace";
type Props = Omit<
  ComponentProps<typeof MonitorTaskDrawer>,
  | "title"
  | "initialInputs"
  | "inputLabels"
  | "parameters"
  | "launchOptions"
  | "launchKey"
> & { workspace: MonitoringWorkspace };
export default function WildfireTaskDrawer({ workspace: w, ...props }: Props) {
  const [span, setSpan] = useState<TrendSpan>("current");
  const range = trendRange(w, span);
  const history = range.history;
  const options = {
    ...w.effectiveRegion,
    product: w.product,
    time_index: w.time?.ordinal ?? 0,
    history,
  };
  const period = monitoringPeriodLabel(w.product, w.time);
  const page = props.page && {
    ...props.page,
    businessFlow: w.catalog?.method
      ? {
          ...w.catalog.method,
          goal: `生成${observationProducts.find((row) => row.value === w.product)?.label}观测图。所选时期：${period}；研究区WGS84：${JSON.stringify(w.effectiveRegion)}；趋势统计时段${range.start}至${range.end}（按真实坐标计算${history}${w.product === "fcci_ba" ? "个月" : "个观测期"}）。交付观测原值、分级图、区域统计与序列。 ${monitorTaskWritingGuidance}`,
        }
      : props.page.businessFlow,
  };
  return (
    <MonitorTaskDrawer
      {...props}
      fixedInputs
      page={page}
      title="野火观测制图任务"
      initialInputs={w.inputs}
      inputLabels={
        w.source ? { [w.source.resource.id]: w.source.resource.name } : {}
      }
      parameters={{ nodeParameters: { interpret: options } }}
      launchKey={JSON.stringify([
        w.inputs,
        options,
        w.catalog?.method?.versionId,
      ])}
      launchReady={w.ready}
      launchOptions={
        <div>
          <p>{w.source?.resource.name}</p>
          <p>
            {observationProducts.find((row) => row.value === w.product)?.label}{" "}
            · {period}
          </p>
          <p>
            研究区：
            {w.region
              ? Object.values(w.region)
                  .map((value) => value.toFixed(3))
                  .join(" / ")
              : "全域（所选数据的共同覆盖范围）"}
          </p>
          <label className="monitor-trend-range">
            趋势统计
            <Select
              aria-label="趋势统计范围"
              value={span}
              options={trendOptions}
              onChange={setSpan}
            />
          </label>
          <p className="monitor-task-note">
            统计时段：{range.start} — {range.end}
          </p>
          <MonitorFlowGuide scene="wildfire" />
        </div>
      }
    />
  );
}
