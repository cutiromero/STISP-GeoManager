import "./monitor-product-selector.css";
import { Empty, Segmented, Select, Tag } from "antd";
import type {
  ProductView,
  MonitorProductSelection,
} from "./useMonitorProductSelection";
import type { MonitoringProduct } from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";

export function productVersionLabel(item: MonitoringProduct) {
  const origin = item.provenance;
  const date = new Date(
    origin?.createdAt ?? item.registeredAt,
  ).toLocaleString();
  return [
    date,
    origin?.batchId ? `批次 ${origin.batchId.slice(0, 8)}` : item.name,
    origin?.creator,
    item.model?.variant,
  ]
    .filter(Boolean)
    .join(" · ");
}
export default function MonitorProductSelector({
  selection,
  presentation = "select",
}: {
  selection: MonitorProductSelection;
  presentation?: "select" | "list";
}) {
  const ui = useComputeText();
  const names = {
    current: selection.hasCurrentTask
      ? ui("本次解译", "Current run")
      : ui("最近一次解译", "Latest run"),
    history: ui("历史解译", "Previous runs"),
    standard: ui("标准成果", "Reference"),
    uploaded: ui("上传成果", "Uploaded"),
  };
  const options = selection.choices.map((item) => ({
    value: `product:${item.id}`,
    label: productVersionLabel(item),
  }));
  if (selection.view === "standard")
    for (const resource of selection.references) {
      if (!selection.choices.some((item) => item.resourceId === resource.id))
        options.push({
          value: `resource:${resource.id}`,
          label: `${resource.name} · #${resource.id}`,
        });
    }
  const selected = selection.selected;
  return (
    <div className="monitor-product-selector">
      <Segmented
        block
        size="small"
        aria-label={ui("成果来源", "Product origin")}
        value={selection.view}
        onChange={(value) => selection.selectView(value as ProductView)}
        options={Object.entries(names)
          .filter(
            ([key]) =>
              key !== "uploaded" ||
              selection.view === "uploaded" ||
              selection.hasUploaded,
          )
          .map(([value, label]) => ({ value, label }))}
      />
      {options.length && presentation === "list" ? (
        <div>
          {options.map((option) => {
            const product = selection.choices.find(
              (item) => `product:${item.id}` === option.value,
            );
            const reference = selection.references.find(
              (item) => `resource:${item.id}` === option.value,
            );
            return (
              <button
                type="button"
                key={option.value}
                className={`monitor-product-choice${option.value === selection.key ? " selected" : ""}`}
                aria-pressed={option.value === selection.key}
                onClick={() => selection.selectKey(option.value)}
              >
                <strong>{product?.name ?? reference?.name}</strong>
                <time>{option.label}</time>
              </button>
            );
          })}
        </div>
      ) : options.length > 1 ||
        (selection.view === "standard" && selection.references.length > 0) ? (
        <Select
          aria-label={ui("选择成果版本", "Select product version")}
          value={selection.key}
          placeholder={
            selection.view === "standard"
              ? ui("选择上传的标准成果", "Choose an uploaded reference")
              : ui("选择处理批次", "Choose a processing batch")
          }
          onChange={selection.selectKey}
          options={options}
          popupMatchSelectWidth={false}
          optionRender={(option) => (
            <span title={String(option.label)}>{option.label}</span>
          )}
        />
      ) : !options.length ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            selection.view === "current"
              ? ui(
                  "该批次没有该样区成果",
                  "No result for this region in the selected batch",
                )
              : selection.view === "standard"
                ? ui(
                    "可选择已上传的分类栅格或矢量成果",
                    "Choose an uploaded classification or vector result",
                  )
                : ui("暂无此类成果", "No products in this group")
          }
        />
      ) : null}
      {(selected || selection.reference) && (
        <div className="monitor-product-identity">
          <Tag color={selection.view === "standard" ? "gold" : "cyan"}>
            {names[selection.view]}
          </Tag>
          {selected?.provenance?.batchId && (
            <span title={selected.provenance.batchId}>
              批次 {selected.provenance.batchId.slice(0, 8)}
            </span>
          )}
          {selected && (
            <time>
              {new Date(
                selected.provenance?.createdAt ?? selected.registeredAt,
              ).toLocaleString()}
            </time>
          )}
          {selected?.provenance?.creator && (
            <span>处理人 {selected.provenance.creator}</span>
          )}
          {presentation !== "list" && (
            <strong title={selected?.name ?? selection.reference?.name}>
              {selected?.name ?? selection.reference?.name}
            </strong>
          )}
          {selection.reference?.updatedAt && (
            <time>
              {ui("资料更新", "Data updated")}{" "}
              {new Date(selection.reference.updatedAt).toLocaleString()}
            </time>
          )}
          {selection.reference && (
            <span>
              数据资源 #{selection.reference.id} ·{" "}
              {ui("上传资料", "Uploaded data")}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
