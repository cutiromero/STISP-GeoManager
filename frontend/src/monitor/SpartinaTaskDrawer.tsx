import { InputNumber } from "antd";
import { useMemo, useState, type ComponentProps } from "react";
import MonitorTaskDrawer from "./MonitorTaskDrawer";

const initialRegion = { west: 121.9, south: 31.2, east: 121.99, north: 31.29 };
type Props = Omit<
  ComponentProps<typeof MonitorTaskDrawer>,
  | "title"
  | "initialInputs"
  | "inputLabels"
  | "parameters"
  | "launchOptions"
  | "launchKey"
>;

export default function SpartinaTaskDrawer(props: Props) {
  const [region, setRegion] = useState(initialRegion);
  const resources = props.page?.inputResources ?? [];
  const inputs = useMemo(
    () =>
      Object.fromEntries(
        (
          [
            ["march", "202503"],
            ["august", "202508"],
            ["december", "202512"],
          ] as const
        ).flatMap(([role, period]) => {
          const resource = resources.find((row) => row.name.includes(period));
          return resource ? [[role, resource.id]] : [];
        }),
      ),
    [resources],
  );
  return (
    <MonitorTaskDrawer
      {...props}
      title="互花米草解译任务"
      initialInputs={inputs}
      inputLabels={Object.fromEntries(
        resources.map((row) => [row.id, row.name]),
      )}
      parameters={{ nodeParameters: { interpret: region } }}
      launchKey={JSON.stringify(region)}
      launchOptions={
        <div className="spartina-task-region">
          <strong>研究区 · WGS84</strong>
          <p>默认长江口，可调整经纬度边界</p>
          <div>
            {(
              [
                ["west", "西界"],
                ["south", "南界"],
                ["east", "东界"],
                ["north", "北界"],
              ] as const
            ).map(([key, label]) => (
              <label key={key}>
                <span>{label}</span>
                <InputNumber
                  aria-label={label}
                  value={region[key]}
                  min={key === "west" || key === "east" ? -180 : -90}
                  max={key === "west" || key === "east" ? 180 : 90}
                  step={0.01}
                  onChange={(value) =>
                    value !== null &&
                    setRegion((old) => ({ ...old, [key]: value }))
                  }
                />
              </label>
            ))}
          </div>
        </div>
      }
    />
  );
}
