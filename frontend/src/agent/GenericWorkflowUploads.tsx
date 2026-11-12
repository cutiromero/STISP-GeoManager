import {
  Alert,
  Button,
  Checkbox,
  Input,
  Modal,
  Pagination,
  Select,
  Space,
  Tag,
  Typography,
  Upload,
} from "antd";
import {
  DatabaseOutlined,
  DeleteOutlined,
  FileOutlined,
  PlusOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { agentApi } from "../api/agent";
import { ResourceSearchLabel } from "./ResourceSearchLabel";
import { scheduleResourceSearch } from "./resourceSearch";
import type { ReasoningEffort } from "./ReasoningEffortControl";
import type {
  AgentWorkflowUpload,
  AgentWorkflowRoleResult,
  AgentWorkflowCatalogItem,
  AgentLogicConfigurationResult,
} from "../api/generated/types.gen";

type UploadRole = NonNullable<AgentWorkflowUpload["roleHint"]>;

export const genericRoles: {
  key: UploadRole;
  label: string;
  kind: AgentWorkflowUpload["dataType"];
  dataTypes?: AgentWorkflowUpload["dataType"][];
}[] = [
  { key: "lithology", label: "岩性图（必需）", kind: "vector" },
  { key: "faults", label: "构造线", kind: "vector" },
  { key: "coverage", label: "研究区范围", kind: "vector" },
  { key: "units", label: "填图单元表", kind: "table" },
  { key: "hematite", label: "赤铁矿化识别结果", kind: "raster" },
  { key: "chlorite", label: "绿泥石化识别结果", kind: "raster" },
  { key: "hydromica", label: "水云母化识别结果", kind: "raster" },
  { key: "calcite", label: "方解石化识别结果", kind: "raster" },
  { key: "dolomite", label: "白云石化识别结果", kind: "raster" },
  {
    key: "alterations",
    label: "蚀变识别资料（不限矿物种类，可多份）",
    kind: "raster",
    dataTypes: ["vector", "raster"],
  },
];

export const workflowRoleKey = (role: string, resourceId: number) =>
  role === "alterations" ? `${role}:${resourceId}` : role;
export const workflowRoleName = (role: string) =>
  role.startsWith("alterations:") ? "alterations" : role;

export function workflowInputsForRoles(
  inputs: Record<string, number>,
  allowedRoles?: string[],
) {
  return Object.fromEntries(
    Object.entries(inputs).flatMap(([key, id]) => {
      const role = workflowRoleName(key);
      if (!allowedRoles || allowedRoles.includes(role)) return [[key, id]];
      if (
        allowedRoles.includes("alterations") &&
        genericRoles.some(
          (entry) => entry.key === role && entry.kind === "raster",
        )
      )
        return [[workflowRoleKey("alterations", id), id]];
      return [];
    }),
  );
}

const kindLabels = { vector: "矢量", raster: "栅格", table: "表格" } as const;

function profileSummary(item: AgentWorkflowUpload) {
  const profile = item.profile;
  if (profile.kind === "raster")
    return `${profile.width ?? "?"}×${profile.height ?? "?"} 像元，${profile.bandCount ?? "?"} 个波段`;
  const geometry = profile.geometryTypes?.length
    ? `${profile.geometryTypes.join("、")}，`
    : "";
  return `${geometry}${profile.featureCount ?? 0} ${profile.kind === "table" ? "行" : "个要素"}，字段：${profile.fields
    .map((field) => field.name)
    .join("、")}`;
}

export default function GenericWorkflowUploads({
  batchId,
  model,
  inputs,
  disabled = false,
  onInputsChange,
  onActivityChange,
  uploadOnly = false,
  onCountChange,
  onClose,
  onRestored,
  onSelectionChange,
  presentation = "default",
  allowedRoles,
  reasoningEffort,
}: {
  batchId: string;
  model: string;
  inputs: Record<string, number>;
  disabled?: boolean;
  onInputsChange: Dispatch<SetStateAction<Record<string, number>>>;
  onActivityChange?: (busy: boolean) => void;
  uploadOnly?: boolean;
  onCountChange?: (count: number) => void;
  onClose?: () => void;
  onRestored?: (result: AgentLogicConfigurationResult) => void;
  onSelectionChange?: () => void;
  presentation?: "default" | "business-flow";
  allowedRoles?: string[];
  reasoningEffort?: ReasoningEffort;
}) {
  const polished = presentation === "business-flow";
  const allowedRoleKey = allowedRoles?.join(",");
  const [items, setItems] = useState<AgentWorkflowUpload[]>([]);
  useEffect(() => onCountChange?.(items.length), [items, onCountChange]);
  const [uploading, setUploading] = useState<string>();
  const [error, setError] = useState("");
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [catalogQuery, setCatalogQuery] = useState("");
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
  const [restoreWarning, setRestoreWarning] = useState("");
  const restoredCallback = useRef(onRestored);
  restoredCallback.current = onRestored;
  const [catalogSelected, setCatalogSelected] = useState<number[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [recognizing, setRecognizing] = useState(false);
  const [suggestions, setSuggestions] = useState<AgentWorkflowRoleResult>();
  const [recognitionError, setRecognitionError] = useState("");
  const manual = useRef(new Set<number>());
  const currentBatch = useRef(batchId);
  currentBatch.current = batchId;
  const inFlight = useRef(false);
  const changed = useRef(false);
  useEffect(() => {
    if (!catalogOpen || catalogComposing) return;
    setCatalogLoading(true);
    setCatalogError("");
    return scheduleResourceSearch(
      (signal) =>
        agentApi.workflowCatalogResources(
          catalogQuery,
          { signal },
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
    );
  }, [
    catalogOpen,
    catalogQuery,
    batchId,
    catalogPage,
    directoryId,
    catalogComposing,
  ]);
  useEffect(() => {
    onActivityChange?.(Boolean(uploading) || recognizing);
    return () => onActivityChange?.(false);
  }, [uploading, recognizing, onActivityChange]);
  useEffect(() => {
    setItems([]);
    setError("");
    setSuggestions(undefined);
    setRecognitionError("");
    setUploading(undefined);
    setRecognizing(false);
    inFlight.current = false;
    changed.current = false;
    manual.current.clear();
    setCatalogOpen(false);
    setCatalogComposing(false);
    setCatalogSelected([]);
    setCatalogQuery("");
    const controller = new AbortController();
    if (uploadOnly) {
      setUploading("上次配置");
      void agentApi
        .restoreLogicConfiguration(batchId, controller.signal)
        .then((result) => {
          if (controller.signal.aborted || currentBatch.current !== batchId)
            return;
          if (result.configuration)
            result = {
              ...result,
              configuration: {
                ...result.configuration,
                roles: workflowInputsForRoles(
                  result.configuration.roles,
                  allowedRoleKey?.split(","),
                ),
              },
            };
          setItems(
            result.items.map((item) => ({
              ...item,
              roleHint:
                genericRoles.find((role) =>
                  Object.entries(result.configuration?.roles ?? {}).some(
                    ([key, id]) =>
                      workflowRoleName(key) === role.key &&
                      id === item.resourceId,
                  ),
                )?.key ?? item.roleHint,
            })),
          );
          setRestoreWarning(
            result.unavailableResourceIds.length
              ? `${result.unavailableResourceIds.length} 份上次资料已失效、变化或无权访问，请重新选择并核对。`
              : result.configuration && !result.configuration.roles.lithology
                ? "上次岩性图为临时资料，未纳入可复用配置，请重新选择岩性图。"
                : "",
          );
          restoredCallback.current?.(result);
        })
        .catch((reason) => {
          if (!controller.signal.aborted)
            setRestoreWarning(
              reason instanceof Error
                ? reason.message
                : "上次配置读取失败，可重新选择资料",
            );
        })
        .finally(() => {
          if (!controller.signal.aborted) setUploading(undefined);
        });
      return () => controller.abort();
    }
    void agentApi
      .workflowUploads(batchId, { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted && !changed.current)
          setItems(result.items);
      })
      .catch(() => {
        // A new batch has nothing to restore.
      });
    return () => controller.abort();
  }, [batchId, uploadOnly, allowedRoleKey]);
  const roleOf = (item: AgentWorkflowUpload) =>
    workflowRoleName(
      Object.entries(inputs).find(([, id]) => id === item.resourceId)?.[0] ??
        "",
    ) || undefined;
  const assign = (item: AgentWorkflowUpload, role: string | undefined) =>
    onInputsChange((old) => {
      const next = Object.fromEntries(
        Object.entries(old).filter(
          ([key, id]) =>
            id !== item.resourceId &&
            key !== (role ? workflowRoleKey(role, item.resourceId) : role),
        ),
      );
      if (role) next[workflowRoleKey(role, item.resourceId)] = item.resourceId;
      return next;
    });
  const recognize = async () => {
    setRecognizing(true);
    setRecognitionError("");
    try {
      const result = reasoningEffort
        ? await agentApi.recognizeWorkflowRoles(batchId, model, reasoningEffort)
        : await agentApi.recognizeWorkflowRoles(batchId, model);
      if (currentBatch.current !== batchId) return;
      setSuggestions(result);
      onInputsChange((old) => {
        const next = Object.fromEntries(
          Object.entries(old).filter(([, id]) => manual.current.has(id)),
        );
        for (const item of result.items) {
          if (
            item.role &&
            !manual.current.has(item.resourceId) &&
            !next[workflowRoleKey(item.role, item.resourceId)]
          )
            next[workflowRoleKey(item.role, item.resourceId)] = item.resourceId;
        }
        return workflowInputsForRoles(next, allowedRoles);
      });
    } catch (reason) {
      if (currentBatch.current === batchId)
        setRecognitionError(
          reason instanceof Error
            ? reason.message
            : "角色识别失败，请重试或手动选择",
        );
    } finally {
      if (currentBatch.current === batchId) setRecognizing(false);
    }
  };
  const upload = async (files: File[]) => {
    if (inFlight.current) return;
    inFlight.current = true;
    changed.current = true;
    setError("");
    setUploading(`${files.length}个文件`);
    try {
      const result = await agentApi.uploadWorkflowBatch(batchId, files);
      if (currentBatch.current !== batchId) return;
      setItems((old) => [...old, ...result.items]);
      if (result.items.length) onSelectionChange?.();
      setError(
        result.errors
          .map((item) => `${item.fileName}：${item.detail}`)
          .join("；"),
      );
      if (result.items.length && !uploadOnly) await recognize();
    } catch (reason) {
      if (currentBatch.current === batchId)
        setError(reason instanceof Error ? reason.message : "上传失败");
    } finally {
      if (currentBatch.current === batchId) {
        setUploading(undefined);
        inFlight.current = false;
      }
    }
  };
  const remove = async (item: AgentWorkflowUpload) => {
    setError("");
    try {
      await agentApi.deleteWorkflowUpload(item.id);
      changed.current = true;
      setItems((old) => old.filter((entry) => entry.id !== item.id));
      onSelectionChange?.();
      assign(item, undefined);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除失败");
    }
  };
  const addCatalog = async () => {
    if (inFlight.current || !catalogSelected.length) return;
    inFlight.current = true;
    changed.current = true;
    setUploading("系统数据");
    setCatalogError("");
    try {
      const result = await agentApi.addWorkflowCatalogReferences(
        batchId,
        catalogSelected,
      );
      if (currentBatch.current !== batchId) return;
      setItems((old) => [
        ...old,
        ...result.items.filter(
          (item) => !old.some((entry) => entry.id === item.id),
        ),
      ]);
      setCatalogOpen(false);
      setCatalogSelected([]);
      onSelectionChange?.();
      if (!uploadOnly) await recognize();
    } catch (reason) {
      if (currentBatch.current === batchId)
        setCatalogError(
          reason instanceof Error ? reason.message : "系统数据引用失败",
        );
    } finally {
      if (currentBatch.current === batchId) {
        setUploading(undefined);
        inFlight.current = false;
      }
    }
  };
  return (
    <section
      className={
        polished
          ? "flow-materials"
          : `agent-demo-form${uploadOnly ? " agent-logic-intake" : ""}`
      }
      aria-label="上传本次资料"
    >
      <div
        className={
          polished ? "flow-materials-heading" : "agent-demo-form-heading"
        }
      >
        {polished ? (
          <div>
            <strong>
              {polished
                ? "任务资料"
                : uploadOnly
                  ? "逻辑推理资料"
                  : "上传本次资料"}
            </strong>
            {polished && <span>{items.length} 份已选</span>}
          </div>
        ) : (
          <strong>{uploadOnly ? "逻辑推理资料" : "上传本次资料"}</strong>
        )}
        {onClose && (
          <Button size="small" type="text" onClick={onClose}>
            收起
          </Button>
        )}
      </div>
      {!uploadOnly && (
        <p className="agent-demo-hint">
          可上传资料或选择当前项目的系统数据。上传资料只用于本次任务；系统数据仅建立引用，移除不影响原数据。岩性图必需，其余资料可选，字段含义将在对话中确认。
        </p>
      )}
      {restoreWarning && <Alert type="warning" title={restoreWarning} />}
      <Space wrap className={polished ? "flow-materials-tools" : undefined}>
        <Button
          icon={polished ? <PlusOutlined /> : undefined}
          aria-label="选择系统数据"
          disabled={disabled || Boolean(uploading) || recognizing}
          onClick={() => setCatalogOpen(true)}
        >
          选择系统数据
        </Button>
        {uploadOnly && (
          <Upload
            multiple
            showUploadList={false}
            disabled={disabled || Boolean(uploading)}
            accept=".zip,.shp,.dbf,.shx,.prj,.cpg,.gpkg,.geojson,.json,.tif,.tiff,.csv,.xlsx"
            beforeUpload={(file, files) => {
              if (file === files[0]) void upload(files);
              return false;
            }}
          >
            <Button
              icon={polished ? <UploadOutlined /> : undefined}
              aria-label="上传文件/ZIP"
              disabled={disabled || Boolean(uploading)}
            >
              上传文件/ZIP
            </Button>
          </Upload>
        )}
        {uploadOnly && items.length > 0 && (
          <Button
            size="small"
            danger={!polished}
            type={polished ? "text" : "default"}
            disabled={disabled || Boolean(uploading)}
            onClick={async () => {
              for (const item of items) await remove(item);
            }}
          >
            清空
          </Button>
        )}
      </Space>
      <Modal
        title="选择系统数据"
        open={catalogOpen}
        width={polished ? 720 : undefined}
        className={polished ? "flow-materials-picker" : undefined}
        onCancel={() => {
          setCatalogOpen(false);
          setCatalogComposing(false);
        }}
        onOk={() => void addCatalog()}
        okText="加入本次任务"
        confirmLoading={Boolean(uploading)}
        okButtonProps={{
          disabled: disabled || !catalogSelected.length || Boolean(uploading),
        }}
      >
        <p>
          {polished
            ? `从当前项目选择资料，已选 ${catalogSelected.length} 份`
            : `名称命中优先，同级最近更新优先，共 ${catalogTotal} 份。可搜索资料名称或说明；多个关键词以空格分隔且都要包含，可跨页选择。`}
        </p>
        {catalogError && <Alert type="error" title={catalogError} />}
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
              onChange={(event) => {
                setCatalogQuery(event.target.value);
                setCatalogPage(1);
              }}
            />
            <div
              className="flow-materials-candidates"
              aria-busy={catalogLoading}
            >
              {catalogItems.map((item) => (
                <Checkbox
                  key={item.id}
                  className="flow-materials-candidate"
                  aria-label={`选择${item.name}`}
                  checked={catalogSelected.includes(item.id)}
                  disabled={
                    disabled ||
                    Boolean(uploading) ||
                    items.some((entry) => entry.resourceId === item.id)
                  }
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
                onSearch: (value) => {
                  setCatalogQuery(value);
                  setCatalogPage(1);
                },
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
              disabled={disabled || Boolean(uploading)}
              options={catalogItems.map((item) => ({
                value: item.id,
                label: `${item.name}（${kindLabels[item.dataType as keyof typeof kindLabels] ?? item.dataType} · ${item.directoryName || "未分组"} · 登记 ${item.createdAt?.slice(0, 10) ?? ""}）`,
                name: item.name,
                description: item.description,
                details: `${kindLabels[item.dataType as keyof typeof kindLabels] ?? item.dataType} · ${item.directoryName || "未分组"} · 登记 ${item.createdAt?.slice(0, 10) ?? ""}`,
                disabled: items.some((entry) => entry.resourceId === item.id),
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
          onChange={setCatalogPage}
          showTotal={(total) => `共 ${total} 份`}
        />
      </Modal>
      {!uploadOnly && (
        <Upload.Dragger
          multiple
          showUploadList={false}
          disabled={disabled || Boolean(uploading) || recognizing}
          accept=".zip,.shp,.dbf,.shx,.prj,.cpg,.sbn,.sbx,.qix,.gpkg,.geojson,.json,.tif,.tiff,.csv,.xlsx"
          beforeUpload={(file, files) => {
            if (file === files[0]) void upload(files);
            return false;
          }}
        >
          <p>
            {uploading
              ? `正在上传并读取资料：${uploading}`
              : "点击或拖入多个文件或总ZIP：Shapefile、GeoPackage、GeoJSON、GeoTIFF、CSV、Excel"}
          </p>
        </Upload.Dragger>
      )}
      {uploadOnly && uploading && (
        <Typography.Text role="status">正在读取：{uploading}</Typography.Text>
      )}
      {error && <Alert type="error" showIcon title={error} />}
      {recognizing &&
        (polished ? (
          <p className="flow-materials-footnote" role="status">
            AI 正在识别资料用途…
          </p>
        ) : (
          <Alert type="info" showIcon title="智能体正在识别资料角色…" />
        ))}
      {suggestions &&
        !recognizing &&
        (polished ? (
          <p className="flow-materials-footnote" role="status">
            AI 已给出用途建议，可在列表中调整。
          </p>
        ) : (
          <Alert
            type="success"
            showIcon
            title="智能体已识别资料角色，请核对后生成执行计划"
          />
        ))}
      {!inputs.lithology &&
        suggestions?.questions.map((question) => (
          <Alert key={question} type="warning" title={question} />
        ))}
      {recognitionError && (
        <Alert
          type="error"
          title={recognitionError}
          description="可重试识别或手动选择资料角色"
        />
      )}
      {(!uploadOnly || polished) &&
        items.length > 0 &&
        (!polished || items.some((item) => !roleOf(item))) && (
          <Button
            loading={recognizing}
            disabled={disabled || Boolean(uploading)}
            onClick={() => void recognize()}
          >
            {recognitionError
              ? "重试识别"
              : polished
                ? "AI 识别资料用途"
                : "识别资料角色"}
          </Button>
        )}
      {polished && items.length === 0 && !uploading && (
        <div className="flow-materials-empty">
          <FileOutlined />
          <strong>添加本次分析要使用的资料</strong>
          <p>可选择平台数据或上传文件，原始资料保持只读。</p>
        </div>
      )}
      {polished && items.length > 0 && (
        <div className="flow-materials-columns">
          <span>资料</span>
          <span>用途</span>
        </div>
      )}
      <div
        className={
          polished
            ? "flow-materials-list"
            : uploadOnly
              ? "agent-logic-files"
              : undefined
        }
      >
        {items.map((item) => {
          const role = roleOf(item);
          return (
            <div
              key={item.id}
              className={polished ? "flow-materials-row" : "agent-demo-fields"}
            >
              {polished && (
                <span className="flow-materials-file-icon">
                  {item.source === "catalog" ? (
                    <DatabaseOutlined />
                  ) : (
                    <FileOutlined />
                  )}
                </span>
              )}
              <Space orientation="vertical" size={2} style={{ minWidth: 0 }}>
                <Space size={6} wrap>
                  <strong title={item.fileName}>{item.fileName}</strong>
                  {!polished && (
                    <>
                      <Tag>
                        {item.source === "catalog" ? "系统数据" : "上传资料"}
                      </Tag>
                      <Tag>{kindLabels[item.dataType]}</Tag>
                      {uploadOnly && (
                        <Tag>
                          {genericRoles.find(
                            (entry) => entry.key === item.roleHint,
                          )?.label || "发送后识别角色"}
                        </Tag>
                      )}
                      {!uploadOnly && item.profile.crs && (
                        <Tag>{item.profile.crs}</Tag>
                      )}
                    </>
                  )}
                </Space>
                {polished && (
                  <small className="flow-materials-file-meta">
                    {kindLabels[item.dataType]} ·{" "}
                    {item.source === "catalog" ? "平台数据" : "本次上传"}
                  </small>
                )}
                {!uploadOnly && (
                  <Typography.Text type="secondary">
                    {profileSummary(item)}
                  </Typography.Text>
                )}
                {suggestions?.items.find((entry) => entry.uploadId === item.id)
                  ?.reason && (
                  <Typography.Text type="secondary">
                    {
                      suggestions.items.find(
                        (entry) => entry.uploadId === item.id,
                      )?.reason
                    }
                  </Typography.Text>
                )}
                {item.profile.warnings?.map((warning) => (
                  <Typography.Text key={warning} type="warning">
                    {warning}
                  </Typography.Text>
                ))}
              </Space>
              {(!uploadOnly || polished) && (
                <label>
                  <span>{polished ? "用途" : "资料角色"}</span>
                  <Select
                    aria-label={`${item.fileName}的资料角色`}
                    allowClear
                    disabled={disabled || recognizing || Boolean(uploading)}
                    value={role}
                    placeholder={polished ? "待指定" : "不使用"}
                    options={genericRoles
                      .filter(
                        (entry) =>
                          (!allowedRoles || allowedRoles.includes(entry.key)) &&
                          (entry.dataTypes ?? [entry.kind]).includes(
                            item.dataType,
                          ) &&
                          (entry.key === "alterations" ||
                            entry.kind !== "vector" ||
                            item.profile.geometryTypes?.some((geometry) =>
                              geometry.includes(
                                entry.key === "faults" ? "Line" : "Polygon",
                              ),
                            )),
                      )
                      .map((entry) => ({
                        value: entry.key,
                        label: entry.label,
                      }))}
                    onChange={(value: string | undefined) => {
                      manual.current.add(item.resourceId);
                      if (value && inputs[value])
                        manual.current.add(inputs[value]);
                      assign(item, value);
                    }}
                  />
                </label>
              )}
              <Button
                size="small"
                type={polished ? "text" : "default"}
                icon={polished ? <DeleteOutlined /> : undefined}
                aria-label={polished ? `移除${item.fileName}` : undefined}
                disabled={disabled || recognizing || Boolean(uploading)}
                onClick={() => void remove(item)}
              >
                {polished ? null : "移除"}
              </Button>
            </div>
          );
        })}
      </div>
      {polished && (
        <p className="flow-materials-footnote">
          用途可由 AI
          建议或手动指定，启动后会核对资料与字段。移除仅取消本次引用。
        </p>
      )}
      {uploadOnly && !polished && items.length > 0 && (
        <Alert
          type="info"
          showIcon
          title={`已选 ${items.length} 份资料，输入要求后发送。系统数据的已确认配置可复用；上传文件仅用于本次。`}
        />
      )}
      {!uploadOnly && items.length > 0 && !inputs.lithology && (
        <Alert type="warning" showIcon title="请把一份矢量面资料指定为岩性图" />
      )}
    </section>
  );
}
