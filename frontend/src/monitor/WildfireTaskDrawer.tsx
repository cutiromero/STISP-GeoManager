import { InputNumber, Select } from "antd";
import { useMemo, useState, type ComponentProps } from "react";
import type { WildfireObservationCatalog } from "../api/generated/types.gen";
import MonitorTaskDrawer from "./MonitorTaskDrawer";

type Props = Omit<
  ComponentProps<typeof MonitorTaskDrawer>,
  | "title"
  | "initialInputs"
  | "inputLabels"
  | "parameters"
  | "launchOptions"
  | "launchKey"
> & { catalog?: WildfireObservationCatalog };
const defaults = {
  west: 112,
  south: -44,
  east: 154,
  north: -10,
  product: "gwis_ba",
  time_index: 873,
  history: 12,
};

export default function WildfireTaskDrawer({ catalog, ...props }: Props) {
  const [options, setOptions] = useState(defaults);
  const cube = catalog?.cube;
  const inputs = useMemo<Record<string, number>>(() => {
    const value: Record<string, number> = {};
    if (cube) value.cube = cube.id;
    return value;
  }, [cube?.id]);
  const times =
    catalog?.times.filter((row) =>
      row.validProducts.includes(options.product),
    ) ?? [];
  const product = catalog?.products.find((row) => row.key === options.product);
  const selectedTime = times.find((row) => row.index === options.time_index);
  const monthTime =
    product?.periodMode === "monthly" && selectedTime
      ? times.find(
          (row) => row.date.slice(0, 7) === selectedTime.date.slice(0, 7),
        )?.index
      : options.time_index;
  const ready = Boolean(
    cube &&
    selectedTime &&
    options.west < options.east &&
    options.south < options.north,
  );

  return (
    <MonitorTaskDrawer
      {...props}
      title="野火观测制图任务"
      initialInputs={inputs}
      inputLabels={cube ? { [cube.id]: cube.name } : {}}
      parameters={{ nodeParameters: { interpret: options } }}
      launchKey={JSON.stringify(options)}
      launchReady={ready}
      launchOptions={
        <div className="wildfire-task-options">
          <label>
            <span>观测源</span>
            <Select
              aria-label="观测源"
              value={options.product}
              onChange={(value) =>
                setOptions((old) => ({
                  ...old,
                  product: value,
                  time_index:
                    catalog?.times.find(
                      (row) =>
                        row.index === old.time_index &&
                        row.validProducts.includes(value),
                    )?.index ??
                    catalog?.times
                      .filter((row) => row.validProducts.includes(value))
                      .slice(-1)[0]?.index ??
                    0,
                }))
              }
              options={catalog?.products.map((row) => ({
                value: row.key,
                label: row.label,
              }))}
            />
          </label>
          <label>
            <span>
              {product?.periodMode === "monthly" ? "观测月份" : "观测周期"}
            </span>
            <Select
              aria-label="观测周期"
              showSearch
              optionFilterProp="label"
              value={monthTime}
              onChange={(value) =>
                setOptions((old) => ({ ...old, time_index: value }))
              }
              options={times
                .filter(
                  (row, index, array) =>
                    product?.periodMode !== "monthly" ||
                    index === 0 ||
                    row.date.slice(0, 7) !== array[index - 1]!.date.slice(0, 7),
                )
                .map((row) => ({
                  value: row.index,
                  label:
                    product?.periodMode === "monthly"
                      ? row.date.slice(0, 7)
                      : `${row.date} — ${row.endDate}`,
                }))}
            />
          </label>
          <label>
            <span>序列长度</span>
            <InputNumber
              aria-label="序列长度"
              min={1}
              max={12}
              value={options.history}
              onChange={(value) =>
                value !== null &&
                setOptions((old) => ({ ...old, history: value }))
              }
            />
          </label>
          <p>研究区 · WGS84</p>
          <div className="wildfire-region-grid">
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
                  value={options[key]}
                  min={key === "west" || key === "east" ? -180 : -90}
                  max={key === "west" || key === "east" ? 180 : 90}
                  onChange={(value) =>
                    value !== null &&
                    setOptions((old) => ({ ...old, [key]: value }))
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
