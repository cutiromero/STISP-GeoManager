import { Empty, Select } from "antd";
import { useState } from "react";
import type { NonGeoFieldProfile, NonGeoTableQueryResult } from "../types";
import { useComputeText } from "../compute/ui";

export function isMeasurement(field: NonGeoFieldProfile) {
  return (
    field.role === "measure" &&
    !/(^id$|_id$|^fid$|^oid$|^plot_number$|地点号|样地号|编号|序号)/i.test(
      field.name,
    )
  );
}

export function finiteValue(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && !value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export default function NonGeoScatter({
  tableData,
  fields,
}: {
  tableData: NonGeoTableQueryResult | null;
  fields: NonGeoFieldProfile[];
}) {
  const ui = useComputeText();
  const [x, setX] = useState("");
  const [y, setY] = useState("");
  const candidates = fields.filter(
    (field) =>
      isMeasurement(field) &&
      tableData?.fields.some((column) => column.name === field.name),
  );
  const xField = candidates.find((field) => field.name === x) ?? candidates[0];
  const yField =
    candidates.find(
      (field) => field.name === y && field.name !== xField?.name,
    ) ?? candidates.find((field) => field.name !== xField?.name);
  if (!tableData || !xField || !yField)
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={ui(
          "需要至少两个数值指标才能绘图",
          "Two numeric measures are needed for this chart",
        )}
      />
    );
  const fieldLabel = (field: NonGeoFieldProfile) =>
    `${field.label || field.name}${field.unit ? ` (${field.unit})` : ""}`;
  const options = candidates.map((field) => ({
    value: field.name,
    label: fieldLabel(field),
  }));
  const points = tableData.rows.flatMap((row) => {
    const px = finiteValue(row[xField.name]),
      py = finiteValue(row[yField.name]);
    return px === null || py === null ? [] : [{ x: px, y: py }];
  });
  // Coincident observations share a mark; its tooltip preserves their count.
  const grouped = new Map<string, { x: number; y: number; count: number }>();
  for (const point of points) {
    const key = `${point.x}:${point.y}`;
    const saved = grouped.get(key);
    if (saved) saved.count += 1;
    else grouped.set(key, { ...point, count: 1 });
  }
  const extent = (values: number[]): [number, number] => {
    if (!values.length) return [0, 1];
    const min = Math.min(...values),
      max = Math.max(...values);
    const padding = (max - min || Math.abs(min) || 1) * 0.06;
    return [min - padding, max + padding];
  };
  const [minX, maxX] = extent(points.map((point) => point.x));
  const [minY, maxY] = extent(points.map((point) => point.y));
  const format = (value: number) => Number(value.toPrecision(3)).toString();
  return (
    <div className="analysis-scatter">
      <div className="analysis-axis-controls">
        <label>
          {ui("横轴", "X axis")}
          <Select
            aria-label={ui("横轴指标", "X-axis measure")}
            value={xField.name}
            options={options}
            onChange={(value) => {
              setX(value);
              setY(
                value === yField.name
                  ? (candidates.find((field) => field.name !== value)?.name ??
                      "")
                  : yField.name,
              );
            }}
          />
        </label>
        <label>
          {ui("纵轴", "Y axis")}
          <Select
            aria-label={ui("纵轴指标", "Y-axis measure")}
            value={yField.name}
            options={options.filter((option) => option.value !== xField.name)}
            onChange={setY}
          />
        </label>
      </div>
      {points.length ? (
        <svg
          viewBox="0 0 480 285"
          role="img"
          aria-label={`${fieldLabel(xField)} × ${fieldLabel(yField)}`}
        >
          {[0, 0.25, 0.5, 0.75, 1].map((fraction) => (
            <g key={fraction}>
              <line
                x1={60}
                x2={450}
                y1={230 - fraction * 200}
                y2={230 - fraction * 200}
                className="analysis-grid-line"
              />
              <text x={50} y={234 - fraction * 200} textAnchor="end">
                {format(minY + fraction * (maxY - minY))}
              </text>
              <text x={60 + fraction * 390} y={250} textAnchor="middle">
                {format(minX + fraction * (maxX - minX))}
              </text>
            </g>
          ))}
          <path d="M60 30 V230 H450" className="analysis-axis-line" />
          <text x={60} y={16}>
            {fieldLabel(yField)}
          </text>
          <text x={255} y={278} textAnchor="middle">
            {fieldLabel(xField)}
          </text>
          {[...grouped].map(([key, point]) => (
            <circle
              key={key}
              cx={60 + ((point.x - minX) / (maxX - minX)) * 390}
              cy={230 - ((point.y - minY) / (maxY - minY)) * 200}
              r={3}
              className="analysis-point"
            >
              <title>{`${fieldLabel(xField)}: ${point.x}; ${fieldLabel(yField)}: ${point.y}${point.count > 1 ? ` · ${point.count} ${ui("条记录", "records")}` : ""}`}</title>
            </circle>
          ))}
        </svg>
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={ui(
            "所选指标暂无成对有效值",
            "No valid pairs for these measures",
          )}
        />
      )}
      <p className="analysis-chart-note">
        {ui(
          `当前明细中 ${points.length} 条有效记录；点的位置表示两项指标，同值记录重叠显示。`,
          `${points.length} valid records from the current table preview. Position encodes the two measures; identical pairs overlap.`,
        )}
      </p>
    </div>
  );
}
