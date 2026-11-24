import {
  Alert,
  Checkbox,
  Input,
  Modal,
  Pagination,
  Segmented,
  Select,
} from "antd";
import { useEffect, useRef, useState } from "react";
import { agentApi } from "../api/agent";
import type {
  AgentResourceSource,
  AgentWorkflowCatalogItem,
} from "../api/generated/types.gen";
import { ResourceSearchLabel } from "./ResourceSearchLabel";
import {
  RESOURCE_SEARCH_DELAY_MS,
  scheduleResourceSearch,
} from "./resourceSearch";

const kindLabels: Record<string, string> = {
  vector: "矢量",
  raster: "栅格",
  table: "表格",
};

export type WorkflowDataSelection = { id: number; name: string };

export default function WorkflowDataPicker({
  open: catalogOpen,
  polished = false,
  disabled = false,
  usage,
  excludedIds,
  selection,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  polished?: boolean;
  disabled?: boolean;
  usage?: "research";
  excludedIds?: number[];
  selection?: WorkflowDataSelection[];
  onCancel: () => void;
  onConfirm: (items: WorkflowDataSelection[]) => void | Promise<void>;
}) {
  const [catalogSource, setCatalogSource] =
    useState<AgentResourceSource>("registered");
  const [catalogQuery, setCatalogQuery] = useState("");
  const [catalogSearchDelay, setCatalogSearchDelay] = useState(0);
  const [catalogComposing, setCatalogComposing] = useState(false);
  const [catalogResultQuery, setCatalogResultQuery] = useState("");
  const [catalogItems, setCatalogItems] = useState<AgentWorkflowCatalogItem[]>(
    [],
  );
  const catalogNames = useRef(new Map<number, string>());
  const [catalogPage, setCatalogPage] = useState(1);
  const [catalogTotal, setCatalogTotal] = useState(0);
  const [directoryId, setDirectoryId] = useState<number>();
  const [directories, setDirectories] = useState<
    { id: number; name: string }[]
  >([]);
  const [catalogSelected, setCatalogSelected] = useState<number[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  useEffect(() => {
    if (catalogOpen) return;
    setCatalogSource("registered");
    setCatalogQuery("");
    setCatalogPage(1);
    setCatalogTotal(0);
    setCatalogSearchDelay(0);
    setCatalogComposing(false);
    setDirectoryId(undefined);
    setDirectories([]);
    setCatalogSelected(selection?.map((item) => item.id) ?? []);
    catalogNames.current = new Map(
      selection?.map(({ id, name }) => [id, name]),
    );
    setSaveError("");
  }, [catalogOpen, selection]);

  useEffect(() => {
    if (!catalogOpen || catalogComposing) return;
    setCatalogLoading(true);
    setCatalogItems([]);
    setCatalogError("");
    return scheduleResourceSearch(
      (signal) =>
        agentApi.workflowCatalogResources(
          catalogQuery,
          { signal, source: catalogSource, usage },
          catalogPage,
          directoryId,
        ),
      {
        success: (result) => {
          setCatalogItems(result.items);
          setCatalogResultQuery(catalogQuery);
          for (const item of result.items)
            catalogNames.current.set(item.id, item.name);
          setCatalogTotal(result.total);
          setDirectories(result.directories);
        },
        error: (reason) => {
          setCatalogError(
            reason instanceof Error ? reason.message : "系统数据读取失败",
          );
        },
        settled: () => setCatalogLoading(false),
      },
      catalogSearchDelay,
    );
  }, [
    catalogOpen,
    catalogSource,
    catalogQuery,
    catalogSearchDelay,
    catalogPage,
    directoryId,
    catalogComposing,
    usage,
  ]);
  const changeCatalogQuery = (value: string) => {
    setCatalogQuery(value);
    setCatalogPage(1);
    setCatalogSearchDelay(RESOURCE_SEARCH_DELAY_MS);
  };
  const changeCatalogSource = (source: AgentResourceSource) => {
    setCatalogSource(source);
    setDirectoryId(undefined);
    setDirectories([]);
    setCatalogTotal(0);
    setCatalogPage(1);
    setCatalogSearchDelay(0);
  };
  const addCatalog = async () => {
    if (saving || !catalogSelected.length) return;
    setSaving(true);
    setSaveError("");
    try {
      await onConfirm(
        catalogSelected.map((id) => ({
          id,
          name: catalogNames.current.get(id) ?? `资料 ${id}`,
        })),
      );
    } catch (reason) {
      setSaveError(reason instanceof Error ? reason.message : "请重试添加资料");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="选择系统数据"
      open={catalogOpen}
      width={polished ? 720 : undefined}
      className={polished ? "flow-materials-picker" : undefined}
      onCancel={onCancel}
      onOk={() => void addCatalog()}
      okText="加入本次任务"
      confirmLoading={saving}
      okButtonProps={{
        disabled: disabled || !catalogSelected.length || saving,
      }}
    >
      <p>
        {polished
          ? `从当前项目选择资料，已选 ${catalogSelected.length} 份`
          : `名称命中优先，同级最近更新优先，共 ${catalogTotal} 份。可搜索资料名称或说明；多个关键词以空格分隔且都要包含，可跨页选择。`}
      </p>
      {(saveError || catalogError) && (
        <Alert type="error" title={saveError || catalogError} />
      )}
      <Segmented<AgentResourceSource>
        aria-label="资料来源"
        value={catalogSource}
        options={[
          { label: "登记数据", value: "registered" },
          { label: "计算成果", value: "computed" },
        ]}
        onChange={changeCatalogSource}
        style={{ marginBottom: 8 }}
      />
      <Select
        aria-label="按数据目录筛选"
        allowClear
        placeholder="全部数据目录"
        value={directoryId}
        style={{ width: "100%", marginBottom: 8 }}
        options={directories.map((item) => ({
          value: item.id,
          label: item.name,
        }))}
        onChange={(value) => {
          setDirectoryId(value);
          setCatalogPage(1);
          setCatalogSearchDelay(0);
        }}
      />
      {polished ? (
        <div
          onCompositionStartCapture={() => setCatalogComposing(true)}
          onCompositionEndCapture={() => setCatalogComposing(false)}
        >
          <Input.Search
            aria-label="搜索任务资料"
            placeholder="搜索资料名称或说明，空格分隔多个关键词"
            allowClear
            loading={catalogLoading}
            value={catalogQuery}
            onChange={(event) => changeCatalogQuery(event.target.value)}
          />
          <div className="flow-materials-candidates" aria-busy={catalogLoading}>
            {catalogItems.map((item) => (
              <Checkbox
                key={item.id}
                className="flow-materials-candidate"
                aria-label={`选择${item.name}`}
                checked={catalogSelected.includes(item.id)}
                disabled={disabled || saving || excludedIds?.includes(item.id)}
                onChange={(event) =>
                  setCatalogSelected((previous) =>
                    event.target.checked
                      ? [...new Set([...previous, item.id])]
                      : previous.filter((id) => id !== item.id),
                  )
                }
              >
                <span>
                  <ResourceSearchLabel
                    name={item.name}
                    description={item.description}
                    query={catalogResultQuery}
                  />
                  <small>
                    {kindLabels[item.dataType as keyof typeof kindLabels] ??
                      item.dataType}{" "}
                    · {item.directoryName || "未分组"}
                  </small>
                </span>
              </Checkbox>
            ))}
            {!catalogLoading && !catalogItems.length && (
              <p>没有匹配的资料，请调整关键词或数据目录</p>
            )}
          </div>
        </div>
      ) : (
        <div
          onCompositionStartCapture={() => setCatalogComposing(true)}
          onCompositionEndCapture={() => setCatalogComposing(false)}
        >
          <Select
            mode="multiple"
            style={{ width: "100%" }}
            aria-label="选择系统数据资源"
            placeholder="搜索资料名称或说明，空格分隔多个关键词"
            loading={catalogLoading}
            showSearch={{
              filterOption: false,
              onSearch: changeCatalogQuery,
            }}
            value={catalogSelected}
            labelRender={(option) =>
              catalogNames.current.get(Number(option.value)) ?? option.label
            }
            optionRender={(option) => (
              <ResourceSearchLabel
                name={option.data.name}
                description={option.data.description}
                query={catalogResultQuery}
                details={`（${option.data.details}）`}
              />
            )}
            notFoundContent={
              catalogLoading
                ? "正在搜索资料…"
                : "没有匹配的资料，请调整关键词或数据目录"
            }
            onSelect={(value) =>
              setCatalogSelected((current) =>
                current.includes(value) ? current : [...current, value],
              )
            }
            onDeselect={(value) =>
              setCatalogSelected((current) =>
                current.filter((item) => item !== value),
              )
            }
            onClear={() => setCatalogSelected([])}
            disabled={disabled || saving}
            options={catalogItems.map((item) => ({
              value: item.id,
              label: `${item.name}（${kindLabels[item.dataType as keyof typeof kindLabels] ?? item.dataType} · ${item.directoryName || "未分组"} · 登记 ${item.createdAt?.slice(0, 10) ?? ""}）`,
              name: item.name,
              description: item.description,
              details: `${kindLabels[item.dataType as keyof typeof kindLabels] ?? item.dataType} · ${item.directoryName || "未分组"} · 登记 ${item.createdAt?.slice(0, 10) ?? ""}`,
              disabled: excludedIds?.includes(item.id),
            }))}
          />
        </div>
      )}
      <Pagination
        size="small"
        current={catalogPage}
        pageSize={20}
        total={catalogTotal}
        showSizeChanger={false}
        onChange={(page) => {
          setCatalogPage(page);
          setCatalogSearchDelay(0);
        }}
        showTotal={(total) => `共 ${total} 份`}
      />
    </Modal>
  );
}
