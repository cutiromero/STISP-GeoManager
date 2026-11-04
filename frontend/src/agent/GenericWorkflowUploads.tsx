import {
  Alert,
  Button,
  Modal,
  Pagination,
  Select,
  Space,
  Tag,
  Typography,
  Upload,
} from "antd";
import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { agentApi } from "../api/agent";
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
}[] = [
  { key: "lithology", label: "地质图（必需）", kind: "vector" },
  { key: "faults", label: "构造线", kind: "vector" },
  { key: "coverage", label: "研究区范围", kind: "vector" },
  { key: "units", label: "填图单元表", kind: "table" },
  { key: "hematite", label: "赤铁矿化识别结果", kind: "raster" },
  { key: "chlorite", label: "绿泥石化识别结果", kind: "raster" },
  { key: "hydromica", label: "水云母化识别结果", kind: "raster" },
  { key: "calcite", label: "方解石化识别结果", kind: "raster" },
  { key: "dolomite", label: "白云石化识别结果", kind: "raster" },
];

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
}) {
  const [items, setItems] = useState<AgentWorkflowUpload[]>([]);
  useEffect(() => onCountChange?.(items.length), [items, onCountChange]);
  const [uploading, setUploading] = useState<string>();
  const [error, setError] = useState("");
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [catalogQuery, setCatalogQuery] = useState("");
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
    if (!catalogOpen) return;
    const controller = new AbortController();
    setCatalogLoading(true);
    setCatalogError("");
    const timer = setTimeout(() => {
      void agentApi
        .workflowCatalogResources(
          catalogQuery,
          { signal: controller.signal },
          catalogPage,
          directoryId,
        )
        .then((result) => {
          if (!controller.signal.aborted) {
            setCatalogItems(result.items);
            for (const item of result.items)
              catalogNames.current.set(item.id, item.name);
            setCatalogTotal(result.total);
            setDirectories(result.directories);
          }
        })
        .catch((reason) => {
          if (!controller.signal.aborted)
            setCatalogError(
              reason instanceof Error ? reason.message : "系统数据读取失败",
            );
        })
        .finally(() => {
          if (!controller.signal.aborted) setCatalogLoading(false);
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [catalogOpen, catalogQuery, batchId, catalogPage, directoryId]);
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
          setItems(
            result.items.map((item) => ({
              ...item,
              roleHint:
                genericRoles.find(
                  (role) =>
                    result.configuration?.roles[role.key] === item.resourceId,
                )?.key ?? item.roleHint,
            })),
          );
          setRestoreWarning(
            result.unavailableResourceIds.length
              ? `${result.unavailableResourceIds.length} 份上次资料已失效、变化或无权访问，请重新选择并核对。`
              : result.configuration && !result.configuration.roles.lithology
                ? "上次地质图为临时资料，未纳入可复用配置，请重新选择地质图。"
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
  }, [batchId, uploadOnly]);
  const roleOf = (item: AgentWorkflowUpload) =>
    Object.entries(inputs).find(([, id]) => id === item.resourceId)?.[0];
  const assign = (item: AgentWorkflowUpload, role: string | undefined) =>
    onInputsChange((old) => {
      const next = Object.fromEntries(
        Object.entries(old).filter(
          ([key, id]) => id !== item.resourceId && key !== role,
        ),
      );
      if (role) next[role] = item.resourceId;
      return next;
    });
  const recognize = async () => {
    setRecognizing(true);
    setRecognitionError("");
    try {
      const result = await agentApi.recognizeWorkflowRoles(batchId, model);
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
            !next[item.role]
          )
            next[item.role] = item.resourceId;
        }
        return next;
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
      className={`agent-demo-form${uploadOnly ? " agent-logic-intake" : ""}`}
      aria-label="上传本次资料"
    >
      <div className="agent-demo-form-heading">
        <strong>{uploadOnly ? "逻辑推理资料" : "上传本次资料"}</strong>
        {onClose && (
          <Button size="small" type="text" onClick={onClose}>
            收起
          </Button>
        )}
      </div>
      {!uploadOnly && (
        <p className="agent-demo-hint">
          可上传资料或选择当前项目的系统数据。上传资料只用于本次任务；系统数据仅建立引用，移除不影响原数据。地质图必需，其余资料可选，字段含义将在对话中确认。
        </p>
      )}
      {restoreWarning && <Alert type="warning" title={restoreWarning} />}
      <Space wrap>
        <Button
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
            <Button disabled={disabled || Boolean(uploading)}>
              上传文件/ZIP
            </Button>
          </Upload>
        )}
        {uploadOnly && items.length > 0 && (
          <Button
            size="small"
            danger
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
        onCancel={() => setCatalogOpen(false)}
        onOk={() => void addCatalog()}
        okText="加入本次任务"
        confirmLoading={Boolean(uploading)}
        okButtonProps={{
          disabled: disabled || !catalogSelected.length || Boolean(uploading),
        }}
      >
        <p>最近更新优先，共 {catalogTotal} 份。可搜索名称或说明，跨页选择。</p>
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
        <Select
          mode="multiple"
          style={{ width: "100%" }}
          aria-label="选择系统数据资源"
          placeholder="搜索名称并勾选资料"
          loading={catalogLoading}
          filterOption={false}
          showSearch={{
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
            <div style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>
              {option.data.label}
            </div>
          )}
          onChange={setCatalogSelected}
          disabled={disabled || Boolean(uploading)}
          options={catalogItems.map((item) => ({
            value: item.id,
            label: `${item.name}（${kindLabels[item.dataType as keyof typeof kindLabels] ?? item.dataType} · ${item.directoryName || "未分组"} · 登记 ${item.createdAt?.slice(0, 10) ?? ""}）`,
            disabled: items.some((entry) => entry.resourceId === item.id),
          }))}
        />
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
      {recognizing && (
        <Alert type="info" showIcon title="智能体正在识别资料角色…" />
      )}
      {suggestions && !recognizing && (
        <Alert
          type="success"
          showIcon
          title="智能体已识别资料角色，请核对后生成执行计划"
        />
      )}
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
      {!uploadOnly && items.length > 0 && (
        <Button
          loading={recognizing}
          disabled={disabled || Boolean(uploading)}
          onClick={() => void recognize()}
        >
          {recognitionError ? "重试识别" : "识别资料角色"}
        </Button>
      )}
      {items.map((item) => {
        const role = roleOf(item);
        return (
          <div key={item.id} className="agent-demo-fields">
            <Space orientation="vertical" size={2} style={{ minWidth: 0 }}>
              <Space size={6} wrap>
                <strong>{item.fileName}</strong>
                <Tag>{item.source === "catalog" ? "系统数据" : "上传资料"}</Tag>
                <Tag>{kindLabels[item.dataType]}</Tag>
                {uploadOnly && (
                  <Tag>
                    {genericRoles.find((entry) => entry.key === item.roleHint)
                      ?.label || "发送后识别角色"}
                  </Tag>
                )}
                {!uploadOnly && item.profile.crs && (
                  <Tag>{item.profile.crs}</Tag>
                )}
              </Space>
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
            {!uploadOnly && (
              <label>
                <span>资料角色</span>
                <Select
                  aria-label={`${item.fileName}的资料角色`}
                  allowClear
                  disabled={disabled || recognizing || Boolean(uploading)}
                  value={role}
                  placeholder="不使用"
                  options={genericRoles
                    .filter(
                      (entry) =>
                        entry.kind === item.dataType &&
                        (entry.kind !== "vector" ||
                          item.profile.geometryTypes?.some((geometry) =>
                            geometry.includes(
                              entry.key === "faults" ? "Line" : "Polygon",
                            ),
                          )),
                    )
                    .map((entry) => ({ value: entry.key, label: entry.label }))}
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
              disabled={disabled || recognizing || Boolean(uploading)}
              onClick={() => void remove(item)}
            >
              移除
            </Button>
          </div>
        );
      })}
      {uploadOnly && items.length > 0 && (
        <Alert
          type="info"
          showIcon
          title={`已选 ${items.length} 份资料，输入要求后发送。系统数据的已确认配置可复用；上传文件仅用于本次。`}
        />
      )}
      {!uploadOnly && items.length > 0 && !inputs.lithology && (
        <Alert type="warning" showIcon title="请把一份矢量面资料指定为地质图" />
      )}
    </section>
  );
}
