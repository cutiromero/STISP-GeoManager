import { InputNumber } from "antd";
import { useState, type ComponentProps } from "react";
import MonitorTaskDrawer from "./MonitorTaskDrawer";
import {
  observationProducts,
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
  const [history, setHistory] = useState(12);
  const options = {
    ...w.region,
    product: w.product,
    time_index: w.time?.ordinal ?? 0,
    history,
  };
  const page = props.page && {
    ...props.page,
    businessFlow: w.catalog?.method
      ? {
          ...w.catalog.method,
          goal: `生成${observationProducts.find((row) => row.value === w.product)?.label}观测图。所选时期：${w.time?.date} — ${w.time?.endDate}；研究区WGS84：${JSON.stringify(w.region)}；包含所选时期向前${history}${w.product === "fcci_ba" ? "个月" : "期"}。交付观测原值、分级图、区域统计与序列。`,
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
            · {w.time?.date} — {w.time?.endDate}
          </p>
          <p>
            研究区：
            {w.region
              ? Object.values(w.region)
                  .map((value) => value.toFixed(3))
                  .join(" / ")
              : "请在地图绘制研究区"}
          </p>
          <details>
            <summary>序列设置</summary>
            <label>
              回看{w.product === "fcci_ba" ? "月数" : "期数"}
              <InputNumber
                aria-label="回看期数"
                min={1}
                max={12}
                value={history}
                onChange={(value) => value != null && setHistory(value)}
              />
            </label>
          </details>
        </div>
      }
    />
  );
}
