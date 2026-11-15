import type { ComponentProps } from "react";
import { Alert } from "antd";
import MonitorTaskDrawer from "./MonitorTaskDrawer";
import type { MonitoringWorkspace } from "./useMonitoringWorkspace";
type Props = Omit<
  ComponentProps<typeof MonitorTaskDrawer>,
  | "title"
  | "initialInputs"
  | "inputLabels"
  | "parameters"
  | "launchOptions"
  | "launchKey"
> & { workspace: MonitoringWorkspace };
export default function SpartinaTaskDrawer({ workspace: w, ...props }: Props) {
  const set = w.inputSet;
  const page = props.page && {
    ...props.page,
    businessFlow: w.catalog?.method
      ? {
          ...w.catalog.method,
          goal: `对所选${set?.label ?? ""}时相组合进行互花米草RF解译。研究区WGS84：${JSON.stringify(w.region)}。输出分类、概率、分布统计并登记到监测大屏。`,
        }
      : props.page.businessFlow,
  };
  return (
    <MonitorTaskDrawer
      {...props}
      page={page}
      title="互花米草解译任务"
      initialInputs={w.inputs}
      inputLabels={Object.fromEntries(
        (set?.resources ?? []).map((row) => [row.id, row.name]),
      )}
      parameters={{ nodeParameters: { interpret: w.region ?? {} } }}
      launchKey={JSON.stringify([
        w.inputs,
        w.region,
        w.catalog?.method?.versionId,
      ])}
      launchReady={w.ready}
      launchOptions={
        <div>
          <p>输入时相：{set?.label ?? "请先选择时相组合"}</p>
          <p>
            研究区：
            {w.region
              ? Object.values(w.region)
                  .map((value) => value.toFixed(4))
                  .join(" / ")
              : "请在地图绘制研究区"}
          </p>
          {!w.ready && (
            <Alert
              type="info"
              title="在大屏选择原始资料并绘制研究区后开始任务"
            />
          )}
        </div>
      }
    />
  );
}
