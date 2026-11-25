import { Select } from "antd";
import { useEffect, useState } from "react";
import { scheduleResourceSearch } from "../agent/resourceSearch";
import { agentApi } from "../api/agent";
import { requestScope } from "../projects/session";

export default function BusinessFlowImageReplacement({
  disabled,
  value,
  onChange,
}: {
  disabled: boolean;
  value?: number;
  onChange: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [options, setOptions] = useState<{ label: string; value: number }[]>([]);
  const [selected, setSelected] = useState<{ label: string; value: number }>();
  useEffect(() => {
    if (!open || disabled) return;
    const current = requestScope();
    setLoading(true);
    setFailed(false);
    setOptions([]);
    return scheduleResourceSearch(
      async (signal) => {
        const result = await agentApi.resources(query.trim().slice(0, 200), {
          signal,
          source: "registered",
        });
        current();
        return result.items;
      },
      {
        success: (items) =>
          setOptions(items.filter((item) => item.dataType === "raster")
            .map((item) => ({ label: item.name, value: item.id }))),
        error: () => setFailed(true),
        settled: () => setLoading(false),
      },
    );
  }, [open, query, disabled]);
  return (
    <label>
      换一幅原始影像
      <Select
        aria-label="换一幅原始影像"
        placeholder="按影像名称查找"
        style={{ minWidth: 260 }}
        disabled={disabled}
        loading={loading}
        onOpenChange={setOpen}
        showSearch={{ filterOption: false, onSearch: setQuery }}
        labelInValue
        value={selected?.value === value ? selected : undefined}
        options={options}
        notFoundContent={failed ? "影像列表没有加载成功，关闭后重试。" : "没有找到影像"}
        onChange={(option) => {
          setSelected({ value: option.value, label: String(option.label) });
          onChange(option.value);
        }}
      />
    </label>
  );
}
