import { Button, Popover, Radio, Select } from "antd";
import {
  DatabaseOutlined,
  ExperimentOutlined,
  ReadOutlined,
} from "@ant-design/icons";
import { useState } from "react";
import type {
  AgentBootstrap,
  AgentResource,
  AgentRun,
  AgentRunInput,
} from "../api/generated/types.gen";

export type ToolPreferences = Required<
  Pick<
    AgentRunInput,
    | "knowledgeSelection"
    | "algorithmSelectionMode"
    | "algorithmVersionIds"
    | "dataSelectionMode"
  >
>;
export const defaultToolPreferences: ToolPreferences = {
  knowledgeSelection: { mode: "auto", domains: [] },
  algorithmSelectionMode: "auto",
  algorithmVersionIds: [],
  dataSelectionMode: "auto",
};
export function preferencesFromRun(run?: AgentRun): ToolPreferences {
  return {
    knowledgeSelection: run?.knowledgeSelection ?? {
      mode: "auto",
      domains: [],
    },
    algorithmSelectionMode: run?.algorithmSelectionMode ?? "auto",
    algorithmVersionIds: run?.algorithmVersionIds ?? [],
    dataSelectionMode: run?.dataSelectionMode ?? "auto",
  };
}
export function selectionError(value: ToolPreferences, resources: number[]) {
  if (
    value.algorithmSelectionMode === "manual" &&
    !value.algorithmVersionIds.length
  )
    return "请选择至少一个算法，或切换为自动筛选。";
  if (value.dataSelectionMode === "manual" && !resources.length)
    return "请选择至少一项数据，或切换为自动筛选。";
  if (
    value.knowledgeSelection.mode === "manual" &&
    !value.knowledgeSelection.domains.length
  )
    return "请选择至少一个知识分区，或切换知识库模式。";
  return "";
}

export default function AgentToolSelection({
  bootstrap,
  resources,
  selected,
  value,
  disabled,
  onChange,
  onResources,
}: {
  bootstrap: AgentBootstrap;
  resources: AgentResource[];
  selected: number[];
  value: ToolPreferences;
  disabled: boolean;
  onChange: (value: ToolPreferences) => void;
  onResources: (ids: number[]) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const algorithms = bootstrap.algorithmOptions ?? [];
  const domains = bootstrap.knowledgeDomains ?? [];
  const knowledgeSummary = {
    auto: "自动",
    all: "全部",
    none: "不参考",
    manual: `${value.knowledgeSelection.domains.length} 个分区`,
  }[value.knowledgeSelection.mode];
  const controls = [
    {
      key: "algorithm",
      label: "调用算法",
      icon: <ExperimentOutlined />,
      summary:
        value.algorithmSelectionMode === "auto"
          ? "自动"
          : `${value.algorithmVersionIds.length} 项`,
      content: (
        <>
          <Radio.Group
            role="radiogroup"
            name="agent-algorithm-selection"
            aria-label="算法选择方式"
            value={value.algorithmSelectionMode}
            disabled={disabled}
            onChange={(event) =>
              onChange({
                ...value,
                algorithmSelectionMode: event.target.value,
                algorithmVersionIds:
                  event.target.value === "manual"
                    ? value.algorithmVersionIds
                    : [],
              })
            }
            options={[
              { value: "auto", label: "自动筛选" },
              { value: "manual", label: "手动选择" },
            ]}
          />
          <p>根据问题匹配平台已发布算法；手选后仅使用所选算法。</p>
          {value.algorithmSelectionMode === "manual" && (
            <Select
              aria-label="选择调用算法"
              mode="multiple"
              value={value.algorithmVersionIds}
              allowClear
              showSearch
              optionFilterProp="label"
              disabled={disabled}
              placeholder="选择需要调用的算法"
              notFoundContent="当前暂无可用的已发布算法"
              options={algorithms.map((item) => ({
                value: item.versionId,
                label: `${item.name} · ${item.version}`,
              }))}
              labelRender={({ value: id }) => {
                const item = algorithms.find(
                  (option) => option.versionId === id,
                );
                return item ? `${item.name} · ${item.version}` : "算法已不可用";
              }}
              onChange={(ids) =>
                onChange({ ...value, algorithmVersionIds: ids })
              }
            />
          )}
        </>
      ),
    },
    {
      key: "data",
      label: "选择数据",
      icon: <DatabaseOutlined />,
      summary:
        value.dataSelectionMode === "auto" ? "自动" : `${selected.length} 项`,
      content: (
        <>
          <Radio.Group
            role="radiogroup"
            name="agent-data-selection"
            aria-label="数据选择方式"
            value={value.dataSelectionMode}
            disabled={disabled}
            onChange={(event) =>
              onChange({ ...value, dataSelectionMode: event.target.value })
            }
            options={[
              { value: "auto", label: "自动筛选" },
              { value: "manual", label: "手动选择" },
            ]}
          />
          <p>从当前项目的授权数据中筛选；手选后仅使用所选数据。</p>
          {value.dataSelectionMode === "manual" && (
            <Select
              aria-label="限定数据资源"
              mode="multiple"
              allowClear
              showSearch
              optionFilterProp="label"
              value={selected}
              disabled={disabled}
              placeholder="选择需要分析的数据"
              notFoundContent="当前项目没有可访问的数据"
              options={resources.map((item) => ({
                value: item.id,
                label: item.name,
              }))}
              labelRender={({ value: id }) =>
                resources.find((item) => item.id === id)?.name ?? "数据已不可用"
              }
              onChange={onResources}
            />
          )}
        </>
      ),
    },
    {
      key: "knowledge",
      label: "知识库",
      icon: <ReadOutlined />,
      summary: knowledgeSummary,
      content: (
        <>
          <Radio.Group
            role="radiogroup"
            name="agent-knowledge-selection"
            aria-label="知识库参考方式"
            className="agent-knowledge-modes"
            value={value.knowledgeSelection.mode}
            disabled={disabled}
            onChange={(event) =>
              onChange({
                ...value,
                knowledgeSelection: {
                  ...value.knowledgeSelection,
                  mode: event.target.value,
                  domains:
                    event.target.value === "manual"
                      ? value.knowledgeSelection.domains
                      : [],
                },
              })
            }
            options={[
              { value: "auto", label: "自动筛选" },
              { value: "manual", label: "手选分区" },
              { value: "all", label: "全部知识库" },
              { value: "none", label: "不参考知识库" },
            ]}
          />
          <p>
            {value.knowledgeSelection.mode === "none"
              ? "本轮处理使用平台数据与算法，不检索知识库。"
              : "自动匹配问题所属领域，也可指定一个或多个知识分区。"}
          </p>
          {value.knowledgeSelection.mode === "manual" && (
            <Select
              aria-label="选择知识分区"
              mode="multiple"
              maxCount={4}
              value={value.knowledgeSelection.domains}
              disabled={disabled}
              allowClear
              placeholder="选择一个或多个分区"
              options={domains.map((item) => ({
                value: item.id,
                label: item.label,
                title: item.description,
              }))}
              labelRender={({ value: id }) =>
                domains.find((item) => item.id === id)?.label ?? "分区已不可用"
              }
              onChange={(ids) =>
                onChange({
                  ...value,
                  knowledgeSelection: { mode: "manual", domains: ids },
                })
              }
            />
          )}
        </>
      ),
    },
  ];
  return (
    <>
      {controls.map((control) => (
        <Popover
          key={control.key}
          trigger="click"
          destroyOnHidden
          placement="top"
          title={control.label}
          open={open === control.key}
          onOpenChange={(next) => setOpen(next ? control.key : null)}
          content={
            <div
              className="agent-selection-panel"
              onKeyDown={(event) => {
                if (event.key === "Escape") setOpen(null);
              }}
            >
              {control.content}
            </div>
          }
        >
          <Button
            type="text"
            icon={control.icon}
            className="agent-selection-trigger"
            aria-label={control.label}
            aria-expanded={open === control.key}
          >
            <span>{control.label}</span>
            <span className="agent-selection-summary">{control.summary}</span>
          </Button>
        </Popover>
      ))}
    </>
  );
}
